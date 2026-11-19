"""An environment is published, never upgraded in place (dev-lab #632): an upgrade completes under a live holder."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import venv
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from lab_commons.census import Process, processes

from dev_lab.dev import dep, venvcurrent, venvpointer
from dev_lab.dev.jsrun import node_path
from dev_lab.dev.servelock import held
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
    assert 'kept' in venvcurrent.reclaim(root, census=lambda: [holder])[0], 'PLANTED CONTROL: held, it stays'
    assert legacy.is_dir()
    assert venvcurrent.reclaim(root, census=list)[0].startswith('legacy')
    assert legacy.resolve() == new.resolve(), '.venv is now the alias of the current env'


def test_a_bootstrap_whose_venv_alias_stays_stale_fails_and_names_why(tmp_path, capsys) -> None:
    """O16: the pointer moved but a held legacy ``.venv`` still runs the old env -- the door must not report success."""
    root = tmp_path / 'main'
    _project(root)
    (root / venvpointer.POINTER).unlink()
    legacy = root / venvpointer.ALIAS
    legacy.unlink() if legacy.is_symlink() else legacy.rmdir()  # the junction _project published: now legacy
    venv.EnvBuilder(with_pip=False).create(legacy)
    holder = Process(1, 0, str(legacy.joinpath(*TAIL)), 'python -m app run', 3600.0, str(tmp_path))
    assert dep.main(['--bootstrap', str(root)], run=_uv, cwd=tmp_path, census=lambda: [holder]) == 1
    out = capsys.readouterr().out
    assert f'{legacy} still runs' in out
    assert str(venvpointer.current(root).joinpath(*TAIL)) in out, 'the door: the published interpreter'
    assert dep.main(['--bootstrap', str(root)], run=_uv, cwd=tmp_path, census=list) == 0, 'PLANTED CONTROL: unheld'
    assert legacy.resolve() == venvpointer.current(root).resolve()


_HOLD = """
import os, sys, time
from pathlib import Path
from dev_lab.dev import venvcurrent
with venvcurrent.exclusive_build(Path(sys.argv[1])):
    print(os.getpid(), flush=True)
    time.sleep(60)
"""


def _holder(root: Path) -> tuple[subprocess.Popen[str], int]:
    """A second process holding *root*'s build lock, and its pid (a Windows venv python is a launcher's child)."""
    child = subprocess.Popen(
        [sys.executable, '-c', _HOLD, str(root)], stdout=subprocess.PIPE, text=True, encoding='utf-8'
    )
    assert child.stdout is not None
    return child, int(child.stdout.readline())


def test_a_second_bootstrap_on_one_worktree_is_refused_naming_the_first(tmp_path, capsys) -> None:
    root = tmp_path / 'wt'
    old = _project(root)
    child, pid = _holder(root)
    try:
        assert dep.main(['--bootstrap', str(root)], run=_uv, cwd=tmp_path, census=list) == 1
        out = capsys.readouterr().out
        assert f'pid {pid}' in out, out
        assert 'started' in out, out
        assert f'dev_lab.dev.stoprun --pid {pid}' in out, out
        assert venvpointer.named(root) == old, 'the refused run published nothing'
        assert [p.name for p in (root / venvpointer.HOME).iterdir() if p.is_dir()] == ['old'], 'and built nothing'
    finally:
        os.kill(pid, signal.SIGTERM)  # the holder itself dies; its launcher follows
        child.kill()
        child.wait()
    assert dep.main(['--bootstrap', str(root)], run=_uv, cwd=tmp_path, census=list) == 0, 'a dead holder is taken over'
    assert venvpointer.named(root) != old


def test_a_single_bootstrap_holds_the_lock_only_while_it_runs(tmp_path) -> None:
    root = tmp_path / 'wt'
    _project(root)
    seen: list[bool] = []

    def uv(argv: list[str], **options: object) -> SimpleNamespace:
        with held(root / venvpointer.HOME / venvcurrent.BUILD_LOCK) as free:
            seen.append(free)
        return _uv(argv, **options)

    assert dep.main(['--bootstrap', str(root)], run=uv, cwd=tmp_path, census=list) == 0
    assert seen, 'the fake uv ran'
    assert not any(seen), 'PLANTED CONTROL: the lock is held during the build'
    with venvcurrent.exclusive_build(root):
        pass  # released after the run


def test_a_reclaim_while_a_build_holds_the_worktree_removes_nothing(tmp_path) -> None:
    """A reclaim racing a build deleted the environment the build was about to publish (two runs, one worktree).

    Reclaim reads the live pointer, then walks ``.venvs``; a build that publishes between the two had its new
    environment reclaimed as 'not current'. So a reclaim outside the build takes the same build lock and skips.
    """
    root = tmp_path / 'wt'
    _project(root)
    fresh = root / venvpointer.HOME / 'fresh'  # unmarked and unpublished: exactly what the race sees
    venv.EnvBuilder(with_pip=False).create(fresh)
    child, pid = _holder(root)
    try:
        lines = venvcurrent.reclaim(root, census=list)
        assert fresh.is_dir(), lines
        assert any(f'pid {pid}' in line for line in lines), lines
    finally:
        os.kill(pid, signal.SIGTERM)
        child.kill()
        child.wait()
    assert any(line.startswith('reclaimed') for line in venvcurrent.reclaim(root, census=list)), 'PLANTED CONTROL'
    assert not fresh.exists(), 'PLANTED CONTROL: unheld, the same environment is reclaimed'
