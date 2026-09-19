"""THE FAMILY'S INSTALL DOORS, one row per repo per door, re-measured rather than remembered.

:mod:`lab_commons.dev.installdoor` answers "does THIS command deliver the declared build". All four
repos now call it, each declaring its OWN door set -- correct, because which files can move an
environment is not portable. What nothing owned is the question one level up: **was a repo's door
set ever looked at, and is it still the set that was measured?** A per-repo guard cannot answer that
about itself: it reads the paths it was given, and a path it was never given is indistinguishable
from a path that holds nothing.

WHAT THIS CENSUS CONVICTED THE DAY IT WAS WRITTEN, 2026-09-19, and both had been green for two days:

1. TWO RECORDED COUNTS WERE WRONG AND NEITHER COULD RED. ``lab-commons`` recorded "9 installer
   commands" and delivered 16; ``wdg-lab`` recorded 28 and delivered 30. Both sat above a floor
   (``5``, ``18``), and a floor is ``DECLARED <= live`` -- satisfied by every shorter declaration,
   blind to a constant drifting either way. These rows assert EQUALITY per file, so a number that
   moves names the file it moved in.

2. A SHARED DOOR WAS CLASSIFIED AGAINST THE WRONG REPO'S MANIFEST.
   ``lab-commons/.github/workflows/python-verify.yml`` is a reusable workflow RUNNING in every
   caller's checkout, holding three lock-consuming commands. Scanned at home against this repo's
   floating names -- ``()``, because the kit IS the kit -- all three read INERT; against a CALLER's
   all three are REVERTS, and no caller scans the file because it is not in its tree. The door was
   OWNED by a repo for which it is vacuous and USED by repos that could not see it.
   :class:`SharedDoor` is that row, judged against the names of the repos that RUN it.

THE ONE CONDITION THE CI ROW RESTS ON, asserted rather than assumed because it is the whole reason a
lock-consuming command in CI is survivable: ``uv.lock`` is TRACKED BY NO REPO IN THIS FAMILY (user
ruling 2026-09-17), and a checkout carries tracked files only, so no lock reaches the runner and the
resolution there is fresh. Commit a lock and that step starts serving it, so
:func:`assert_no_tracked_lock` reds on the commit rather than on the CI run three weeks later.
``setup-uv``'s ``enable-cache`` caches uv's PACKAGE cache, not the lock, and does not weaken it.

WHAT THIS CANNOT SEE, stated so the next reader does not over-read a green:

* A DOOR THAT IS NOT A COMMAND IN A FILE. ``motronics-studio`` builds its ``uv`` invocations as
  Python lists, and a text scan cannot tell which branch composes the live argv. Those are DECLINED,
  naming the mechanism that covers them: a census quietly omitting a door is indistinguishable from
  a census nobody ran.
* WHAT A COMMAND ACTUALLY DID. Every answer is about command TEXT against the MEASURED table in
  ``installdoor``'s docstring. Nothing here installs, syncs or prunes, and nothing here may.
* WHICH EXTRAS SURVIVE. The vocabulary is delivery, not population: a sync naming ``-P`` and no
  ``--extra`` classifies RESOLVES -- right about the kit BUILD, blind to the optional distributions
  it removes, the shape that took one environment from 113 to 30. That ratchet is NOT this one.
* A SIBLING'S UNCOMMITTED WORK, by the choice :func:`door_text` argues.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from lab_commons.dev.checkout import git_out
from lab_commons.dev.installdoor import Delivery, classify, commands, floating_in_manifest

__all__ = [
    'DELIVERY_NAMES',
    'WHY_FLOOR',
    'CensusRowError',
    'Declined',
    'DoorDriftError',
    'DoorRow',
    'Reading',
    'SharedDoor',
    'TrackedLockError',
    'UnreadableRepo',
    'VacuousCensusError',
    'assert_census',
    'assert_no_tracked_lock',
    'committed',
    'door_text',
    'drift',
    'floating_at_head',
    'reachable',
    'read',
    'rows_for',
]

#: The delivery names a row may carry. Taken from the enum rather than typed out, so a value that
#: stops existing cannot survive in the table as a string nothing resolves.
DELIVERY_NAMES: Final[frozenset[str]] = frozenset(member.name for member in Delivery)

#: The shortest a row's REASON may be. A row's deliverable is why that file is a door of that repo
#: and what its numbers mean; a caption cannot carry either, and a DECLINED row's caption is how a
#: door gets dropped while still appearing to have been considered. Shorter than
#: `_config_census.REASON_FLOOR` (240) on purpose: that census decides WHERE an artefact belongs and
#: owes a seam and a consequence, this one records a measurement and owes the fact behind it.
WHY_FLOOR: Final = 150


class CensusRowError(ValueError):
    """A row the census refuses to hold -- an unknown delivery, a caption for a reason, an impossible pair."""


class UnreadableRepo(RuntimeError):
    """A declared checkout is present and its committed state cannot be read, so it is not quietly skipped."""


class DoorDriftError(AssertionError):
    """A declared door no longer measures what the table records, in either direction."""


class VacuousCensusError(AssertionError):
    """The census read fewer repos or fewer doors than its floor -- finding nothing proves nothing."""


class TrackedLockError(AssertionError):
    """A repo tracks ``uv.lock``, so every lock-consuming door in it serves a reviewed-by-nobody pin."""


@dataclass(frozen=True, slots=True)
class Reading:
    """What one door file measured: HOW MANY installer commands, and WHICH deliveries among them.

    Both halves, because either alone is blind. A count cannot say which command changed; a named
    set cannot say that two commands became one. A row pins both and compares by EQUALITY.
    """

    commands: int
    deliveries: frozenset[str]

    def describe(self) -> str:
        """``<n> commands {A, B}``, the spelling a drift message compares two of."""
        listed = ', '.join(sorted(self.deliveries)) or '-'
        return f'{self.commands} commands {{{listed}}}'


def _check_why(why: str, subject: str) -> None:
    """Refuse a reason that is a caption. Shared by every row kind, since the hazard is identical."""
    if len(why) < WHY_FLOOR:
        msg = (
            f'{subject}: a reason of {len(why)} characters, under the {WHY_FLOOR} floor. The reason '
            f'is the deliverable and the numbers are only its label -- and for a DECLINED row it is '
            f'the whole of it, because a caption is how a door gets dropped while still looking '
            f'considered.'
        )
        raise CensusRowError(msg)


@dataclass(frozen=True, slots=True)
class DoorRow:
    """One door file in one repo, with the reading it was MEASURED at and why it is a door there."""

    repo: str
    path: str
    commands: int
    deliveries: frozenset[str]
    why: str

    def __post_init__(self) -> None:
        """Refuse the row AT CONSTRUCTION, so an unmeasured one cannot enter the table at all."""
        _check_why(self.why, self.key)
        unknown = self.deliveries - DELIVERY_NAMES
        if unknown:
            msg = f'{self.key}: {sorted(unknown)} name no Delivery member; the enum is {sorted(DELIVERY_NAMES)}'
            raise CensusRowError(msg)
        if (self.commands == 0) != (not self.deliveries):
            msg = (
                f'{self.key}: {self.commands} commands but deliveries {sorted(self.deliveries)}. A file '
                f'with no installer command has no delivery, and one with a delivery had a command -- '
                f'the pair cannot disagree, and a row that says it does was typed rather than measured.'
            )
            raise CensusRowError(msg)

    @property
    def key(self) -> str:
        """``<repo>::<path>``, the one spelling the census keys and reports rows by."""
        return f'{self.repo}::{self.path}'

    @property
    def reading(self) -> Reading:
        """The reading this row records, so a comparison is between two of one type."""
        return Reading(self.commands, self.deliveries)


@dataclass(frozen=True, slots=True)
class Declined:
    """A door DELIBERATELY not text-censused, recorded with its reason and where it IS checked.

    THE POINT OF THE TYPE IS THAT DECLINING COSTS SOMETHING. Omitting a path from a door set is free
    and silent; a declined row must name the fact that makes a text scan wrong for that file AND the
    mechanism covering it instead -- a door with neither is an unwatched door in a decision's
    clothes.
    """

    repo: str
    path: str
    covered_by: str
    why: str

    def __post_init__(self) -> None:
        """Refuse the row AT CONSTRUCTION, so an unmeasured one cannot enter the table at all."""
        _check_why(self.why, self.key)
        if not self.covered_by:
            msg = (
                f'{self.key} is declined and names no mechanism. A door covered by nothing is not '
                f'declined, it is dropped, and the two are indistinguishable in a list of paths.'
            )
            raise CensusRowError(msg)

    @property
    def key(self) -> str:
        """``<repo>::<path>``, matching :attr:`DoorRow.key` so the two tables share one namespace."""
        return f'{self.repo}::{self.path}'


@dataclass(frozen=True, slots=True)
class SharedDoor:
    """A door file living in ONE repo whose commands run inside ANOTHER repo's checkout.

    The reason this is its own kind rather than a :class:`DoorRow` with a note: the floating names a
    command must be judged against are the names of the repo it RUNS in, and for a reusable CI
    workflow that is never the repo it is stored in. Judged at home it is vacuous; judged where it
    runs it was three reverting doors.
    """

    repo: str
    path: str
    ran_by: tuple[str, ...]
    deliveries: frozenset[str]
    why: str

    def __post_init__(self) -> None:
        """Refuse the row AT CONSTRUCTION, so an unmeasured one cannot enter the table at all."""
        _check_why(self.why, f'{self.repo}::{self.path}')
        if not self.ran_by:
            msg = f'{self.repo}::{self.path} is shared with nobody, which makes it an ordinary door row'
            raise CensusRowError(msg)


def read(text: str, names: tuple[str, ...]) -> Reading:
    """Measure one door file's TEXT against the floating requirements *names*.

    Drives :func:`~lab_commons.dev.installdoor.commands` and
    :func:`~lab_commons.dev.installdoor.classify` -- the real ones -- so a planted control here
    exercises the same code path a repo's own guard does, rather than a second implementation that
    would agree with this one by construction.
    """
    found = [classify(argv, names).name for _line, argv in commands(text)]
    return Reading(len(found), frozenset(found))


def committed(root: Path, relpath: str) -> str | None:
    """*relpath*'s content as COMMITTED in *root*, or ``None`` when it is not committed there.

    ``None`` IS NOT THE EMPTY STRING here and the distinction carries the whole guard: a file that
    was renamed away must read as absent and red, never as a door holding no command.
    """
    return git_out(root, 'show', f'HEAD:{relpath}')


def door_text(root: Path, relpath: str, *, at_head: bool) -> str | None:
    """A door's content, from ``HEAD`` or from the WORKING TREE, and the choice is not cosmetic.

    TWO KINDS OF TREE NEED OPPOSITE ANSWERS, which the first cut got wrong and its live test caught.

    * A SIBLING is read at ``HEAD``. What another repo DECLARES is a committed fact; a lane's
      half-finished edit over there must not be able to turn this repo red for a change that exists
      in no commit, and this repo paid for exactly that on 2026-09-18.
    * THE REPO UNDER VERIFICATION is read from its WORKING TREE. Its rows describe the change under
      review, and reading them at ``HEAD`` makes a door repair unverifiable until after it lands --
      the guard would demand the row and the fix in one blind commit. The distinction
      `_config_census.installed_hook_names` draws: what the family AGREED is committed, THIS tree
      is on disk.
    """
    if at_head:
        return committed(root, relpath)
    path = root / relpath
    return path.read_text(encoding='utf-8', errors='replace') if path.is_file() else None


def reachable(base: Path, paths: dict[str, str]) -> dict[str, Path]:
    """Every declared repo actually checked out under *base*, keyed by repo name.

    A sibling not on this box is ABSENT rather than failing -- repos are cloned per box and a census
    demanding all four would be unrunnable on three. The repo floor in :func:`assert_census` is what
    stops that being a free pass.
    """
    found = {repo: base / relative for repo, relative in paths.items()}
    return {repo: root for repo, root in found.items() if (root / 'pyproject.toml').is_file()}


def floating_at_head(root: Path) -> tuple[str, ...]:
    """The floating requirements *root* DECLARES at ``HEAD``.

    Raises:
        UnreadableRepo: the checkout is there and its manifest is not committed. Answering "none"
            would make every door in that repo INERT, which is the reading under which a census of
            an unreadable tree comes back clean.

    """
    text = committed(root, 'pyproject.toml')
    if text is None:
        msg = (
            f'{root} is checked out and has no committed pyproject.toml, so what it declares cannot be '
            f'read. That is INCONCLUSIVE and must not render as a repo with no floating requirement.'
        )
        raise UnreadableRepo(msg)
    return floating_in_manifest(text)


def rows_for(repo: str, rows: tuple[DoorRow, ...]) -> tuple[DoorRow, ...]:
    """The rows declared for one repo, in table order."""
    return tuple(row for row in rows if row.repo == repo)


def drift(root: Path, rows: tuple[DoorRow, ...], names: tuple[str, ...], *, at_head: bool = True) -> tuple[str, ...]:
    """Every declared row whose live reading is not EQUAL to what it records.

    EQUALITY IN BOTH DIRECTIONS, which is the whole reason this exists beside the per-repo floors: a
    floor is ``declared <= live``, so it cannot see a recorded constant drift -- and it did not,
    twice, for two days. Pure but for the git read, so the planted controls drive THIS function.
    """
    out: list[str] = []
    for row in rows:
        text = door_text(root, row.path, at_head=at_head)
        if text is None:
            out.append(
                f'{row.key} is declared a door and is not committed at that path. A renamed or deleted '
                f'door must red here rather than read as a file holding no command.'
            )
            continue
        live = read(text, names)
        if live != row.reading:
            out.append(f'{row.key} records {row.reading.describe()} and now measures {live.describe()}')
    return tuple(out)


def assert_no_tracked_lock(roots: dict[str, Path]) -> None:
    """Refuse if any repo TRACKS ``uv.lock``.

    THE CONDITION EVERY SURVIVING LOCK-CONSUMING DOOR IN THIS FAMILY RESTS ON. A ``uv sync`` in CI is
    safe only because a fresh checkout contains tracked files only and no lock is among them; commit
    one and that step silently starts serving a pin nobody reviewed -- which is the user ruling of
    2026-09-17 given a mechanism instead of a sentence.

    Raises:
        TrackedLockError: at least one repo tracks it, named.

    """
    tracked = sorted(repo for repo, root in roots.items() if git_out(root, 'ls-files', 'uv.lock'))
    if tracked:
        msg = (
            f'{tracked} track uv.lock. It is untracked FAMILY-WIDE by user ruling, and every '
            f'lock-consuming command that survives this census survives because a fresh checkout '
            f'cannot contain one. Tracking it turns each of those into a door serving an unreviewed '
            f'pin, starting with the `uv sync` in the shared CI workflow.'
        )
        raise TrackedLockError(msg)


def assert_census(
    base: Path,
    paths: dict[str, str],
    rows: tuple[DoorRow, ...],
    *,
    repo_floor: int,
    door_floor: int,
    here: str = '',
) -> dict[str, Path]:
    """Refuse unless every reachable repo's declared doors still measure what the table records.

    *here* names the repo whose WORKING TREE is authoritative -- the one being verified; every other
    is read at ``HEAD``, and :func:`door_text` says why the two need opposite answers. The default
    ``''`` reads everything as published, right for a caller censusing trees it is not editing.

    Returns the repos it read, so a caller pins the NAMED SET rather than a count.

    Raises:
        VacuousCensusError: fewer repos or fewer rows were read than the floors. A census that
            reached one repo and found no drift has found nothing, and reads identically to a clean
            family.
        DoorDriftError: at least one declared row no longer measures what it records, named with the
            recorded reading and the live one.

    """
    roots = reachable(base, paths)
    read_rows = tuple(row for row in rows if row.repo in roots)
    if len(roots) < repo_floor or len(read_rows) < door_floor:
        msg = (
            f'read {len(roots)} repos and {len(read_rows)} door rows, under the floors of {repo_floor} '
            f'and {door_floor}. A census that reached almost nothing and found no drift proves '
            f'nothing -- either a sibling checkout moved, in which case repoint it, or this box '
            f'genuinely holds fewer of them and cannot produce this verdict.'
        )
        raise VacuousCensusError(msg)
    assert_no_tracked_lock(roots)
    problems: list[str] = []
    for repo, root in roots.items():
        problems.extend(drift(root, rows_for(repo, rows), floating_at_head(root), at_head=repo != here))
    if problems:
        listed = '\n  '.join(problems)
        msg = (
            f'the install-door census no longer matches the family:\n  {listed}\n'
            f'RE-MEASURE, then edit the row -- and read the new reading before you do. A count that '
            f'went UP is a door that was added; a delivery that gained REVERTS is the defect this '
            f'whole layer exists for; a row that lost its file is a door nobody is watching.'
        )
        raise DoorDriftError(msg)
    return roots
