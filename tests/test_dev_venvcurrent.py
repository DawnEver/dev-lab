"""An environment is published, never upgraded in place (dev-lab #632): an upgrade completes under a live holder."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
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


def test_a_legacy_venv_directory_moves_aside_once_and_becomes_current_when_no_pointer_names_one(tmp_path) -> None:
    root = tmp_path / 'main'
    legacy = root / venvpointer.RETIRED_ALIAS
    venv.EnvBuilder(with_pip=False).create(legacy)
    assert venvpointer.current(root) == root / venvpointer.POINTER, 'no pointer: nothing is current, .venv unread'
    holder = Process(1, 0, str(legacy.joinpath(*TAIL)), 'python -m app run', 60.0, str(tmp_path))
    assert 'kept' in venvcurrent.retire_alias(root, census=lambda: [holder]), 'PLANTED CONTROL: held, it stays'
    assert legacy.is_dir()
    assert venvcurrent.retire_alias(root, census=list).startswith('legacy')
    assert not legacy.exists(), 'gone once'
    adopted = venvpointer.named(root)
    assert adopted is not None, 'no pointer named one: the moved directory is published'
    assert adopted.joinpath(*TAIL).is_file()
    assert venvcurrent.retire_alias(root, census=list) == '', 'once: nothing left to retire'


def test_a_legacy_directory_beside_a_pointer_moves_aside_and_the_pointer_stays(tmp_path) -> None:
    root = tmp_path / 'main'
    new = root / venvpointer.HOME / 'new'
    new.mkdir(parents=True)
    venvcurrent.publish(root, new)
    (root / venvpointer.RETIRED_ALIAS).mkdir()
    assert venvcurrent.retire_alias(root, census=list).startswith('legacy')
    assert venvpointer.named(root) == new, 'the pointer already ruled: it is unchanged'


def test_a_venv_link_is_removed_once_and_publish_writes_none(tmp_path) -> None:
    root = tmp_path / 'main'
    new = root / venvpointer.HOME / 'new'
    new.mkdir(parents=True)
    assert venvcurrent.publish(root, new).endswith('-> new')
    alias = root / venvpointer.RETIRED_ALIAS
    assert not venvcurrent.holds_alias(root), 'publish writes no alias'
    if sys.platform == 'win32':
        cmd = shutil.which('cmd')
        assert cmd is not None
        subprocess.run([cmd, '/c', 'mklink', '/J', str(alias), str(new)], check=True, capture_output=True)
    else:
        alias.symlink_to(new, target_is_directory=True)
    assert venvcurrent.holds_alias(root)
    assert 'removed' in venvcurrent.retire_alias(root, census=list)
    assert not venvcurrent.holds_alias(root)
    assert new.is_dir(), 'PLANTED CONTROL: the environment the link named is untouched'


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


def _release(child: subprocess.Popen[str], pid: int, root: Path) -> None:
    """Kill the holder and wait until the kernel lets go of its lock.

    On Windows ``child`` is the venv launcher and ``pid`` its python child: ``child.wait()`` returns when the launcher
    exits, before the terminated child's handles close, so the lock can still read held for a moment.
    """
    os.kill(pid, signal.SIGTERM)  # the holder itself dies; its launcher follows
    child.kill()
    child.wait()
    deadline = time.monotonic() + 10.0
    while True:
        try:
            with venvcurrent.exclusive_build(root):
                return
        except venvcurrent.BuildBusy:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.05)


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
        _release(child, pid, root)
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
        _release(child, pid, root)
    assert any(line.startswith('reclaimed') for line in venvcurrent.reclaim(root, census=list)), 'PLANTED CONTROL'
    assert not fresh.exists(), 'PLANTED CONTROL: unheld, the same environment is reclaimed'
