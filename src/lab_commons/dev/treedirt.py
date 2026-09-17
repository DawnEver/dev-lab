"""Did the tree MOVE while it was being judged -- and WHICH paths made it so.

Migrated 2026-09-17 from motronics-studio's ``scripts/gate/tree_state.py``, and it is a SPLIT in two
independent ways, which is why it does not carry that module's name.

**THE IDENTITY HALF DID NOT COME.** That module answered ``(sha, dirty, paths)``, and the ``sha``
half is this family's ALREADY ANSWERED question: a verdict's ``tree=`` is
:func:`lab_commons.dev.content.content_address`, and its docstring records WHY it is not a git sha --
"a run that reads a tree which MOVES underneath it stamps the HEAD it started on, so the verdict
names a commit that was never the input". Shipping a git-sha stamp beside it would be a THIRD
spelling of tree identity in one package, and the weakest of the three. So what is here is the DIRT:
which paths differ from HEAD, and whether the set moved between two readings. That is the half a
content address does not answer, because it says THAT a tree changed and never which file did.

**THE NEUTRAL SET IS THE REPO'S.** Which paths a run may ignore when they appear MID-RUN is a
measured property of one suite -- it is the set of paths NO TEST READS, and the measurement is
"count the test files that reference each candidate". It arrives as an argument with NO DEFAULT. An
empty declaration is the correct, FAIL-CLOSED starting point for a repo that has not measured, and
it is spelled by passing an empty tuple rather than by omitting the argument, so "we measured and
found none" and "we never asked" are different acts. The measurement that produced motronics'
one-entry set is worth quoting for whoever repeats it there: ``.claude/tasks/`` was the only
candidate at ZERO, while ``.claude/memory/`` (168 test files), ``output/`` (126), ``.claude/rules/``
(136) and ``docs-src/`` (31) are live test INPUTS. "It is only markdown" is false wherever a
prose-drift ratchet reads markdown as its input.

THE CONFLATION THIS SPLITS, and it is the reason :func:`verdict_dirt` takes TWO readings. Asking
``git status`` only AFTER a run lets one question ("is the tree dirty NOW?") stand in for a different
one ("did what I tested change while I tested it?"). Those come apart exactly when a run is long:
MEASURED 2026-09-07, a four-hour run was disqualified by a docs commit made while it ran, and the
disqualifying edit could not have changed a single result it had already recorded. A verdict NAMES
its tree and is cited only while that name still matches, so staleness is already the citation
check's job and voiding here did that job a second time and worse.

THREE KINDS, because the remedies differ and a reader handed one word cannot tell them apart:

* ``UNREADABLE`` -- the question could not be asked. Remedy: find out why, and do not cite.
* ``DIRTY`` -- uncommitted work was there BEFORE the run, so there is no commit to vouch for.
  Remedy: commit.
* ``MOVED`` -- the tree changed DURING the run, so this read a mix of two trees. Remedy: re-run.

``UNREADABLE`` is separated from ``DIRTY`` deliberately. The migrated version folded them, and its
own header recorded the cost in the same breath: "the stamp said DIRTY and named nothing, so its
reader had a refused verdict and no way to act on it". Naming the unanswerable case is what turns
that refusal into information. What does NOT change is the polarity -- an unreadable tree still
REFUSES, because promoting an unanswerable question to the reassuring answer is the whole defect.
"""

from __future__ import annotations

import shutil
import subprocess
from enum import Enum
from pathlib import Path

__all__ = ['Dirt', 'Kind', 'path_of', 'status_paths', 'verdict_dirt']

#: Resolved once; see :mod:`lab_commons.dev.checkout` for why a bare name on ``PATH`` is not enough.
_GIT = shutil.which('git') or 'git'

#: A local status read touches no network and no editor, so a child that has not answered in half a
#: minute is hung rather than slow.
_GIT_TIMEOUT_S = 30


