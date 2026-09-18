"""A SCAN THAT READ NOTHING IS NOT A CLEAN SCAN -- the floor, BOTH of its sides, one refusal each.

WHAT A FLOOR IS FOR. A guard's failure mode is SILENCE. If its corpus goes empty -- a rename, a
moved directory, a ``tracked_files`` call that answered nothing, an exclusion that widened -- it
reports exactly what a clean tree reports, and it goes on reporting it for as long as nobody looks.
The floor is the one line that separates *no offender* from *no population*, and it is why a green
scan is evidence at all.

WHY THIS IS A FAMILY MODULE AND NOT A CONVENTION, measured 2026-09-18. The refusal is written by
hand EIGHT times in this family and no two copies agree. In the kit alone:
:func:`lab_commons.dev.cjk.assert_floor`, :func:`lab_commons.dev.docwidth.assert_width_floor`,
``lab_commons.dev.famtests._configrender_readings.assert_floor`` and this repo's own
``tests/_arch_corpus.assert_floor`` are four separate bodies of the same four lines, raising four
different exception types -- two ``RuntimeError``, two ``AssertionError``, and TWO OF THE FOUR ARE
BOTH NAMED ``VacuousScan`` over different base classes -- so a consumer cannot catch *the floor
failing* without naming which module's floor it was, and the one name it would reach for is
ambiguous inside this repo alone. Three more are inlined at the top of a larger arm
(``famtests.rulespages``, ``famtests.rostercensus``, ``installdoor``). Outside the kit, ``wdg-lab``
publishes ``tests/architecture/_corpus.bind_floor`` and calls it from SEVEN guards, while
``optimi-lab`` inlines the same ``assert len(x) >= FLOOR`` with its own prose in EIGHT.

THE FLOOR HAS TWO SIDES AND ONLY ONE OF THEM WAS EVER WRITTEN, which is the substantive addition
here rather than de-duplication. Every copy above guards the LOW side: the scan fell below its
number. Nothing guards the other -- a floor measured at 180 against 208 files still reads 180 when
the tree holds 2000, at which point it refuses only a total collapse and passes a walk that lost
nine tenths of its corpus. A FLOOR THE POPULATION HAS OUTGROWN IS A WAIVER NOTHING USES, and a
ratchet has two sides: :func:`assert_floor_still_binds` is that side, and it fails LOUDLY with the
remedy being to re-measure the floor, never to widen the headroom.

EVERY NUMBER HERE ARRIVES AS A KEYWORD ARGUMENT WITH NO DEFAULT, including the LABEL, and that last
one is measured rather than symmetry. :func:`lab_commons.dev.cjk.assert_floor` defaults *what* to
``'CJK'``; a second scan calling it inherits that label and its refusal then names a guard that is
not the one which failed. A wrong label does not raise -- it MISDIRECTS, which is the
``LAB_CZ_BASE_REF`` shape one layer down: THE FAILURE MODE OF A GUESSED ANSWER IS NOT AN ERROR, IT IS
A WIDER SCOPE, and here the scope that widens is the reader's idea of what broke.

THE DECLARATION IS REFUSED SEPARATELY FROM THE TREE, because the two are fixed by different people
in different files. :exc:`FloorMisdeclared` says the number cannot refuse anything -- a floor at or
below zero, or a headroom at zero, which pins the exact count and reds on the next file ADDED. The
other two exceptions are statements about the tree.

WHAT THIS DOES NOT PROVE. A floor is a statement about the SIZE of what was read, never about what
was read. A walk that reaches the right number of the wrong files clears every arm here; that is
:mod:`lab_commons.dev.supersede`'s and each guard's own business, and a floor that claimed otherwise
would be a declaration that lies.
"""

from __future__ import annotations

__all__ = [
    'FloorMisdeclared',
    'FloorUnmet',
    'SlackFloor',
    'assert_floor',
    'assert_floor_still_binds',
    'slack',
]


class FloorMisdeclared(AssertionError):
    """The floor or its headroom cannot refuse anything, so the arm holding it asserts nothing."""


class FloorUnmet(AssertionError):
    """The scan read fewer items than its floor, so its silence is inconclusive rather than clean."""


