"""``branchset --discard``: the door for ONE unlanded lane the user approved (user ruling 2026-11-13).

Every refusal is planted beside its control: the same lane, with the condition lifted, is discarded.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from dev_lab.dev.branchset import BranchSet, discard
from dev_lab.dev.famtests.visibility import commit, plant_checkout

_GIT = shutil.which('git') or 'git'
_DECLARED = BranchSet(trunk='main', sessions=frozenset({'integrate/main'}))
_WORDS = 'yes, drop the lane experiment'


def _run(cwd: Path, *args: str) -> str:
    return subprocess.run(
        [_GIT, *args], cwd=cwd, check=True, capture_output=True, text=True, encoding='utf-8', timeout=60
    ).stdout


def _heads(work: Path) -> set[str]:
    return set(_run(work, 'branch', '--format=%(refname:short)').split())


@pytest.fixture
def lane(tmp_path: Path) -> Path:
    """A main checkout with ``lane/x``: an unlanded commit, checked out in its own worktree."""
    work = plant_checkout(tmp_path, trunk='main').work
    _run(work, 'branch', 'integrate/main')
    _run(work, 'worktree', 'add', '-q', '-b', 'lane/x', str(tmp_path / 'lane-tree'))
    commit(tmp_path / 'lane-tree', 'unlanded.txt')
    return work


def test_an_approved_unlanded_lane_loses_its_worktree_and_local_branch(lane: Path, tmp_path: Path) -> None:
    code, line = discard(lane, _DECLARED, 'lane/x', _WORDS, quiet_s=0)
    assert code == 0, line
    assert 'discarded' in line
    assert _WORDS in line
    assert not (tmp_path / 'lane-tree').exists()
    assert 'lane/x' not in _heads(lane)
    assert 'lane-tree' not in _run(lane, 'worktree', 'list')


def test_a_lane_with_no_worktree_loses_its_branch_alone(lane: Path, tmp_path: Path) -> None:
    _run(lane, 'branch', 'lane/y', 'lane/x')
    assert discard(lane, _DECLARED, 'lane/y', _WORDS, quiet_s=0)[0] == 0
    assert 'lane/y' not in _heads(lane)
    assert (tmp_path / 'lane-tree').exists(), "another lane's tree is untouched"


@pytest.mark.parametrize(
    ('branch', 'words', 'said'),
    [
        ('lane/x', '', '--approved'),
        ('lane/x', '   ', '--approved'),
        ('main', _WORDS, 'declared'),
        ('integrate/main', _WORDS, 'declared'),
        ('lane/nowhere', _WORDS, 'no local branch'),
    ],
)
def test_a_missing_approval_a_declared_or_a_non_local_branch_is_refused(
    lane: Path, branch: str, words: str, said: str
) -> None:
    before = _heads(lane)
    code, line = discard(lane, _DECLARED, branch, words, quiet_s=0)
    assert (code, said in line) == (1, True), line
    assert _heads(lane) == before


def test_the_main_checkouts_branch_is_refused(lane: Path) -> None:
    _run(lane, 'switch', '-q', '-c', 'lane/main-held')
    code, line = discard(lane, _DECLARED, 'lane/main-held', _WORDS, quiet_s=0)
    assert (code, 'the main checkout holds it' in line) == (1, True), line
    assert 'lane/main-held' in _heads(lane)


def test_a_live_session_is_refused_and_the_same_tree_once_quiet_is_discarded(lane: Path, tmp_path: Path) -> None:
    code, line = discard(lane, _DECLARED, 'lane/x', _WORDS)  # its index just changed
    assert (code, 'live session' in line) == (1, True), line
    assert (tmp_path / 'lane-tree').exists()
    assert 'lane/x' in _heads(lane)
    assert discard(lane, _DECLARED, 'lane/x', _WORDS, quiet_s=0)[0] == 0, 'PLANTED CONTROL'


def test_a_remote_tracking_name_is_not_a_local_branch(lane: Path) -> None:
    code, line = discard(lane, _DECLARED, 'origin/main', _WORDS, quiet_s=0)
    assert (code, 'no local branch' in line) == (1, True), line
