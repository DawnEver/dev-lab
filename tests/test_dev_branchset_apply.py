"""``branchset --apply``: the LOCAL door (ruling 2026-10-04), planted on both sides; origin is listed only."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from dev_lab.dev.branchset import BranchSet, apply_local
from dev_lab.dev.famtests.visibility import commit, plant_checkout

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
    (tmp_path / 'busy-tree' / 'base.txt').write_text('a tracked change', encoding='utf-8')

    lines = apply_local(work, _DECLARED) or ()

    assert any(line.startswith('deleted  local   landed') for line in lines)
    assert any(line.startswith('kept     local   open') for line in lines)
    assert any(line.startswith('kept     local   busy') for line in lines)
    assert any(line.startswith('listed   origin  landed') and 'human' in line for line in lines)
    heads = set(_run(work, 'branch', '--format=%(refname:short)').split())
    assert heads == {'main', 'open', 'feat/session', 'busy'}
    assert 'refs/heads/landed' in _run(work, 'ls-remote', '--heads', 'origin'), 'the door never deletes on origin'


def test_an_archive_tag_is_a_branch_left_behind_merged_ones_go_open_ones_are_merged(tmp_path: Path) -> None:
    """MERGE-OR-DELETE (user ruling 2026-10-11): a parked archive tag is a branch left behind.

    Parking a branch as an `archive/*` tag hides it from
    everyone; a merged one is deleted, an unmerged one is listed to MERGE, never kept as a tag.
    """
    work = plant_checkout(tmp_path, trunk='main').work
    _run(work, 'tag', 'archive/landed')
    _run(work, 'switch', '-q', '-c', 'open')
    commit(work, 'open.txt')
    _run(work, 'tag', 'archive/open')
    _run(work, 'switch', '-q', 'main')
    _run(work, 'branch', '-q', '-D', 'open')
    _run(work, 'tag', 'v1.0')

    lines = apply_local(work, _DECLARED) or ()

    assert any(line.startswith('deleted  tag     archive/landed') for line in lines)
    assert any(line.startswith('kept     tag     archive/open') and 'merge' in line for line in lines)
    tags = set(_run(work, 'tag', '--list').split())
    assert tags == {'archive/open', 'v1.0'}, 'a release tag is not a parked branch and is never touched'
