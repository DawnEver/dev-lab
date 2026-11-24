"""venvprune: a checkout keeps its current, its newest and every held environment; the rest go on --apply."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from lab_commons.census import Process

from dev_lab.dev import venvcurrent, venvprune
from dev_lab.dev._deny_delete_row import RECURSIVE_DELETE
from dev_lab.dev.venvpointer import HOME


def _checkout(root: Path, *names: str, current: str | None) -> Path:
    for name in names:
        (root / HOME / name).mkdir(parents=True)
        (root / HOME / name / 'payload').write_bytes(b'x' * 10)
    if current is not None:
        venvcurrent.publish(root, root / HOME / current, census=list)
    return root


def _keeps(rows) -> dict[str, str]:
    return {row.env.name: row.keep for row in rows}


def test_keeps_current_newest_and_held_and_marks_the_rest(tmp_path: Path) -> None:
    root = _checkout(
        tmp_path / 'repo',
        'a-20261101T000000Z', 'a-20261102T000000Z', 'a-20261103T000000Z', 'a-20261104T000000Z',
        current='a-20261102T000000Z',
    )  # fmt: skip
    held = root / HOME / 'a-20261101T000000Z'
    table = (Process(7, 0, str(held / 'Scripts' / 'python.exe'), 'python -m app', 3600.0, str(tmp_path)),)
    rows = venvprune.plan(root, census=lambda: table)
    assert _keeps(rows) == {
        'a-20261101T000000Z': 'held by 1 process(es)',
        'a-20261102T000000Z': 'current',
        'a-20261103T000000Z': '',
        'a-20261104T000000Z': 'newest',
    }
    assert all(row.bytes >= 10 for row in rows)


def test_dry_run_removes_nothing_and_apply_removes_only_the_unkept(tmp_path: Path, capsys) -> None:
    root = _checkout(tmp_path / 'repo', 'a-20261101T000000Z', 'a-20261102T000000Z', current='a-20261101T000000Z')
    old = root / HOME / 'a-20261101T000000Z'
    _checkout(tmp_path / 'repo', 'a-20261100T000000Z', current=None)
    stale = root / HOME / 'a-20261100T000000Z'
    assert venvprune.main([str(tmp_path)], census=tuple) == 0
    out = capsys.readouterr().out
    assert f'would remove {stale.name}' in out
    assert 'reclaimable' in out
    assert stale.is_dir()
    assert venvprune.main(['--apply', str(tmp_path)], census=tuple) == 0
    assert not stale.exists()
    assert old.is_dir()
    assert (root / HOME / 'a-20261102T000000Z').is_dir()


def test_worktrees_under_a_root_are_found(tmp_path: Path) -> None:
    lane = tmp_path / 'repo' / '.claude' / 'worktrees' / 'lane'
    tree = _checkout(lane, 'b-20261101T000000Z', current='b-20261101T000000Z')
    _checkout(tmp_path / 'repo', 'a-20261101T000000Z', current='a-20261101T000000Z')
    assert set(venvprune.checkouts([tmp_path])) == {tmp_path / 'repo', tree}
    assert set(venvprune.checkouts([tree])) == {tree}


def test_a_checkout_without_a_pointer_is_left_alone(tmp_path: Path) -> None:
    root = _checkout(tmp_path / 'repo', 'a-20261101T000000Z', 'a-20261102T000000Z', current=None)
    assert venvprune.plan(root, census=tuple) == ()


def test_the_recursive_delete_refusal_names_the_door() -> None:
    assert 'dev_lab.dev.venvprune --apply' in str(RECURSIVE_DELETE['remedy'])


def _half_built(root: Path, name: str, pid: int, *, lock: bool = True) -> Path:
    env = root / HOME / name
    env.mkdir(parents=True)
    (env / 'payload').write_bytes(b'x' * 10)
    env.with_name(name + venvcurrent.BUILDING).write_text(str(pid), encoding='utf-8')
    if lock:
        (root / HOME / venvcurrent.BUILD_LOCK).write_bytes(f'\x00{pid} 2026-11-22T00:21:45Z\n'.encode())
    return env


def _alive(pid: int, tmp_path: Path) -> Callable[[], tuple[Process, ...]]:
    return lambda: (Process(pid, 0, 'uv.exe', 'uv sync', 60.0, str(tmp_path)),)


def test_an_abandoned_build_in_a_legacy_checkout_is_listed_and_reclaimed(tmp_path: Path, capsys) -> None:
    root = tmp_path / 'ai-lab'
    (root / '.venv').mkdir(parents=True)  # legacy plain environment: no pointer
    env = _half_built(root, 'b5-20261122T002147Z', 36556)
    marker = env.with_name(env.name + venvcurrent.BUILDING)
    assert venvprune.main([str(root)], census=tuple) == 0
    out = capsys.readouterr().out
    assert 'abandoned builds' in out
    assert f'would remove {env.name}' in out
    assert 'reclaimable: 10 bytes' in out
    assert env.is_dir()
    assert marker.is_file()
    assert venvprune.main(['--apply', str(root)], census=tuple) == 0
    assert not env.exists()
    assert not marker.exists()
    assert not (root / HOME / venvcurrent.BUILD_LOCK).exists()
    assert (root / '.venv').is_dir()


def test_a_live_builder_is_never_touched(tmp_path: Path, capsys) -> None:
    root = tmp_path / 'repo'
    (root / '.venv').mkdir(parents=True)
    env = _half_built(root, 'b5-20261124T000000Z', 4242)
    assert venvprune.main(['--apply', str(root)], census=_alive(4242, tmp_path)) == 0
    out = capsys.readouterr().out
    assert f'keep         {env.name}  (builder pid 4242 alive)' in out
    assert env.is_dir()
    assert env.with_name(env.name + venvcurrent.BUILDING).is_file()
    assert (root / HOME / venvcurrent.BUILD_LOCK).is_file()


def test_a_build_older_than_the_wall_is_abandoned_even_if_its_pid_was_reused(tmp_path: Path) -> None:
    root = tmp_path / 'repo'
    (root / '.venv').mkdir(parents=True)
    env = _half_built(root, 'b5-20261101T000000Z', 4242, lock=False)
    marker = env.with_name(env.name + venvcurrent.BUILDING)
    then = marker.stat().st_mtime - venvcurrent.BUILD_WALL_S - 60
    os.utime(marker, (then, then))
    assert venvprune.main(['--apply', str(root)], census=_alive(4242, tmp_path)) == 0
    assert not env.exists()


def test_a_dead_builder_in_a_linked_checkout_is_reclaimed_not_kept_as_being_built(tmp_path: Path) -> None:
    root = _checkout(tmp_path / 'repo', 'a-20261101T000000Z', current='a-20261101T000000Z')
    env = _half_built(root, 'a-20261102T000000Z', 99999, lock=False)
    assert env.name not in _keeps(venvprune.plan(root, census=tuple))
    assert venvprune.main(['--apply', str(root)], census=tuple) == 0
    assert not env.exists()
    assert (root / HOME / 'a-20261101T000000Z').is_dir()
