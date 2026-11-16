"""An environment is published, never upgraded in place (dev-lab #632): an upgrade completes under a live holder."""

from __future__ import annotations

import os
import subprocess
import threading
import venv
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from lab_commons.census import Process, processes

from dev_lab.dev import dep, venvcurrent, venvpointer
from dev_lab.dev.jsrun import node_path
from dev_lab.dev.venvpath import VENV_LAYOUTS

LAUNCHER = Path(dep.__file__).with_name('agent_launcher.js')
TAIL = VENV_LAYOUTS[os.name][1:]


def _project(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / 'pyproject.toml').write_text(
        '[project]\nname="example"\nversion="0"\n[project.optional-dependencies]\ndev=[]\n', encoding='utf-8'
    )
    old = root / venvpointer.HOME / 'old'
    venv.EnvBuilder(with_pip=False).create(old)
    venvcurrent.publish(root, old)
    return old


def _uv(argv, **options: object) -> SimpleNamespace:
    """A fake uv: a ``sync`` builds a real venv where ``UV_PROJECT_ENVIRONMENT`` says, as uv does."""
    env = options.get('env') or {}
    if 'sync' in argv:
        venv.EnvBuilder(with_pip=False).create(env['UV_PROJECT_ENVIRONMENT'])
    return SimpleNamespace(returncode=0, stdout='', stderr='')


def _census() -> Callable[[], list]:
    """The real process table, every process old enough to count (a planted holder is seconds old)."""
    return lambda: [replace(one, age_s=3600.0) for one in processes()]


def _launch(root: Path) -> str:
    env = {**os.environ, 'CLAUDE_PROJECT_DIR': str(root)}
    done = subprocess.run(
        [str(node_path()), str(LAUNCHER), '-c', 'import sys; print(sys.prefix)'],
        capture_output=True, text=True, encoding='utf-8', env=env, cwd=root, check=False, timeout=60,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def test_an_upgrade_under_a_live_holder_completes_and_the_old_env_goes_only_after_the_holder(tmp_path) -> None:
    root = tmp_path / 'main'
    old = _project(root)
    assert Path(_launch(root)).resolve() == old.resolve(), 'PLANTED CONTROL: before the upgrade, the old env'
    holder = subprocess.Popen([str(old.joinpath(*TAIL)), '-c', 'import time; time.sleep(120)'])
    try:
        assert dep.main(['--bootstrap', str(root)], run=_uv, cwd=tmp_path, census=_census()) == 0
        new = venvpointer.current(root)
        assert new != old
        assert new.joinpath(*TAIL).is_file()
        assert Path(_launch(root)).resolve() == new.resolve(), 'the next launch takes the published env'
        assert holder.poll() is None, 'the holder runs on, undisturbed'
        assert old.is_dir(), 'PLANTED CONTROL: an env a holder runs from is never reclaimed'
        assert any('kept' in line for line in venvcurrent.reclaim(root, census=_census()))
        assert old.is_dir()
    finally:
        holder.kill()
        holder.wait(timeout=30)
    assert venvcurrent.reclaim(root, census=_census()) == (f'reclaimed {old}',)
    assert not old.exists()
    assert venvpointer.current(root) == new, 'the current env is never reclaimed'


def test_an_env_being_built_is_not_reclaimed_and_a_failed_build_is_dropped(tmp_path) -> None:
    root = tmp_path / 'main'
    _project(root)
    building = venvcurrent.fresh(root)
    building.mkdir()
    assert venvcurrent.reclaim(root, census=list) == ()
    assert building.is_dir()
    venvcurrent.abandon(building)
    assert not building.exists()
    assert not building.with_name(building.name + venvcurrent.BUILDING).exists()


def test_a_reader_never_sees_a_partial_pointer(tmp_path) -> None:
    root = tmp_path / 'main'
    _project(root)
    names = ('a' * 40, 'b' * 40)
    for name in names:
        (root / venvpointer.HOME / name).mkdir()
    seen: set[str | None] = set()
    stop = threading.Event()

    def read() -> None:
        while not stop.is_set():
            env = venvpointer.named(root)
            seen.add(env.name if env else None)

    reader = threading.Thread(target=read)
    reader.start()
    try:
        for n in range(300):
            venvcurrent.publish(root, root / venvpointer.HOME / names[n % 2])
    finally:
        stop.set()
        reader.join()
    assert seen <= {*names, 'old'}, f'a partial or missing pointer was read: {seen - {*names, "old"}}'
    assert set(names) <= seen, 'PLANTED CONTROL: the reader saw both publications'


def test_a_legacy_venv_directory_moves_aside_once_nothing_runs_from_it(tmp_path) -> None:
    root = tmp_path / 'main'
    legacy = root / venvpointer.ALIAS
    venv.EnvBuilder(with_pip=False).create(legacy)
    assert venvpointer.current(root) == legacy, 'no pointer: the legacy layout resolves'
    new = root / venvpointer.HOME / 'new'
    new.mkdir(parents=True)
    assert 'legacy directory' in venvcurrent.publish(root, new)
    assert venvpointer.current(root) == new, 'the pointer rules before the migration'
    holder = Process(1, 0, str(legacy.joinpath(*TAIL)), 'python -m app run', 60.0, str(tmp_path))
    assert 'kept' in venvcurrent.migrate_legacy(root, census=lambda: [holder]), 'PLANTED CONTROL: held, it stays'
    assert venvcurrent.migrate_legacy(root, census=list).startswith('legacy')
    assert legacy.resolve() == new.resolve(), '.venv is now the alias of the current env'