class Kind(Enum):
    """What disqualified a verdict about the tree it tested -- or ``CLEAN``, which does not."""

    CLEAN = 'clean'
    UNREADABLE = 'unreadable'
    DIRTY = 'dirty'
    MOVED = 'moved'

    @property
    def disqualifying(self) -> bool:
        """Whether a verdict resting on this reading may be cited. Only ``CLEAN`` may."""
        return self is not Kind.CLEAN


class Dirt:
    """The reading, its kind, and the paths that produced it.

    A plain class rather than a ``NamedTuple`` so nobody unpacks it positionally and silently swaps
    the two fields: they are a kind and a path list, and both are truthy in the failing case.
    """

    __slots__ = ('kind', 'paths')

    def __init__(self, kind: Kind, paths: tuple[str, ...]) -> None:
        """Hold *kind* and the porcelain lines that justify it."""
        self.kind = kind
        self.paths = paths

    def __eq__(self, other: object) -> bool:
        """Two readings are the same reading when their kind and their paths agree."""
        if not isinstance(other, Dirt):
            return NotImplemented
        return (self.kind, self.paths) == (other.kind, other.paths)

    def __hash__(self) -> int:
        """Hashable, because a caller comparing readings across a run will want them in a set."""
        return hash((self.kind, self.paths))

    def __repr__(self) -> str:
        """Both fields, because a failing assertion that shows only the kind sends nobody anywhere."""
        return f'Dirt(kind={self.kind.value!r}, paths={self.paths!r})'


def status_paths(root: Path) -> tuple[str, ...] | None:
    """``git status --porcelain`` lines for *root*, or ``None`` when the question could not be asked.

    ``None`` IS NOT THE EMPTY TUPLE, and this module's whole polarity rests on the distinction: an
    unreadable repository must never render as a clean one. Same rule, same reason and same return
    shape as :func:`lab_commons.dev.checkout.git_out`.
    """
    try:
        status = subprocess.run(
            [_GIT, 'status', '--porcelain'],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if status.returncode != 0:
        return None
    return tuple(line.strip() for line in status.stdout.splitlines() if line.strip())


def path_of(porcelain_line: str) -> str:
    """The path out of one ``git status --porcelain`` line, taking a rename's DESTINATION.

    The destination rather than the source, because a rename's effect on the tree a suite reads is
    the file that now exists. Quoting is stripped: git quotes a path containing unusual bytes, and a
    prefix test against a quoted path silently matches nothing.
    """
    body = porcelain_line.rsplit(' -> ', maxsplit=1)[-1]
    return body.split(maxsplit=1)[-1].strip().strip('"') if body.split() else ''


def verdict_dirt(
    start: tuple[str, ...] | None,
    end: tuple[str, ...] | None,
    *,
    neutral_prefixes: tuple[str, ...],
) -> Dirt:
    """Whether a verdict may be cited for the tree it tested, and why not when it may not.

    Args:
        start: :func:`status_paths` taken BEFORE the run, ``None`` if it could not be read.
        end: the same reading taken AFTER it, ``None`` if it could not be read.
        neutral_prefixes: repo-relative path prefixes that no test in the adopting suite reads, so
            their appearance mid-run cannot have changed a result. NO DEFAULT -- this is a
            MEASUREMENT of one suite, and inheriting another repo's would wave through a path that
            IS a test input here. FAIL-CLOSED either way: an unlisted path is verdict-bearing, so
            ``()`` is the safe declaration and never a broken one.

    Returns:
        The reading. Only ``Kind.CLEAN`` permits a citation.

    """
    if start is None or end is None:
        return Dirt(Kind.UNREADABLE, ())
    if start:
        return Dirt(Kind.DIRTY, start)
    appeared = tuple(line for line in end if line not in frozenset(start))
    bearing = tuple(line for line in appeared if not path_of(line).startswith(neutral_prefixes))
    if bearing:
        return Dirt(Kind.MOVED, bearing)
    return Dirt(Kind.CLEAN, ())
