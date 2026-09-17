"""SHARED-CHECKOUT, as assertions: what exists only on this box exists for nobody.

THE RULE AND THE CONCLUSION THAT WAS WRONG. Two repos in this family declared this rule UNENFORCEABLE
for the same stated reason -- *"the push obligation is a fact about origin, not about any file in
this checkout"*. The premise is true and the conclusion is not: a guard does not have to read a FILE.
``git`` answers "what is here that origin does not have" exactly, cheaply and without a network call,
and :mod:`lab_commons.dev.checkout` is that question asked three ways.

WHAT IS HERE, AND WHAT IS ALREADY IN :mod:`~lab_commons.dev.checkout`. Every MEASUREMENT is that
module's -- :func:`~lab_commons.dev.checkout.classify`,
:func:`~lab_commons.dev.checkout.stale_branches`, :func:`~lab_commons.dev.checkout.origin_branches`,
:func:`~lab_commons.dev.checkout.debris`, :func:`~lab_commons.dev.checkout.authority_for` and
:func:`~lab_commons.dev.checkout.unmerged_changes` -- together with the two traps they carry: measure
against the REMOTE, and use ``git cherry`` for content rather than ancestry. Nothing is
re-implemented here. What was still forked when this module was written is the ASSERTION and,
measurably, THE CONTROL: two repos' copies agreed on all six arms and differed mostly in their
hand-rolled ``_run``/``_commit``/``_cloned`` git fixtures, one of which inlined them inside each test
function. A control written twice is a control that can be wrong in one place, and the whole point of
a planted control is that it is the part nobody checks.

THE TRUNK ARRIVES WITH NO DEFAULT, and it is the sharpest case of the family rule. Both consumers
spell it ``main``, which is exactly what makes a default tempting -- and a repository whose trunk is
named otherwise then resolves the guess to nothing, counts no commits against it, and REPORTS THE
CHECKOUT CLEAN. That is the ``LAB_CZ_BASE_REF`` failure in a second place. The declared branch sets
carry no default either: ``frozenset()`` is a MEASUREMENT meaning "we looked and found none", which
is a different act from never asking, and only a required argument can tell them apart.

EVERY REFUSAL IS A ``raise`` AND NOT AN ``assert``, the convention
:func:`lab_commons.dev.hook_adoption.assert_shippable` already sets, and it is not a style rule: a
bare ``assert`` is ERASED under ``python -O``, so a guard written with one is a guard a reader can
switch off without editing it, and it would go quiet in exactly the way this layer exists to refuse.
:class:`NotVisibleOnOrigin` derives from ``AssertionError`` so a consumer's red still reads as the
assertion it is.

A SHARED FILENAME IS NOT A SHARED IMPLEMENTATION, and this module deliberately serves two of the
three repos that hold the subject. The third writes it under a different name and measures 6%
identical code -- an independent implementation rather than a twin -- so adopting it there is a
rewrite to be decided on its own evidence, not a substitution this module can claim.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

from lab_commons.dev.checkout import (
    authority_for,
    classify,
    debris,
    origin_branches,
    stale_branches,
    unmerged_changes,
)

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    'NotVisibleOnOrigin',
    'Planted',
    'assert_local_only_branches',
    'assert_one_pushable_branch',
    'assert_origin_branch_set',
    'assert_readable',
    'assert_the_planted_debris_is_named',
    'assert_the_remote_is_the_authority',
    'commit',
    'plant_checkout',
]

#: Resolved once: a bare name is a PATH lookup at every call site, and a PATH that answers
#: differently between a terminal and a detached launcher describes an environment nobody meant.
_GIT = shutil.which('git') or 'git'

#: Every call is local -- no network, no hook, no editor -- so a minute without an answer is hung.
_GIT_TIMEOUT_S = 60


class NotVisibleOnOrigin(AssertionError):
    """A checkout holds something origin does not, or could not be read at all."""


def _refuse(message: str) -> None:
    """Raise the one refusal this module makes, so every arm fails in one recognisable way."""
    raise NotVisibleOnOrigin(message)


@dataclass(frozen=True)
class Planted:
    """A real bare origin and a real clone of it, with one commit pushed to the trunk."""

    bare: Path
    work: Path


def _run(cwd: Path, *args: str) -> None:
    subprocess.run([_GIT, *args], cwd=cwd, check=True, capture_output=True, timeout=_GIT_TIMEOUT_S)


def commit(repo: Path, name: str) -> None:
    """One real commit adding one real file. Shared because a control built twice can differ twice."""
    (repo / name).write_text(name, encoding='utf-8')
    _run(repo, 'add', name)
    _run(repo, 'commit', '-q', '-m', f'add {name}')


def plant_checkout(tmp_path: Path, *, trunk: str) -> Planted:
    """A bare origin on *trunk*, a clone of it, and one commit pushed. *trunk* has NO DEFAULT.

    A fixture that hard-coded ``main`` could not build the repository that proves why the assertions
    below take a trunk, so the fixture takes one too.
    """
    bare = tmp_path / 'origin.git'
    _run(tmp_path, 'init', '-q', '--bare', '-b', trunk, str(bare))
    work = tmp_path / 'work'
    _run(tmp_path, 'clone', '-q', str(bare), str(work))
    _run(work, 'config', 'user.email', 'a@b.invalid')
    _run(work, 'config', 'user.name', 'Test')
    commit(work, 'base.txt')
    _run(work, 'push', '-q', 'origin', trunk)
    return Planted(bare=bare, work=work)


def assert_readable(*, root: Path, trunk: str) -> None:
    """THE FLOOR. An unreadable repository must never render as a clean one.

    Also the arm a guessed trunk dies on: if *trunk* names no branch this checkout is on, the trunk
    row is empty and every count downstream would be a zero about nothing.

    Raises:
        NotVisibleOnOrigin: the repository could not be read, holds no worktree, is not on *trunk*,
            or its debris census did not answer.

    """
    rows = classify(root, trunk=trunk)
    if rows is None:
        _refuse(f'{root} could not be read as a git repository; this guard proved nothing')
        return
    if not rows:
        _refuse(f'{root} reports no worktrees at all: an unread answer, not a tidy one')
    found = [row.branch for row in rows if row.kind == 'trunk']
    if found != [trunk]:
        _refuse(
            f'the trunk row is {found}, not [{trunk!r}]. Either this checkout is not on its trunk, or '
            f'the trunk this guard was given is stale -- and a trunk that resolves to nothing reports '
            f'every branch as clean.'
        )
    if not debris(root).readable:
        _refuse(f'the debris census of {root} could not be read; a silent census is not a clean one')


def assert_one_pushable_branch(*, root: Path, trunk: str) -> None:
    """A second branch origin already carries is a second thing somebody must push and may forget.

    Raises:
        NotVisibleOnOrigin: the repository could not be read, or a second pushable branch exists.

    """
    rows = classify(root, trunk=trunk)
    if rows is None:
        _refuse(f'{root} could not be read as a git repository')
        return
    pushable = sorted(row.branch for row in rows if row.kind == 'primary')
    if pushable:
        _refuse(
            f'{len(pushable)} branch(es) besides the trunk are on origin and not integrated: '
            f'{pushable}. One session pushes ONE branch -- reconcile them into {trunk} and delete '
            f'them, or finish them and let one become the trunk.'
        )


def assert_local_only_branches(*, root: Path, declared: frozenset[str]) -> None:
    """Branches this box knows and origin does not, pinned BY NAME and two-sided.

    *declared* has NO DEFAULT: ``frozenset()`` is a measurement, and it is not the same statement as
    an argument nobody passed.

    Raises:
        NotVisibleOnOrigin: the census could not be read, or the live set is not the declared one in
            EITHER direction -- a pin that outlived its branch reads as a live decision.

    """
    local = stale_branches(root)
    if local is None:
        _refuse(f'the branch census of {root} could not be read; an unread repo is not a clean one')
        return
    if set(local) != declared:
        _refuse(
            f'branches this box knows and origin does not: {sorted(set(local) - declared)}; pinned '
            f'names that are gone: {sorted(declared - set(local))}. Push it or delete it, and edit '
            f'the pin in the SAME change -- a named set is what says WHICH one moved, and a count is not.'
        )


def assert_origin_branch_set(*, root: Path, declared: frozenset[str]) -> None:
    """The published branches besides the trunk, pinned BY NAME. Both sides, for the same reason.

    Raises:
        NotVisibleOnOrigin: origin could not be read, or the published set is not the declared one.

    """
    names = origin_branches(root)
    if names is None:
        _refuse(f'origin could not be read from {root}; an unread remote is not an empty one')
        return
    if set(names) != declared:
        _refuse(f'new on origin: {sorted(set(names) - declared)}; pinned and gone: {sorted(declared - set(names))}')


def assert_the_remote_is_the_authority(tmp_path: Path, *, trunk: str) -> None:
    """PLANTED CONTROL for the trap that makes this audit lie: a STALE LOCAL TRUNK.

    The branch does not change; the local pointer does. Against the stale ref an already-landed
    change reads as unmerged, which is how an audit built to stop debt starts manufacturing it --
    measured in a sibling repo as a fully-integrated lane reporting 24 unmerged commits.

    Raises:
        NotVisibleOnOrigin: the remote is not the authority, or the fixture stopped opening a gap,
            which would leave every consumer's control arm passing while measuring nothing.

    """
    planted = plant_checkout(tmp_path, trunk=trunk)
    other = tmp_path / 'other'
    _run(tmp_path, 'clone', '-q', str(planted.bare), str(other))
    _run(other, 'config', 'user.email', 'a@b.invalid')
    _run(other, 'config', 'user.name', 'Test')
    commit(other, 'landed.txt')
    _run(other, 'push', '-q', 'origin', trunk)
    _run(planted.work, 'fetch', '-q', 'origin')

    remote = f'origin/{trunk}'
    if authority_for(planted.work, trunk) != remote:
        _refuse('the remote is the authority whenever it carries the trunk, and it answered otherwise')
    if unmerged_changes(planted.work, trunk, remote) != 1:
        _refuse(
            'against the STALE local ref the landed change must look new; it did not, so the fixture '
            'stopped moving origin ahead and this control measures nothing'
        )
    if unmerged_changes(planted.work, remote, remote) != 0:
        _refuse('against the remote the landed change must read as landed')


def assert_the_planted_debris_is_named(tmp_path: Path, *, trunk: str) -> None:
    """PLANTED CONTROL for both violations: a second pushable branch, and a local-only one.

    Driven through the REAL functions on a REAL worktree and a REAL dangling branch, and it reads
    the CLEAN state first -- a control that never saw the green side cannot tell a working guard
    from one that refuses everything.

    Raises:
        NotVisibleOnOrigin: the clean state was not clean, or a planted violation was not named.

    """
    planted = plant_checkout(tmp_path, trunk=trunk)
    if [row.kind for row in classify(planted.work, trunk=trunk) or ()] != ['trunk']:
        _refuse('the freshly planted checkout was not clean, so nothing below is a controlled change')
    if stale_branches(planted.work) != ():
        _refuse('the freshly planted checkout already held a local-only branch')

    lane = tmp_path / 'lane'
    _run(planted.work, 'worktree', 'add', '-q', '-b', 'feat/second', str(lane))
    commit(lane, 'x.txt')
    _run(lane, 'push', '-q', 'origin', 'feat/second')
    _run(planted.work, 'fetch', '-q', 'origin')

    rows = classify(planted.work, trunk=trunk) or ()
    if sorted(row.branch for row in rows if row.kind == 'primary') != ['feat/second']:
        _refuse('a planted second pushable branch was not classified as one')
    if origin_branches(planted.work) != ('feat/second',):
        _refuse('a planted published branch was not seen on origin')

    _run(planted.work, 'branch', 'abandoned')
    if stale_branches(planted.work) != ('abandoned',):
        _refuse('a branch with no origin, no upstream and no worktree was not named as local-only')
    if 'feat/second' in (stale_branches(planted.work) or ()):
        _refuse('a checked-out, pushed branch was called local-only; a live branch is not debris')
