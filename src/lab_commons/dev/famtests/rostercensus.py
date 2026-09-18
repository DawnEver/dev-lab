"""THE ROSTER IS RE-READ AGAINST THE KIT -- the assertion body, so it is not hand-written a third time.

WHAT THE CONSUMER'S FILE ASSERTS. A placement roster decides a row's side by a DENSITY bar, which
answers *is this file mostly generic?*. That is a good question and a DIFFERENT one from *has the
family already expressed this?*, and until 2026-09-18 nothing in any repo asked the second. So a row
keeps its side after its subject lands upstream, and the only thing that would have caught it is a
human re-reading every row. Across three tranches of the family's largest roster the error ran ONE
WAY every time -- 17 rows declared MOVES, 7 were real, 5 were splits and 5 were already in the kit.

WHY THIS IS A SHARED BODY, and it is the cheapest case this package has. :mod:`lab_commons.dev.
supersede` already holds the detectors, the grades, the ruler and the two floors; what sat on top of
it was a consumer-side file of ARMS, and it was written by hand TWICE on the same day -- wdg-lab
`cc8d8c11` at 190 lines and optimi-lab `4c5b1cd` at 198. Diffed with each repo's own name blanked,
the two files are IDENTICAL IN CODE: every line that differs is a docstring, and the row counts and
the extra paragraphs each one carries are exactly the repo's own measurement. A 100%-identical body
under two names is not a shared convention, it is the fork this package exists to remove, and it had
a two-day head start on being one.

EVERY REPO-SHAPED FACT ARRIVES AS A KEYWORD ARGUMENT WITH NO DEFAULT, and here there are six: the
kit's dotted package, the row count the roster declares, the kit-module floor AND ITS HEADROOM, the
spelling of the MOVES side, and the waiver. The headroom is the newest and the one that was missing
rather than defaulted -- see :func:`assert_reach` for what a one-sided floor cost both labs on the
day it was added. ``LAB_CZ_BASE_REF`` is the worked example the family already paid for
twice -- a guessed ``origin/main`` in a repo whose trunk is named otherwise resolves to nothing and
REPORTS THE LANE CLEAN, and a stray trailing newline on a resolved ``@{push}`` did the same thing
from the other side. THE FAILURE MODE OF A GUESSED ANSWER IS NOT AN ERROR, IT IS A WIDER SCOPE. A
default *package* one level short is the same defect in this module's own subject: it resolves every
``lab_commons.dev.x`` import to the token ``dev``, matches no kit module, and reports UNTOUCHED for
every row -- which is what a fully forked tree reports.

THE WAIVER IS A NAMED SET AND IT MAY NOT BE EMPTY, which is the second side of the ratchet rather
than a nicety. :func:`assert_waiver_is_the_named_set` compares by EQUALITY in both directions so an
arrival is a real stale row and a departure is the fix landing; and it REFUSES an empty declaration
outright, because the day a consumer's waiver goes to nothing the arm has to be DELETED rather than
left pinned at the empty set, where it would be a waiver nothing uses. That day is scheduled, and it was
scheduled once already: both labs pinned six ``NAMED_ONLY`` rows caused by
:func:`~lab_commons.dev.supersede.imported_kit_modules` resolving a sub-package import to the wrong
segment, ``1aa2738`` fixed ONE SPELLING of that import, and ``from lab_commons.dev.famtests.x import
y`` stayed blind for another day -- so a consumer that wrote the natural form kept its waiver and had
no way to earn its way out. Both spellings resolve now and the six go to zero on the next reinstall.
The pin reddening then is the ratchet working.

WHAT THIS DOES NOT PROVE, stated so an adoption row cannot overclaim. The census is blind to a LIVE
FORK that imports nothing and that no kit docstring names; :mod:`~lab_commons.dev.supersede` says so
itself and calls surface overlap a RULER rather than a detector. Green here means no row is stale BY
THE TWO DETECTORS, never that the roster is right.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

from lab_commons.dev import floors, supersede

if TYPE_CHECKING:
    from collections.abc import Container, Mapping

__all__ = [
    'SUBPACKAGE_IMPORT',
    'EmptyWaiver',
    'UnadoptedWaiver',
    'UnresolvedKit',
    'assert_every_waived_row_adopted',
    'assert_no_stale_moves',
    'assert_reach',
    'assert_the_grader_still_convicts',
    'assert_waiver_is_the_named_set',
    'kit_directory',
    'named_only_paths',
    'stale_moves',
]


class UnresolvedKit(AssertionError):
    """The kit package does not resolve to a directory, so there is no kit to take a census of."""


class EmptyWaiver(AssertionError):
    """A waiver with no members waives nothing -- delete the arm rather than pin it at empty."""


class UnadoptedWaiver(AssertionError):
    """A row is waived as having adopted a kit module and its own text does not import it."""


#: How a sub-package adoption is SPELLED, so a waiver is proved by the consumer file's own text
#: rather than by the table that waives it. This one is the family's and not a repo's. It is ONE of
#: the forms in :data:`lab_commons.dev.supersede.IMPORT_SPELLINGS` and not the only one a consumer
#: may write -- that claim used to be made here and was false. It stays narrow on purpose: a waiver
#: exists only for a row the IMPORT detector cannot corroborate, and since the detector now reads
#: every spelling, a row that adopts by any other form is not NAMED_ONLY and never reaches here.
SUBPACKAGE_IMPORT = 'from lab_commons.dev.famtests import '


def kit_directory(*, package: str) -> Path:
    """Where *package* is installed, resolved by SPEC rather than by importing it.

    The kit is read as SOURCE and never executed: a census must be able to judge a kit version that
    is not the one running, and importing the thing under measurement is how a measurement acquires
    a side effect.

    Args:
        package: the kit directory's OWN dotted path -- ``lab_commons.dev``, never ``lab_commons``.
            No default, because one level short is the fail-quiet in the module docstring.

    Returns:
        The directory :func:`lab_commons.dev.supersede.kit_modules` should be pointed at.

    Raises:
        UnresolvedKit: *package* is not an importable package in this environment.

    """
    spec = importlib.util.find_spec(package)
    if spec is None or not spec.submodule_search_locations:
        msg = (
            f'{package!r} does not resolve to a package in this environment, so there is no kit to '
            f'read and every row would grade UNTOUCHED -- the answer a finished migration gives. '
            f'Reinstall the kit through the dependency door of this repo rather than lowering a floor.'
        )
        raise UnresolvedKit(msg)
    return Path(spec.submodule_search_locations[0])


def assert_reach(census: supersede.Census, *, rows_declared: int, module_floor: int, module_headroom: int) -> None:
    """THE FLOOR'S OWN ARM, BOTH SIDES: every declared row was judged, against a kit that is really there.

    Three separate readings, because they fail for different reasons and a caller that conflates them
    cannot act on any: a roster the census did not finish reading has rows whose side nothing
    re-checks, a kit nobody read grades the whole roster UNTOUCHED, and a floor the kit has OUTGROWN
    proves only that a kit exists.

    THE THIRD READING IS NEW AND IT IS HERE BECAUSE THE ABSENCE WAS CONVICTED RATHER THAN SUSPECTED.
    This function took a ``module_floor`` and no headroom, so it was structurally one-sided, and both
    consumers paid for that the same way on 2026-09-18: ``KIT_MODULE_FLOOR`` had been left at 35 while
    the kit grew 46 -> 51 -> 56, i.e. it would have passed a kit that had lost THREE FIFTHS of itself,
    and each lab then wrote the missing side by hand in its own test file -- the same four lines under
    two names, which is the fork this package exists to remove. Neither lab was wrong to write it; the
    arm they were calling had one side.

    Args:
        census: what :func:`lab_commons.dev.supersede.take_census` returned.
        rows_declared: how many rows the consumer's roster holds. EQUALITY, not a floor -- the
            roster is the population, so a row it declares and the census did not judge is a gap.
        module_floor: the smallest kit the consumer will accept a verdict from. No default: the kit
            grows and shrinks, and one repo's measured number is not another's.
        module_headroom: how far past *module_floor* the installed kit may grow before the floor has
            stopped separating a full read from a broken one and must be RE-MEASURED. No default, for
            the same reason and one more: it prices how much of the kit a resolution may silently
            lose, and that price is the consumer's to state rather than this module's to assume.

    Raises:
        supersede.VacuousCensus: the floor is not positive, or the kit read fell below it.
        AssertionError: the census judged a different number of rows than the roster declares.
        lab_commons.dev.floors.FloorMisdeclared: *module_headroom* refuses nothing.
        lab_commons.dev.floors.SlackFloor: the kit has outgrown the floor past its headroom.

    """
    if module_floor <= 0:
        msg = f'a kit-module floor of {module_floor} refuses nothing -- a floor of zero is the vacuity written down.'
        raise supersede.VacuousCensus(msg)
    if census.rows_read != rows_declared:
        msg = (
            f'the census judged {census.rows_read} of {rows_declared} declared rows. A row the census '
            f'never read is a row whose side nothing re-checks, which is the state this arm exists to '
            f'end -- fix the roster source rather than the number here.'
        )
        raise AssertionError(msg)
    if census.modules_read < module_floor:
        msg = (
            f'{census.modules_read} kit modules read, below the {module_floor} floor. Fix the '
            f'installed kit, never the floor: every row reads UNTOUCHED against a kit nobody read, '
            f'and that is exactly what a finished migration looks like.'
        )
        raise supersede.VacuousCensus(msg)
    floors.assert_floor_still_binds(
        census.modules_read, floor=module_floor, headroom=module_headroom, what='KIT-MODULE-FLOOR'
    )


def stale_moves(census: supersede.Census, *, moves_side: str) -> dict[str, str]:
    """THE CHECK, as a reading: rows declared *moves_side* whose subject the kit already holds.

    Args:
        census: what :func:`lab_commons.dev.supersede.take_census` returned.
        moves_side: how THIS roster spells the move-it-upstream side. No default -- the label is a
            repo's own vocabulary, and a guessed one matches no row and reports the roster clean.

    Returns:
        ``{path: grade against the kit module that claims it}``, empty when no row is stale.

    """
    return {
        claim.path: f'{claim.grade} against `{claim.kit_module}`'
        for claim in census.flagged
        if claim.side == moves_side
    }


def assert_no_stale_moves(census: supersede.Census, *, moves_side: str) -> None:
    """A ``MOVES`` row the kit already supersedes is the stale-roster defect, named.

    Worth calling on a roster that holds NO such row today: what it guards is the row a later
    tranche writes, and a guard added after the row it was meant to catch has already failed once.

    Raises:
        AssertionError: at least one row is declared to move and its occupant is already upstream.

    """
    stale = stale_moves(census, moves_side=moves_side)
    if stale:
        msg = (
            f'{stale} are declared {moves_side!r} and the kit already holds their subject. A move with '
            f'an occupant is a duplicate running today, not work outstanding -- adopt and delete, then '
            f're-price the row.'
        )
        raise AssertionError(msg)


def named_only_paths(census: supersede.Census) -> frozenset[str]:
    """Every row the kit NAMES and nothing else corroborates -- the reading the waiver is about."""
    return frozenset(claim.path for claim in census.claims if claim.grade == supersede.NAMED_ONLY)


def assert_waiver_is_the_named_set(census: supersede.Census, *, waived: Container[str] | Mapping[str, str]) -> None:
    """The waiver, compared by EQUALITY: an arrival is a real stale row, a departure is the fix.

    Args:
        census: what :func:`lab_commons.dev.supersede.take_census` returned.
        waived: the consumer's NAMED SET of :data:`~lab_commons.dev.supersede.NAMED_ONLY` rows --
            typically ``{path: kit module it adopted}``. A count could not say WHICH row went quiet,
            and an integer that disagrees invites being lowered.

    Raises:
        EmptyWaiver: the declaration is empty. A waiver nothing uses is the other half of the
            ratchet, so the arm is DELETED on the day its last member leaves, not pinned at zero.
        AssertionError: the measured set and the declaration disagree in either direction.

    """
    declared = frozenset(waived)
    if not declared:
        msg = (
            'the waiver declares no rows, so this arm asserts nothing. A waiver nothing uses is as '
            'wrong as a capability that disappeared: when the last member is fixed, DELETE the arm '
            'in that same edit rather than pinning it at the empty set.'
        )
        raise EmptyWaiver(msg)
    found = named_only_paths(census)
    if found != declared:
        msg = (
            f'arrived: {sorted(found - declared)}; adopted-and-still-waived: {sorted(declared - found)}. '
            f'A NAMED_ONLY row is one the kit names and nothing corroborates -- an arrival is either a '
            f'real stale row or a new sub-package adoption, and only reading the file says which.'
        )
        raise AssertionError(msg)


def assert_every_waived_row_adopted(*, root: Path, path: str, module: str, placed: Container[str]) -> None:
    """THE CEILING ON THE WAIVER: membership is earned by the file's own text, never by the table.

    Args:
        root: the consumer checkout *path* is named relative to. No default -- a body resolving this
            itself would answer about whichever tree it happened to be installed into.
        path: the repo-relative waived row.
        module: the :mod:`lab_commons.dev.famtests` module it is waived as having adopted.
        placed: the roster's paths, so a waiver cannot name a row nothing places.

    Raises:
        UnadoptedWaiver: the file does not import *module*, or carries no placement row.

    """
    source = (root / path).read_text(encoding='utf-8')
    if f'{SUBPACKAGE_IMPORT}{module}' not in source:
        msg = (
            f'{path} is waived as having adopted `{module}` and does not import it. This set exists '
            f'because a detector is blind to a sub-package import, not because a row may opt out of '
            f'being judged.'
        )
        raise UnadoptedWaiver(msg)
    if path not in placed:
        msg = f'{path} is waived and carries no placement row, so nothing places it and the waiver is about nothing'
        raise UnadoptedWaiver(msg)


def assert_the_grader_still_convicts(*, moves_side: str) -> None:
    """THE PLANTED CONTROL, in BOTH directions, driving the REAL grader in the installed kit.

    A census that convicts nothing reports exactly what a clean roster reports, so the consumer
    plants the two shapes the grader exists to tell apart -- a whole fork and a partial one -- and a
    third with no kit module at all, which must come back UNTOUCHED. Without that last arm the two
    convictions would be a property of the planted rows rather than of the kit.

    Args:
        moves_side: this roster's spelling of the move side, so the planted rows are shaped like the
            consumer's own and a grader that branched on the label could not pass by accident.

    Raises:
        AssertionError: the grader failed to convict a plant, or convicted one with nothing to
            convict it against.

    """
    module = supersede.KitModule(
        name='checkout',
        claims=frozenset({'scripts/repo/worktree_debris.py'}),
        universe=frozenset({'registered_worktrees', 'orphan_directories', 'stale_branches'}),
    )
    whole = supersede.Row(
        path='scripts/repo/worktree_debris.py',
        side=moves_side,
        public=frozenset({'registered_worktrees', 'orphan_directories'}),
        imports=frozenset(),
    )
    part = supersede.Row(
        path='scripts/repo/worktree_debris.py',
        side=moves_side,
        public=frozenset({'registered_worktrees', 'a_local_answer'}),
        imports=frozenset({'checkout'}),
    )
    if supersede.grade_row(whole, [module]).grade != supersede.SUPERSEDED:
        msg = 'a whole fork went unconvicted, so a silent census would read exactly as a clean roster does'
        raise AssertionError(msg)
    graded = supersede.grade_row(part, [module])
    if graded.grade != supersede.PARTIAL:
        msg = f'a partial fork graded {graded.grade!r}; a seam is not the same answer as a duplicate'
        raise AssertionError(msg)
    if graded.remainder != ('a_local_answer',):
        msg = (
            f'the grader reported remainder {graded.remainder}; the remainder IS the local half of the '
            f'split, so a caller must get the seam rather than a percentage.'
        )
        raise AssertionError(msg)
    if not graded.flagged:
        msg = 'a PARTIAL row did not read as flagged, so the stale-moves arm above would see nothing'
        raise AssertionError(msg)
    if supersede.grade_row(part, []).grade != supersede.UNTOUCHED:
        msg = (
            'with no kit module to judge against, the same row must read UNTOUCHED -- otherwise the '
            'convictions above are a property of the planted row rather than of the kit.'
        )
        raise AssertionError(msg)
