"""WORKTREE OUTPUTS GO HOME on planted worktrees: a tree's run outputs are MOVED home, verified; nothing else moves.

Planted controls, one per way the move could be wrong while looking right: an identical file is skipped (the main
copy is untouched), a differing one lands beside it as ``<name>.<worktree>``, both names taken is refused, a new
one is RENAMED (same inode, never a copy), a venv never travels, a file outside the declared outputs stays,
another volume is refused, and the key and flag D31 retired are refused by name. REAL ``git worktree add``.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from dev_lab.dev import worktree_outputs
from dev_lab.dev.famtests.visibility import plant_checkout
from dev_lab.dev.worktree_outputs import home_outputs
from dev_lab.dev.worktrees import main

_GIT = shutil.which('git') or 'git'
_LOG = Path('output/logs/26/10/21/run')


def _run(cwd: Path, *args: str) -> None:
    subprocess.run([_GIT, *args], cwd=cwd, check=True, capture_output=True, timeout=60)


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
    assert home_outputs(work, _lane(work)) == ''
    assert home.stat().st_mtime_ns == stamp
    assert not (work / _LOG / 'a.txt.lane').exists()


def test_a_differing_file_lands_beside_the_main_one_named_for_its_worktree(work: Path) -> None:
    _plant(work / _LOG / 'a.txt', 'main')
    _plant(_lane(work) / _LOG / 'a.txt', 'lane')
    assert home_outputs(work, _lane(work)) == ''
    assert (work / _LOG / 'a.txt').read_text(encoding='utf-8') == 'main'
    assert (work / _LOG / 'a.txt.lane').read_text(encoding='utf-8') == 'lane'
    assert not (_lane(work) / _LOG / 'a.txt').exists()


def test_both_names_taken_by_different_bytes_is_refused(work: Path) -> None:
    _plant(work / _LOG / 'a.txt', 'main')
    _plant(work / _LOG / 'a.txt.lane', 'older lane')
    source = _plant(_lane(work) / _LOG / 'a.txt', 'lane')
    assert 'both names taken' in home_outputs(work, _lane(work))
    assert source.exists()


def test_a_new_file_is_renamed_never_copied(work: Path) -> None:
    source = _plant(_lane(work) / _LOG / 'deep' / 'b.bin', 'payload')
    inode = source.stat().st_ino
    assert home_outputs(work, _lane(work)) == ''
    assert not source.exists()
    assert (work / _LOG / 'deep' / 'b.bin').stat().st_ino == inode, 'a rename keeps the inode; a copy would not'


def test_a_venv_never_travels(work: Path) -> None:
    _plant(_lane(work) / _LOG / 'env' / 'pyvenv.cfg', 'home = x')
    _plant(_lane(work) / _LOG / 'env' / 'Lib' / 'site.py', 'big')
    assert home_outputs(work, _lane(work)) == ''
    assert not (work / _LOG / 'env').exists()


def test_the_outputs_are_declared_data(work: Path) -> None:
    (work / 'pyproject.toml').write_text("[tool.dev_lab.worktrees]\narchive-outputs = ['results']\n", encoding='utf-8')
    _plant(_lane(work) / 'results' / 'r.csv', '1')
    _plant(_lane(work) / _LOG / 'a.txt', 'not declared any more')
    assert home_outputs(work, _lane(work)) == ''
    assert (work / 'results' / 'r.csv').is_file()
    assert (_lane(work) / _LOG / 'a.txt').exists()


def test_the_key_d31_retired_is_refused_by_name(work: Path) -> None:
    """D31: a tree's work is merged or cleaned, never saved aside; the old destination key is refused, not ignored."""
    (work / 'pyproject.toml').write_text("[tool.dev_lab.worktrees]\narchive-to = 'output/x'\n", encoding='utf-8')
    source = _plant(_lane(work) / _LOG / 'a.txt', 'x')
    why = home_outputs(work, _lane(work))
    assert 'archive-to' in why
    assert 'retired (D31' in why
    assert source.exists()
    assert not (work / 'output' / 'x').exists()


def test_another_volume_is_refused_because_a_move_there_is_a_copy(work: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _plant(_lane(work) / _LOG / 'a.txt', 'x')
    main_root = work.resolve()
    monkeypatch.setattr(worktree_outputs, 'volume', lambda path: 'D:' if path == main_root else 'E:')
    assert 'volume' in home_outputs(work, _lane(work))
    assert source.exists()


def test_the_retired_archive_flag_is_refused_by_name(work: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """D31 retired ``--archive``: refused with its doors, never parsed as unknown, nothing written."""
    _plant(_lane(work) / 'notes.md', 'untracked work')
    assert main(['--root', str(work), '--archive', 'lane']) == 2
    err = capsys.readouterr().err
    assert 'is retired (D31' in err
    assert '--discard <branch> --approved' in err
    assert not (work / 'output').exists()
    assert (_lane(work) / 'notes.md').is_file()
