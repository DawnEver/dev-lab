"""A PLACEMENT ROSTER's arms -- the walk, the completeness ratchet, and the two bars' bounding.

WHAT A PLACEMENT ROSTER IS. Each repo in this family declares, file by file, whether a dev module is
that repo's own (``STAYS``), a generic mechanism (``MOVES``), or both (``SPLITS``), and holds four
properties against the declaration: every file is placed, a ``STAYS`` claim has evidence, a ``MOVES``
claim survives the converse, and a ``STAYS`` or ``SPLITS`` file is mostly this repo's BY DENSITY. Four
such rosters exist and all four hand-rolled the mechanism. The readings that decided what is family and
what is not are DATA in :mod:`lab_commons.dev.famtests._placement_readings`; the density half is
:mod:`lab_commons.dev.famtests.density`.

THE CEILING IS NOT A FAMILY CONSTANT, AND THAT IS THE FINDING THIS MODULE EXISTS TO CARRY. Both labs
and motronics' tests roster bound ``OWN_MECHANISM_CEILING`` at 50; motronics' ``scripts/`` roster bounds
it at 40, and the intervals are not merely different -- TWO PAIRS OF THEM ARE DISJOINT. ``(35, 42)``
excludes 50 and ``(49, 55)`` excludes 40, so a family module shipping one value would be wrong for one
of its four consumers ON THAT CONSUMER'S OWN MEASUREMENT, and wrong in the ADMITTING direction, which
is the silent one. The density minimum reads the other way -- all four bound 3.0 and their intervals
intersect in ``(2.54, 3.06]`` -- and it does not ship as a constant either, because publishing it would
delete four independent measurements and replace them with a copy.

So neither bar is here. What is here is the ARM: :func:`assert_ceiling_is_bounded` and
:func:`assert_minimum_is_bounded` take the repo's value together with the two MEASURED READINGS that
bracket it, and refuse a value the repo's own evidence does not contain. All four rosters wrote that
bracket as a pair of rows in a COMMENT, where nothing could check it -- and a comment is exactly where a
bar quietly widens to absorb the row that reds. These arms make the pair the argument.

THE EMPTY DECLARATION IS ACCEPTED HERE -- the :mod:`~lab_commons.dev.famtests.datedmemory` side of that
fork rather than the :mod:`~lab_commons.dev.famtests.rostercensus` side. An empty debt mapping means
every ``STAYS`` and ``SPLITS`` row clears both bars, which is the state the ratchet exists to REACH;
refusing it would make the fixed state unreachable. The vacuity is closed by the walk's floor instead,
which :func:`assert_every_file_is_placed` binds -- BOTH sides of it -- before it compares a single path,
because "nothing unplaced" over an EMPTY walk reports exactly what a fully classified tree reports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from lab_commons.dev import floors

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping
    from pathlib import Path

__all__ = [
    'MOVES',
    'SPLITS',
    'STAYS',
    'BarMisbounded',
    'Placement',
    'StaleDebt',
    'Unplaced',
    'assert_ceiling_is_bounded',
    'assert_every_file_is_placed',
    'assert_minimum_is_bounded',
    'assert_no_stale_debt',
    'placed_files',
]

#: The three sides a row may take, spelled identically in all four rosters. Strings rather than an enum
#: because a roster is DATA a human writes and a human reads.
STAYS = 'stays'
MOVES = 'moves'
SPLITS = 'splits'


class BarMisbounded(AssertionError):
    """A bar sits outside the interval its repo's own two measured readings draw around it."""


class StaleDebt(AssertionError):
    """A debt row names a path the manifest does not place -- a shortfall describing a gone file."""


class Unplaced(AssertionError):
    """The walk and the manifest disagree: an unplaced file, or a row naming a file that is gone."""


@dataclass(frozen=True)
class Placement:
    """One file's side, and the FACT that decides it. The reason is the deliverable.

    Structurally identical to the four existing spellings, so adopting it is an import rather than a
    rewrite.
    """

    side: str
    why: str


