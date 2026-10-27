"""WORKTREE-ARCHIVE on planted worktrees: a tree's run outputs are MOVED home, its work saved, and nothing removed.

Planted controls, one per way the archiver could be wrong while looking right: an identical file is skipped (the
main copy is untouched), a differing one lands beside it as ``<name>.<worktree>``, a new one is RENAMED (same
inode, never a copy), a live tree is refused before anything moves, a venv never travels, and uncommitted tracked
work arrives as a patch with the untracked files beside it. REAL ``git worktree add``, because the decisions are
about what git and the filesystem say.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest
from lab_commons.census import Process

from dev_lab.dev import worktree_archive
from dev_lab.dev.famtests.visibility import plant_checkout
from dev_lab.dev.worktree_archive import archive
from dev_lab.dev.worktrees import main

_GIT = shutil.which('git') or 'git'
_DAY = date(2026, 10, 21)
_LOG = Path('output/logs/26/10/21/run')


def _run(cwd: Path, *args: str) -> None:
    subprocess.run([_GIT, *args], cwd=cwd, check=True, capture_output=True, timeout=60)


def _idle() -> tuple[Process, ...]:
    return ()


@pytest.fixture
def work(tmp_path: Path) -> Path:
    """A main checkout ignoring ``output/`` and ``.claude/``, with one linked worktree ``lane``."""
    root = plant_checkout(tmp_path, trunk='main').work
    (root / '.gitignore').write_text('output/\n.claude/\nresults/\n.venv/\n', encoding='utf-8')
    _run(root, 'add', '.gitignore')
    _run(root, 'commit', '-q', '-m', 'ignore')
    _run(root, 'worktree', 'add', '-q', '-b', 'lane', str(root / '.claude' / 'worktrees' / 'lane'))
    return root


def _plant(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return path


def _lane(work: Path) -> Path:
    return work / '.claude' / 'worktrees' / 'lane'


def test_an_identical_file_is_skipped_and_the_main_copy_untouched(work: Path) -> None:
    home = _plant(work / _LOG / 'a.txt', 'same')
    _plant(_lane(work) / _LOG / 'a.txt', 'same')
    stamp = home.stat().st_mtime_ns
    done = archive(work, 'lane', census=_idle, today=_DAY)
    assert done.safe, done.lines()
    assert done.identical == (_LOG / 'a.txt',)
    assert not done.moved
    assert home.stat().st_mtime_ns == stamp
    assert not (work / _LOG / 'a.txt.lane').exists()


def test_a_differing_file_lands_beside_the_main_one_named_for_its_worktree(work: Path) -> None:
    _plant(work / _LOG / 'a.txt', 'main')
    _plant(_lane(work) / _LOG / 'a.txt', 'lane')
    done = archive(work, 'lane', census=_idle, today=_DAY)
    assert done.safe, done.lines()
    assert done.renamed == (_LOG / 'a.txt.lane',)
    assert (work / _LOG / 'a.txt').read_text(encoding='utf-8') == 'main'
    assert (work / _LOG / 'a.txt.lane').read_text(encoding='utf-8') == 'lane'
    assert not (_lane(work) / _LOG / 'a.txt').exists()


def test_a_new_file_is_renamed_never_copied(work: Path) -> None:
    source = _plant(_lane(work) / _LOG / 'deep' / 'b.bin', 'payload')
    inode = source.stat().st_ino
    done = archive(work, 'lane', census=_idle, today=_DAY)
    assert done.safe, done.lines()
    assert done.moved == (_LOG / 'deep' / 'b.bin',)
    assert not source.exists()
    assert (work / _LOG / 'deep' / 'b.bin').stat().st_ino == inode, 'a rename keeps the inode; a copy would not'


def test_a_live_tree_is_refused_before_anything_moves(work: Path) -> None:
    source = _plant(_lane(work) / _LOG / 'b.txt', 'mid-run')
    exe = _lane(work) / '.venv' / 'Scripts' / 'python.exe'
    run = Process(4242, 1, str(exe), f'{exe} -m consumer case sweep', 600.0, str(_lane(work)))
    done = archive(work, 'lane', census=lambda: (run,), today=_DAY)
    assert not done.safe
    assert 'pid 4242' in (done.refused or '')
    assert source.exists()
    assert not (work / 'output' / 'worktree-archive').exists(), 'a refusal writes nothing'


def test_a_session_working_in_the_tree_is_a_live_tree_too(work: Path) -> None:
    session = Process(77, 1, 'C:/node/node.exe', 'node claude', 600.0, str(_lane(work)))
    assert archive(work, 'lane', census=lambda: (session,), today=_DAY).refused


def test_a_venv_never_travels(work: Path) -> None:
    _plant(_lane(work) / _LOG / 'env' / 'pyvenv.cfg', 'home = x')
    _plant(_lane(work) / _LOG / 'env' / 'Lib' / 'site.py', 'big')
    _plant(_lane(work) / 'tools' / 'pyvenv.cfg', 'home = x')  # an untracked, NOT ignored venv
    _plant(_lane(work) / 'tools' / 'Lib' / 'x.py', 'big')
    done = archive(work, 'lane', census=_idle, today=_DAY)
    assert done.safe, done.lines()
    assert not done.moved
    assert not (work / _LOG / 'env').exists()
    assert not (done.saved / 'untracked' / 'tools').exists()


def test_uncommitted_work_is_saved_as_a_patch_and_the_untracked_files(work: Path) -> None:
    (_lane(work) / 'base.txt').write_text('changed in the lane\n', encoding='utf-8')
    _plant(_lane(work) / 'notes' / 'n.md', 'untracked')
    _plant(_lane(work) / '.venv' / 'pyvenv.cfg', 'ignored, never saved')
    done = archive(work, 'lane', census=_idle, today=_DAY)
    assert done.safe, done.lines()
    assert done.saved == work / 'output' / 'worktree-archive' / '20261021' / 'lane'
    assert 'changed in the lane' in (done.saved / 'dirty.patch').read_text(encoding='utf-8')
    assert (done.saved / 'untracked' / 'notes' / 'n.md').read_text(encoding='utf-8') == 'untracked'
    assert not (done.saved / 'untracked' / '.venv').exists()
    assert 'lane' in (done.saved / 'HEAD.txt').read_text(encoding='utf-8')
    assert _lane(work).is_dir(), 'removal stays a separate, explicit step'


def test_the_outputs_are_declared_data(work: Path) -> None:
    (work / 'pyproject.toml').write_text("[tool.dev_lab.worktrees]\narchive-outputs = ['results']\n", encoding='utf-8')
    _plant(_lane(work) / 'results' / 'r.csv', '1')
    _plant(_lane(work) / _LOG / 'a.txt', 'not declared any more')
    done = archive(work, 'lane', census=_idle, today=_DAY)
    assert done.moved == (Path('results/r.csv'),)
    assert (_lane(work) / _LOG / 'a.txt').exists()


def test_another_volume_is_refused_because_a_move_there_is_a_copy(work: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _plant(_lane(work) / _LOG / 'a.txt', 'x')
    monkeypatch.setattr(worktree_archive, 'volume', lambda path: 'D:' if path == work else 'E:')
    done = archive(work, 'lane', census=_idle, today=_DAY)
    assert 'volume' in (done.refused or '')
    assert source.exists()


def test_the_main_checkout_and_an_unknown_name_are_refused(work: Path) -> None:
    assert archive(work, 'nope', census=_idle, today=_DAY).refused
    assert archive(work, work.name, census=_idle, today=_DAY).refused


def test_the_worktrees_door_archives_and_reports_safe_to_remove(work: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _plant(_lane(work) / _LOG / 'a.txt', 'x')
    assert main(['--root', str(work), '--archive', 'lane']) == 0
    out = capsys.readouterr().out
    assert 'safe to remove' in out
    assert (work / _LOG / 'a.txt').exists()
    assert _lane(work).is_dir()


def test_an_ignored_file_outside_the_outputs_is_not_work(work: Path) -> None:
    """Ruling 2026-10-25: what git does not track goes with the tree; only the outputs travel."""
    _plant(_lane(work) / 'results' / 'local.env', 'TOKEN_PATH=x')
    done = archive(work, 'lane', census=_idle, today=_DAY)
    assert done.safe, done.lines()


def test_a_detached_head_no_ref_contains_makes_the_tree_not_safe(work: Path) -> None:
    lane = _lane(work)
    _run(lane, 'switch', '-q', '--detach')
    assert archive(work, 'lane', census=_idle, today=_DAY).safe, 'detached at a commit the lane branch holds'
    _plant(lane / 'new.txt', 'only here')
    _run(lane, 'add', 'new.txt')
    _run(lane, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'detached work')
    done = archive(work, 'lane', census=_idle, today=_DAY)
    assert not done.safe
    assert len(done.unreachable) == 40


def test_the_dirty_patch_keeps_non_utf8_bytes(work: Path) -> None:
    lane = _lane(work)
    (lane / 'latin.txt').write_bytes(b'caf\xe9\n')
    _run(lane, 'add', 'latin.txt')
    _run(lane, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'latin-1 file')
    (lane / 'latin.txt').write_bytes(b'caf\xe9 au lait\n')
    done = archive(work, 'lane', census=_idle, today=_DAY)
    assert b'caf\xe9 au lait' in (done.saved / 'dirty.patch').read_bytes()
