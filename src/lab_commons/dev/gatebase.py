"""Which commit a gate diffs FROM -- one question, several candidates, and the NARROWEST honest one.

Migrated 2026-09-17 from motronics-studio's ``scripts/gate/base.py``, and it is a SPLIT rather than a
move: the arithmetic and the admission rule are universal, the CANDIDATE REFS are not. That file
named ``origin/integrate/main`` and ``origin/main`` as literals, which is one repo's branching model
written into a mechanism. Both arrive here as arguments with NO DEFAULT, for the reason
:mod:`lab_commons.dev.githooks` already gives for ``LAB_CZ_BASE_REF``: a default would judge a repo
whose trunk is named otherwise against a ref that does not exist, and report the lane clean.

THE ADMISSION RULE. A candidate is admitted only if it names a real commit that HEAD DESCENDS FROM.
An all-zero sha (what a new branch pushes), an unresolvable name, and a force-pushed remote sha that
HEAD no longer descends from all answer no. This is what keeps a narrower base HONEST: a base HEAD
does not descend from would let the gate SKIP commits rather than only decline to re-judge ones the
remote already holds.

**THE NARROWEST ADMITTED CANDIDATE WINS, NOT THE FIRST**, and that correction was measured rather
than reasoned. Returning the first admitted candidate let the ORDER decide the answer even where a
later one was strictly better. MEASURED 2026-09-06 on a lane rebased onto an integration tip:
``@{push}`` still named the lane's old pushed sha, which IS an ancestor of the new HEAD because the
integrator had merged it -- so it was admitted, it won, and the gate was handed **159 commits / 473
files**, of which 147 were upstream history the rebase had replayed and the integrator had already
gated. The integration branch gives **12 commits / 29 files** for the same HEAD. That gap is the
"over the wall" problem arriving through a STALE ref rather than a wrong one.

WHY NARROWING IS SOUND, and it is a property of the CANDIDATES rather than of the arithmetic: every
one of them is a ref THE REMOTE HOLDS. A commit excluded by taking a narrower base is therefore one
the remote already has and has already gated. The dangerous direction stays closed, because a base
HEAD does not descend from is never admitted at all.

PRIORITY DECIDES TIES. ``min`` is stable, so the earliest candidate in the caller's order wins
whenever nothing is strictly narrower -- which is how a hook-supplied ref keeps its standing as the
ground truth for the push actually happening.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

__all__ = ['ZERO_SHA', 'admitted', 'gate_base']

#: Resolved once: a bare name is a PATH lookup at every call site, and a PATH that answers
#: differently between a terminal and a detached launcher describes an environment nobody meant.
_GIT = shutil.which('git') or 'git'

#: Every call here reads LOCAL refs -- no network, no hook, no editor -- so a child that has not
#: answered in half a minute is hung rather than slow.
_GIT_TIMEOUT_S = 30

#: What a push of a NEW branch names as its "from" ref. It is a valid-looking string that resolves
#: to nothing, so it is refused by shape before git is asked.
ZERO_SHA = '0' * 40


def _git_out(root: Path, *args: str) -> str:
    """One git read, or the empty string when git could not answer."""
    try:
        probe = subprocess.run(
            [_GIT, *args], cwd=root, capture_output=True, text=True, check=False, timeout=_GIT_TIMEOUT_S
        )
    except (OSError, subprocess.TimeoutExpired):
        return ''
    return probe.stdout.strip() if probe.returncode == 0 else ''


def _is_ancestor(root: Path, ref: str) -> bool:
    """Whether *ref* names a real commit that HEAD descends from."""
    if not ref or set(ref) == {'0'}:
        return False
    try:
        probe = subprocess.run(
            [_GIT, 'merge-base', '--is-ancestor', ref, 'HEAD'],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


def _increment_size(root: Path, ref: str) -> int:
    """How many commits ``ref..HEAD`` holds -- the number a gate would have to judge."""
    out = _git_out(root, 'rev-list', '--count', f'{ref}..HEAD')
    return int(out) if out.isdigit() else -1


def admitted(root: Path, candidates: Sequence[str]) -> tuple[str, ...]:
    """The candidates that name a real ancestor of HEAD, IN THE ORDER GIVEN.

    Exposed rather than kept private because it is the half a caller needs in order to explain an
    answer: "your ref was not admitted" and "your ref was admitted and something was narrower" are
    different diagnoses with different remedies, and a function returning only the winner cannot
    tell them apart.

    ``@{push}`` and other revision EXPRESSIONS are accepted here: each candidate is handed to git as
    written, so a caller may pass a spelling only git can resolve.
    """
    return tuple(ref for ref in candidates if _is_ancestor(root, ref))


def gate_base(root: Path, candidates: Sequence[str], *, fallback: str) -> str:
    """The narrowest admitted candidate, so a gate judges the PUSH INCREMENT and nothing wider.

    Args:
        root: the checkout being judged.
        candidates: refs to consider, in PRIORITY order -- a hook-supplied "from" ref, the branch's
            own push target, an integration line, a trunk. NO DEFAULT: which refs exist and what
            they are called is the adopting repo's branching model, and a mechanism that guessed it
            would hand every other repo this family's.
        fallback: what to answer when NOTHING is admitted. NO DEFAULT, and this is the argument that
            most needs one withheld -- ``origin/main`` is exactly the wrong answer in a repo whose
            trunk is called something else, and it fails by reporting a lane as clean rather than by
            erroring.

    Returns:
        The admitted candidate with the smallest ``ref..HEAD`` increment, ties going to the earliest
        in *candidates*; or *fallback* when none was admitted.

    Raises:
        ValueError: *candidates* is empty, or *fallback* is. An empty candidate list makes this
            function a constant, and an empty fallback makes its answer unusable as a git ref.

    """
    if not tuple(candidates):
        msg = (
            'gate_base needs at least one candidate ref. With none, the answer is the fallback '
            'unconditionally and the whole admission rule is dead code wearing a mechanism.'
        )
        raise ValueError(msg)
    if not fallback:
        msg = (
            'gate_base needs a fallback ref naming the widest honest base for THIS repo. It has no '
            'default on purpose: a guess is wrong in any repo whose trunk is named otherwise, and it '
            'fails by reporting a lane as clean rather than by erroring.'
        )
        raise ValueError(msg)
    live = admitted(root, candidates)
    if not live:
        return fallback
    return min(live, key=lambda ref: _increment_size(root, ref))