def assert_ceiling_is_bounded(value: int, *, admits: int, refuses: int, what: str) -> None:
    """A CEILING must sit at or above the largest reading it admits and below the smallest it refuses.

    THE INTERVAL IS TWO REAL FILES, NOT AN ABSTRACTION, which is why the arguments are READINGS rather
    than bounds. All four rosters wrote their bound as a pair of measured rows in a comment, where
    nothing could check it -- and a comment is exactly where a bar quietly widens to absorb the row
    that reds. This arm makes the pair the argument.

    Args:
        value: the bar this repo declares.
        admits: the largest ``own`` reading the bar must ADMIT, measured on a real file.
        refuses: the smallest ``own`` reading the bar must REFUSE, measured on a real file.
        what: names the bar, so the refusal says which roster drifted. NO DEFAULT: a default label does
            not raise, it MISDIRECTS.

    Raises:
        BarMisbounded: the two readings bracket nothing, or *value* falls outside them.

    """
    if admits >= refuses:
        msg = (
            f'the {what} ceiling is bounded by admits={admits} and refuses={refuses}, which brackets '
            f'nothing: the file it must admit reads at or above the file it must refuse, so no value '
            f'satisfies both. RE-MEASURE the two rows -- the pair went stale, not the bar.'
        )
        raise BarMisbounded(msg)
    if not admits <= value < refuses:
        msg = (
            f'the {what} ceiling is declared {value}, outside the interval [{admits}, {refuses}) its '
            f'own measured rows draw: it must admit a file reading {admits} and refuse one reading '
            f'{refuses}. A bar outside its evidence arrived without its argument, and one that is too '
            f'HIGH admits rows silently. Re-measure the two rows, or move the bar to the number they '
            f'bracket. NEVER copy a sibling repo`s value: three of this family`s four rosters read 50 '
            f'and the fourth reads 40, over intervals that exclude each other`s value.'
        )
        raise BarMisbounded(msg)


def assert_minimum_is_bounded(value: float, *, admits: float, refuses: float, what: str) -> None:
    """A MINIMUM must sit at or below the smallest reading it admits and above the largest it refuses.

    The mirror of :func:`assert_ceiling_is_bounded`, and the direction is in the NAME rather than in a
    flag: a boolean saying which way a bar points is a branch every reader has to hold, and two arms
    say it once in the one place every call site already reads.

    Args:
        value: the bar this repo declares, as a percentage.
        admits: the smallest percentage the bar must ADMIT, measured on a real file.
        refuses: the largest percentage the bar must REFUSE, measured on a real file.
        what: names the bar -- see :func:`assert_ceiling_is_bounded`.

    Raises:
        BarMisbounded: the two readings bracket nothing, or *value* falls outside them.

    """
    if refuses >= admits:
        msg = (
            f'the {what} minimum is bounded by refuses={refuses} and admits={admits}, which brackets '
            f'nothing: the file it must refuse reads at or above the file it must admit, so no value '
            f'satisfies both. RE-MEASURE the two rows.'
        )
        raise BarMisbounded(msg)
    if not refuses < value <= admits:
        msg = (
            f'the {what} minimum is declared {value}, outside the interval ({refuses}, {admits}] its '
            f'own measured rows draw. A bar outside its evidence arrived without its argument, and one '
            f'that is too LOW admits rows silently. Re-measure the two rows, or move the bar to the '
            f'number they bracket.'
        )
        raise BarMisbounded(msg)


def placed_files(
    root: Path,
    *,
    trees: Collection[str],
    suffixes: Collection[str],
    not_placed: Collection[str],
) -> tuple[str, ...]:
    """Every file a roster must classify, as sorted repo-relative POSIX paths.

    Args:
        root: this checkout. NO DEFAULT and no ``Path(__file__).parents[n]`` fallback -- the depth that
            resolves a root is a fact about the CONSUMER's directory layout, and a wheel computing it
            from its own location resolves to wherever it happens to be installed.
        trees: the trees this roster answers for, repo-relative. NO DEFAULT: the scope claim is the
            roster's, and a guessed one walks the wrong tree and then reports it clean.
        suffixes: what counts as a runnable file. NO DEFAULT, and the widening is a measured correction
            rather than a preference -- motronics walked ``*.py`` only until 2026-09-16, so eight shell
            and PowerShell files in its ``scripts/`` tree had never been classified by anything. A
            language is as poor a boundary as a tree.
        not_placed: path PARTS that are never placed -- build output, agent memory. NO DEFAULT: a wrong
            exclusion set does not raise, it REMOVES files from the population, and the walk then
            reports a tree with nothing unplaced in it.

    Returns:
        The population, sorted. ``__init__.py`` is ALWAYS omitted rather than left to the exclusion
        set: it carries no knowledge, so it follows whatever its directory does, and placing it would
        be rows of noise around the decisions that matter. All four rosters omit it for that same
        written reason, which is what makes it the kit's answer rather than a repo's.

    """
    out: set[str] = set()
    for tree in trees:
        for path in (root / tree).rglob('*'):
            if not path.is_file() or path.suffix not in suffixes:
                continue
            if path.name == '__init__.py' or any(part in not_placed for part in path.parts):
                continue
            out.add(path.relative_to(root).as_posix())
    return tuple(sorted(out))


