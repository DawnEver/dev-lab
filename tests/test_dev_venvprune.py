"""venvprune: a checkout keeps its current, its newest and every held environment; the rest go on --apply."""

from __future__ import annotations

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
