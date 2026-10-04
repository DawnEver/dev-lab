"""ONE-BRANCH-PER-SESSION, as the assertions every consumer runs over its own checkout.

The measurement is :mod:`lab_commons.dev.branchset`; this body only refuses. A consumer calls::

    from lab_commons.dev.branchset import declared_branchset
    from lab_commons.dev.famtests import branchset

    def test_origin_carries_only_the_declared_branches() -> None:
        branchset.assert_origin_branches_declared(root=ROOT, branchset=declared_branchset(ROOT))

    def test_this_box_carries_only_the_declared_branches() -> None:
        branchset.assert_local_branches_declared(root=ROOT, branchset=declared_branchset(ROOT))

    def test_the_branchset_guard_fires(tmp_path) -> None:
        branchset.assert_the_planted_branchset_is_policed(tmp_path, trunk='main')

The local arm REPORTS unpushed work and returns it rather than failing: a branch holding commits
origin lacks is the only copy of them, and a red would invite deleting it. Every refusal is a
``raise``, never an ``assert``, so ``python -O`` cannot switch the guard off.
"""

from __future__ import annotations

import shutil
import subprocess
import warnings
from typing import TYPE_CHECKING

from lab_commons.dev.branchset import BranchSet, Census, census, merge_candidates
from lab_commons.dev.checkout import git_out
from lab_commons.dev.famtests.visibility import commit, plant_checkout

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    'BranchSetViolation',
    'assert_local_branches_declared',
    'assert_origin_branches_declared',
    'assert_the_planted_branchset_is_policed',
    'merged_owed',
]

_GIT = shutil.which('git') or 'git'
_REMEDY = 'merge it into the session branch, then delete it; `python -m lab_commons.dev.branchset` lists which'


class BranchSetViolation(AssertionError):
    """A checkout carries a branch its declared set does not name, or could not be read."""


def _read(root: Path, branchset: BranchSet) -> Census:
    found = census(root, branchset)
    if found is None:
        msg = f'the branches of {root} could not be read; an unread repo is not a clean one'
        raise BranchSetViolation(msg)
    return found


def _merged(root: Path, branchset: BranchSet, where: str) -> frozenset[str]:
    """Undeclared branches on *where* whose tip is held by HEAD, origin/<trunk> or a session branch.

    A MERGED branch is not a red (ruling 2026-10-04): remote deletion is never automatic, so a red
    here forced an agent to delete on origin BEFORE its push could verify. It is reported instead.
    """
    rows = merge_candidates(root, branchset) or ()
    prefix = 'refs/heads/' if where == 'local' else 'refs/remotes/origin/'
    return frozenset(
        r.name
        for r in rows
        if r.where == where
        and (r.deletable or git_out(root, 'merge-base', '--is-ancestor', f'{prefix}{r.name}', 'HEAD') is not None)
    )


def merged_owed(*, root: Path, branchset: BranchSet) -> tuple[str, ...]:
    """Each merged undeclared branch with the exact command that deletes it -- owed, never run here."""
    owed = [
        f'origin {n}: merged, deletion owed to a human -- git push origin --delete {n}'
        for n in sorted(_merged(root, branchset, 'origin'))
    ]
    owed += [
        f'local {n}: merged -- python -m lab_commons.dev.branchset --apply'
        for n in sorted(_merged(root, branchset, 'local'))
    ]
    return tuple(owed)


def assert_origin_branches_declared(*, root: Path, branchset: BranchSet) -> tuple[str, ...]:
    """Origin carries the declared set, plus MERGED branches whose deletion is owed (returned, warned).

    Raises:
        BranchSetViolation: an undeclared origin branch NOT contained in HEAD/trunk/a session, or unread refs.

    """
    merged = _merged(root, branchset, 'origin')
    owed = tuple(n for n in _read(root, branchset).undeclared_origin if n in merged)
    if owed:
        warnings.warn(
            'merged, deletion owed to a human: ' + '; '.join(f'git push origin --delete {n}' for n in owed),
            stacklevel=2,
        )
    extra = tuple(n for n in _read(root, branchset).undeclared_origin if n not in merged)
    if extra:
        msg = f'origin carries undeclared branches {list(extra)} (ONE-BRANCH-PER-SESSION): {_REMEDY}'
        raise BranchSetViolation(msg)
    return owed


def assert_local_branches_declared(*, root: Path, branchset: BranchSet) -> tuple[str, ...]:
    """Refuse an undeclared local branch origin already holds; return those holding unpushed work.

    Raises:
        BranchSetViolation: an undeclared local branch with nothing unpushed, or unreadable refs.

    """
    found = _read(root, branchset)
    if found.unpushed:
        warnings.warn(f'undeclared local branches hold UNPUSHED work: {list(found.unpushed)}', stacklevel=2)
    merged = _merged(root, branchset, 'local')
    if owed := [n for n in found.local_debt if n in merged]:
        warnings.warn(f'merged local branches {owed}: python -m lab_commons.dev.branchset --apply', stacklevel=2)
    if debt := [n for n in found.local_debt if n not in merged]:
        msg = f'this box carries undeclared branches {debt} (ONE-BRANCH-PER-SESSION): {_REMEDY}'
        raise BranchSetViolation(msg)
    return found.unpushed


def _run(cwd: Path, *args: str) -> None:
    subprocess.run([_GIT, *args], cwd=cwd, check=True, capture_output=True, timeout=60)


def assert_the_planted_branchset_is_policed(tmp_path: Path, *, trunk: str) -> None:
    """PLANTED CONTROL on a real clone of a real bare origin: clean first, then each violation.

    Raises:
        BranchSetViolation: the clean checkout was not clean, or a planted violation was not named.

    """
    work = plant_checkout(tmp_path, trunk=trunk).work
    declared = BranchSet(trunk, frozenset({'session'}))
    assert_origin_branches_declared(root=work, branchset=declared)
    if assert_local_branches_declared(root=work, branchset=declared):
        msg = 'the freshly planted checkout already reported unpushed work'
        raise BranchSetViolation(msg)
    _run(work, 'branch', 'landed')
    _run(work, 'push', '-q', 'origin', 'landed')
    with warnings.catch_warnings(record=True):
        warnings.simplefilter('always')
        if assert_origin_branches_declared(root=work, branchset=declared) != ('landed',):
            msg = 'a MERGED origin branch was not reported as a deletion owed to a human'
            raise BranchSetViolation(msg)
        assert_local_branches_declared(root=work, branchset=declared)
    _run(work, 'switch', '-q', '-c', 'stray')
    commit(work, 'stray.txt')
    _run(work, 'push', '-q', 'origin', 'stray')
    _run(work, 'switch', '-q', trunk)
    for arm in (assert_origin_branches_declared, assert_local_branches_declared):
        try:
            arm(root=work, branchset=declared)
        except BranchSetViolation:
            continue
        msg = f'{arm.__name__} passed over a planted undeclared branch'
        raise BranchSetViolation(msg)
    _run(work, 'switch', '-q', '-c', 'wip')
    commit(work, 'wip.txt')
    if 'wip' not in _read(work, declared).unpushed:
        msg = 'planted unpushed work was not reported as unpushed'
        raise BranchSetViolation(msg)
    if [r.name for r in merge_candidates(work, declared) or () if r.deletable] != ['landed', 'landed']:
        msg = 'a branch at the trunk tip was not offered for deletion, locally and on origin'
        raise BranchSetViolation(msg)