def assert_every_file_is_placed(
    found: Collection[str],
    *,
    declared: Collection[str],
    floor: int,
    headroom: int,
    what: str,
) -> None:
    """COMPLETENESS, BOTH DIRECTIONS, over a walk bound to a floor before either direction is read.

    A file with no row is silently unplaced, which is how a migration loses files; a row naming a file
    that is gone reads as a live decision about nothing. Both halves are needed, or the roster rots in
    one direction while the other stays green -- the ratchet's two sides.

    THE FLOOR COMES FIRST AND TAKES BOTH OF ITS OWN SIDES. "Nothing unplaced" over an EMPTY walk
    reports exactly what a fully classified tree reports, so the low side runs before a single
    comparison; and a floor the tree has outgrown refuses only a total collapse, so the high side runs
    too. Both are :mod:`lab_commons.dev.floors`, which is where that refusal lives for the family.

    Args:
        found: the walk's population -- :func:`placed_files`.
        declared: the manifest's keys.
        floor: this repo's measured floor on the walk. NO DEFAULT.
        headroom: the largest ``found - floor`` this repo accepts before the floor must be re-measured.
            NO DEFAULT.
        what: names the roster.

    Raises:
        Unplaced: a walked file has no row, or a row names a file the walk did not reach.
        lab_commons.dev.floors.FloorUnmet: the walk fell below its floor.
        lab_commons.dev.floors.SlackFloor: the floor has been outgrown past its headroom.
        lab_commons.dev.floors.FloorMisdeclared: the floor or the headroom refuses nothing.

    """
    floors.assert_floor(len(found), floor=floor, what=what)
    floors.assert_floor_still_binds(len(found), floor=floor, headroom=headroom, what=what)

    missing = sorted(set(found) - set(declared))
    gone = sorted(set(declared) - set(found))
    if missing or gone:
        msg = (
            f'the {what} roster and its tree disagree. UNPLACED (walked, no row): {missing or "none"}. '
            f'GONE (row, not walked): {gone or "none"}. A file with no row is silently unplaced; a row '
            f'with no file is a decision about nothing. Both are edits to the MANIFEST, never to the '
            f'walk.'
        )
        raise Unplaced(msg)


def assert_no_stale_debt(*, declared: Collection[str], debt: Mapping[str, str] | Collection[str], what: str) -> None:
    """A SHORTFALL ROW MUST NAME A ROW THE MANIFEST STILL PLACES -- the half no consumer wrote.

    Every roster in the family records its below-the-bar rows as a NAMED SET carrying each row's
    measured numbers, and every roster strict-xfails them so a row that starts passing must be DELETED
    rather than absorbed by editing a digit. What none of the four checks is the other direction: a
    debt row whose FILE is gone. It then describes nothing, still reads as a live shortfall, and its
    strict xfail can never fire -- the parametrize that would have run it no longer has the row. The
    completeness arm above already refuses this shape one level out; this is the same refusal applied
    to the debt mapping.

    THE EMPTY DEBT IS ACCEPTED -- the :mod:`~lab_commons.dev.famtests.datedmemory` side of the fork,
    not :mod:`~lab_commons.dev.famtests.rostercensus`'s. There an empty waiver meant the arm had
    outlived its subject and had to be deleted. Here a roster with no debt is a tree where every
    ``STAYS`` and ``SPLITS`` row clears both bars -- the state the ratchet exists to REACH -- and
    refusing it would make the fixed state unreachable. The vacuity is closed by the walk's floor
    instead, which runs whether the debt is empty or not.

    Args:
        declared: the manifest's keys.
        debt: the below-the-bar rows, as a mapping of path to its measurement or as a bare set.
        what: names the roster.

    Raises:
        StaleDebt: a debt row names a path the manifest does not place.

    """
    stale = sorted(set(debt) - set(declared))
    if stale:
        msg = (
            f'the {what} roster records a shortfall for {stale}, which its manifest does not place. A '
            f'debt row describing a gone file reads as a live shortfall and can never be worked off: '
            f'nothing parametrizes it, so its strict xfail cannot fire. DELETE the row in the commit '
            f'that deleted its file.'
        )
        raise StaleDebt(msg)