class SlackFloor(AssertionError):
    """The population outgrew the floor past its headroom -- a waiver nothing uses, in number form."""


def slack(found: int, *, floor: int) -> int:
    """How much room the floor has left: ``found - floor``, negative when the floor is unmet.

    The PURE reading behind both arms, published so a consumer can print it, parametrize on it, or
    carry it into a report without catching an exception to find out what the margin was.

    Args:
        found: the population the scan actually read.
        floor: the number that population is judged against.

    Returns:
        The signed margin. Zero means the scan sits exactly on its floor, which is legal and is the
        state a re-measurement should move it off.

    """
    return found - floor


def assert_floor(found: int, *, floor: int, what: str) -> None:
    """THE LOW SIDE: refuse a scan that read fewer than *floor* items.

    Args:
        found: the population the scan actually read -- the count it is about to report *no
            offenders* over.
        floor: a MEASURED number from the day the guard was written, set below the real population
            with room for ordinary deletion. NO DEFAULT: it is the adopting repo's own measurement,
            and one repo's number handed silently to another is a floor nothing measured.
        what: names the scan, so the refusal says which guard went quiet. NO DEFAULT -- a default
            label does not raise, it MISDIRECTS, and a reader sent to the wrong guard is worse off
            than one sent nowhere.

    Raises:
        FloorMisdeclared: *floor* is at or below zero, which refuses nothing at all.
        FloorUnmet: the population is below the floor.

    """
    if floor <= 0:
        msg = (
            f'the {what} scan declares a floor of {floor}, which refuses nothing -- it is the vacuity '
            f'written down. Measure the population and set the floor below it, or delete the arm.'
        )
        raise FloorMisdeclared(msg)
    if found < floor:
        msg = (
            f'the {what} scan read {found}, below its measured floor of {floor}. Finding NOTHING is '
            f'vacuous rather than green: a walk that stopped early, a tree that moved, and an '
            f'exclusion that widened all report exactly what a clean tree reports. Fix what is read; '
            f'lower the floor ONLY in the same edit that deletes the things it counted.'
        )
        raise FloorUnmet(msg)


def assert_floor_still_binds(found: int, *, floor: int, headroom: int, what: str) -> None:
    """THE OTHER SIDE: refuse a floor the population has outgrown, so the number stays a guard.

    A floor is set below the population of the day it was measured. The population grows; the number
    does not. Past some margin it stops separating *a clean scan* from *a broken walk* and starts
    passing both, at which point the arm reads as protection and is not any -- the same shape as a
    waiver nothing uses, and as wrong as the capability disappearing.

    Args:
        found: the population the scan actually read.
        floor: the number it is judged against.
        headroom: the largest ``found - floor`` this repo accepts before the floor must be
            re-measured. NO DEFAULT, and it is the argument most worth not guessing: it prices how
            much of its corpus a walk may silently lose, which is a different answer for a tree of
            twenty modules and a tree of two thousand.
        what: names the scan -- see :func:`assert_floor`.

    Raises:
        FloorMisdeclared: *headroom* is at or below zero. Zero pins the floor to the exact count, so
            the arm reds on the next file ADDED; that is the count-pin failure, not a tight guard.
        SlackFloor: the floor has been outgrown by more than *headroom*.

    """
    if headroom <= 0:
        msg = (
            f'the {what} floor declares a headroom of {headroom}. Zero or less pins the floor to the '
            f'exact population, so the next file ADDED reds and the honest-looking repair is to edit '
            f'the digit. A headroom is a band, not a pin.'
        )
        raise FloorMisdeclared(msg)
    margin = slack(found, floor=floor)
    if margin > headroom:
        msg = (
            f'the {what} scan read {found} against a floor of {floor} -- {margin} clear, past the '
            f'{headroom} headroom. The floor was measured against a smaller tree and now refuses only '
            f'a total collapse: a walk losing most of its corpus would still clear it. RE-MEASURE THE '
            f'FLOOR against what is there today; raising the headroom is how the arm is kept while the '
            f'guard it stands for is given up.'
        )
        raise SlackFloor(msg)
