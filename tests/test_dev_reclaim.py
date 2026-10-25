"""A worktree is a LEASE on a branch for one task: reclaimed once its content is landed and it holds nothing else.

Planted on a real repository, every criterion on both sides: a landed tree, a squash-landed one whose origin
ref is gone, and a landed one holding scratch, untracked and ignored files (``.venv``, ``output/logs``) go (their
branch with them through ``branchset --apply``), the outputs moved HOME first; a tree with a modified TRACKED
file, an unlanded one, a pushed-but-unmerged one, a locked one, an occupied one and the main checkout stay, each
with its reason. An orphan directory goes the same way, outputs home first. A planted archive failure keeps
every tree whole (user ruling 2026-10-25: what git does not track is not the work).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from dev_lab.dev.branchset import BranchSet, apply_local
from dev_lab.dev.famtests.visibility import commit, plant_checkout
from dev_lab.dev.reclaim import reclaim, reclaimable

_GIT = shutil.which('git') or 'git'
_HOLDERS = ('origin/main',)
_LOG = Path('output/logs/26/10/25/run')
_GONE = {'landed', 'squashed', 'untracked', 'cache', 'notes'}
_KEPT = ('dirty', 'locked', 'occupied', 'open', 'pushed')


def _run(cwd: Path, *args: str) -> str:
    return subprocess.run(
        [_GIT, *args], cwd=cwd, check=True, capture_output=True, text=True, encoding='utf-8', timeout=60
    ).stdout


def _free(_: Path) -> bool:
    return False


def _planted(tmp_path: Path) -> Path:
    planted = plant_checkout(tmp_path, trunk='main')
    work = planted.work
    (work / '.gitignore').write_text('.claude/\n.venv/\noutput/\n', encoding='utf-8')
    _run(work, 'add', '.gitignore')
    _run(work, 'commit', '-q', '-m', 'ignore')
    _run(work, 'push', '-q', 'origin', 'main')
    home = work / '.claude' / 'worktrees'
    # landed: its commit reached origin/main
    _run(work, 'worktree', 'add', '-q', '-b', 'landed', str(home / 'landed'), 'origin/main')
    commit(home / 'landed', 'landed.txt')
    _run(home / 'landed', 'push', '-q', 'origin', 'landed:main')
    (home / 'landed' / '.venv').mkdir()
    (home / 'landed' / '.venv' / 'pyvenv.cfg').write_text('', encoding='utf-8')
    # squashed: two commits squash-merged on origin, then its origin ref deleted
    _run(work, 'worktree', 'add', '-q', '-b', 'squashed', str(home / 'squashed'), 'origin/main')
    commit(home / 'squashed', 's1.txt')
    commit(home / 'squashed', 's2.txt')
    _run(home / 'squashed', 'push', '-q', '-u', 'origin', 'squashed')
    _run(work, 'fetch', '-q', 'origin')
    _run(work, 'merge', '-q', '--ff-only', 'origin/main')
    _run(work, 'merge', '-q', '--squash', 'origin/squashed')
    _run(work, 'commit', '-q', '-m', 'squash')
    _run(work, 'push', '-q', 'origin', 'main')
    _run(work, 'push', '-q', 'origin', '--delete', 'squashed')
    _run(work, 'fetch', '-q', '--prune', 'origin')
    for name in ('dirty', 'locked', 'occupied', 'untracked'):
        _run(work, 'worktree', 'add', '-q', '--detach', str(home / name), 'origin/main')
    (home / 'dirty' / '.gitignore').write_text('changed\n', encoding='utf-8')
    _plant(home / 'untracked' / 'scratch' / 'probe.py', 'one-off')
    _plant(home / 'untracked' / 'loose.txt', 'untracked')
    _plant(home / 'untracked' / '.venv' / 'pyvenv.cfg', '')
    _plant(home / 'untracked' / _LOG / 'r.txt', 'result')
    _run(work, 'worktree', 'lock', str(home / 'locked'))
    _run(work, 'worktree', 'add', '-q', '-b', 'open', str(home / 'open'), 'origin/main')
    commit(home / 'open', 'open.txt')
    _run(work, 'worktree', 'add', '-q', '-b', 'pushed', str(home / 'pushed'), 'origin/main')
    commit(home / 'pushed', 'pushed.txt')
    _run(home / 'pushed', 'push', '-q', 'origin', 'pushed')
    (home / 'cache' / '__pycache__').mkdir(parents=True)
    (home / 'cache' / '__pycache__' / 'm.pyc').write_text('', encoding='utf-8')
    _plant(home / 'notes' / 'note.txt', 'agent output')
    _plant(home / 'notes' / _LOG / 'n.txt', 'orphan result')
    return work


def _plant(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def _occupied(path: Path) -> bool:
    return path.name == 'occupied'


def test_every_tree_is_judged_with_its_reason(tmp_path: Path) -> None:
    work = _planted(tmp_path)
    leases = {lease.path.name: lease for lease in reclaimable(work, _HOLDERS, occupied=_occupied) or ()}
    assert {n for n, lease in leases.items() if lease.reclaimable} == _GONE
    assert 'tracked changes' in leases['dirty'].reason
    assert 'locked' in leases['locked'].reason
    assert 'live' in leases['occupied'].reason
    assert 'not landed' in leases['open'].reason
    assert 'not landed' in leases['pushed'].reason, 'pushed is not landed'
    assert work.resolve() not in {lease.path for lease in leases.values()}, 'the main checkout is never a lease'


def test_reclaim_removes_only_the_reclaimable_and_lists_the_rest(tmp_path: Path) -> None:
    work = _planted(tmp_path)
    home = work / '.claude' / 'worktrees'
    lines = reclaim(work, _HOLDERS, occupied=_occupied) or ()
    for gone in _GONE:
        assert not (home / gone).exists(), gone
        assert any(line.startswith('removed') and gone in line for line in lines)
    for kept in _KEPT:
        assert (home / kept).is_dir(), kept
        assert any(line.startswith('kept') and kept in line for line in lines)
    assert (work / _LOG / 'r.txt').read_text(encoding='utf-8') == 'result', 'a worktree output went home first'
    assert (work / _LOG / 'n.txt').read_text(encoding='utf-8') == 'orphan result', 'an orphan output went home'
    assert (home / 'dirty' / '.gitignore').read_text(encoding='utf-8') == 'changed\n'


def test_an_archive_that_cannot_be_verified_keeps_the_tree_and_deletes_nothing(tmp_path: Path) -> None:
    """PLANTED FAILURE: ``output`` in the main checkout is a FILE, so no output can land home."""
    work = _planted(tmp_path)
    home = work / '.claude' / 'worktrees'
    (work / 'output').write_text('in the way', encoding='utf-8')
    lines = reclaim(work, _HOLDERS, occupied=_occupied) or ()
    for name, held in (('untracked', _LOG / 'r.txt'), ('notes', _LOG / 'n.txt')):
        assert (home / name / held).is_file(), f'{name} lost its output'
        assert any(line.startswith('kept') and name in line and 'not archived' in line for line in lines), lines
    assert (home / 'untracked' / 'scratch' / 'probe.py').is_file(), 'nothing of a kept tree is deleted'
    assert not (home / 'landed').exists(), 'a tree with no outputs still goes: the failure is per tree'


def test_branchset_apply_reclaims_first_so_the_landed_branch_is_deleted(tmp_path: Path) -> None:
    work = _planted(tmp_path)
    lines = apply_local(work, BranchSet(trunk='main', sessions=frozenset()), occupied=_occupied) or ()
    assert any(line.startswith('removed') and 'landed' in line for line in lines)
    assert any(line.startswith('deleted  local   landed') for line in lines)
    heads = set(_run(work, 'branch', '--format=%(refname:short)').split())
    assert 'landed' not in heads
    assert {'open', 'pushed'} <= heads


def test_an_unreadable_root_is_none(tmp_path: Path) -> None:
    assert reclaimable(tmp_path, _HOLDERS, occupied=_free) is None
    assert reclaim(tmp_path, _HOLDERS, occupied=_free) is None
