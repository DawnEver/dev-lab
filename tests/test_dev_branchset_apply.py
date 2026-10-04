"""``branchset --apply``: the LOCAL door (ruling 2026-10-04), planted on both sides; origin is listed only."""

from __future__ import annotations

import shutil
import subprocess
import warnings
from pathlib import Path

import pytest

from lab_commons.dev.branchset import BranchSet, apply_local
from lab_commons.dev.famtests.branchset import (
    BranchSetViolation,
    assert_local_branches_declared,
    assert_origin_branches_declared,
    merged_owed,
)
from lab_commons.dev.famtests.visibility import commit, plant_checkout

_GIT = shutil.which('git') or 'git'
_DECLARED = BranchSet(trunk='main', sessions=frozenset({'feat/session'}))


def _run(cwd: Path, *args: str) -> str:
    return subprocess.run(
        [_GIT, *args], cwd=cwd, check=True, capture_output=True, text=True, encoding='utf-8', timeout=60
    ).stdout


def test_apply_deletes_merged_local_branches_only_and_never_touches_origin(tmp_path: Path) -> None:
    work = plant_checkout(tmp_path, trunk='main').work
    _run(work, 'branch', 'landed')
    _run(work, 'push', '-q', 'origin', 'landed')
    _run(work, 'switch', '-q', '-c', 'open')
    commit(work, 'open.txt')
    _run(work, 'switch', '-q', 'main')
    _run(work, 'branch', 'feat/session')
    _run(work, 'branch', 'busy')
    _run(work, 'worktree', 'add', str(tmp_path / 'busy-tree'), 'busy')

    lines = apply_local(work, _DECLARED) or ()

    assert any(line.startswith('deleted  local   landed') for line in lines)
    assert any(line.startswith('kept     local   open') for line in lines)
    assert any(line.startswith('kept     local   busy') for line in lines)
    assert any(line.startswith('listed   origin  landed') and 'human' in line for line in lines)
    heads = set(_run(work, 'branch', '--format=%(refname:short)').split())
    assert heads == {'main', 'open', 'feat/session', 'busy'}
    assert 'refs/heads/landed' in _run(work, 'ls-remote', '--heads', 'origin'), 'the door never deletes on origin'


def test_a_merged_undeclared_branch_is_owed_to_a_human_not_a_red(tmp_path: Path) -> None:
    """Ruling 2026-10-04: remote deletion is never automatic, so a MERGED stray must not fail verify."""
    work = plant_checkout(tmp_path, trunk='main').work
    _run(work, 'branch', 'landed')
    _run(work, 'push', '-q', 'origin', 'landed')
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter('always')
        assert assert_origin_branches_declared(root=work, branchset=_DECLARED) == ('landed',)
        assert assert_local_branches_declared(root=work, branchset=_DECLARED) == ()
    assert any('git push origin --delete landed' in str(w.message) for w in seen)
    assert 'origin landed: merged, deletion owed to a human -- git push origin --delete landed' in merged_owed(
        root=work, branchset=_DECLARED
    )

    _run(work, 'switch', '-q', '-c', 'stray')
    commit(work, 'stray.txt')
    _run(work, 'push', '-q', 'origin', 'stray')
    _run(work, 'switch', '-q', 'main')
    with pytest.raises(BranchSetViolation, match='stray'):
        assert_origin_branches_declared(root=work, branchset=_DECLARED)
    with pytest.raises(BranchSetViolation, match='stray'):
        assert_local_branches_declared(root=work, branchset=_DECLARED)
