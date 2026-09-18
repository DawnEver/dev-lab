"""The controls for :mod:`lab_commons.dev.floors` -- every arm driven in BOTH directions.

WHAT IS PROVED HERE. A floor helper is the one module whose own failure is invisible by inspection:
if it never raised, every guard in the family would go on reporting green and nothing downstream
would look different. So each arm is driven on the violating side AND on the honest side beside it,
and the two sides of the ratchet are asserted against each other -- a value that clears
:func:`~lab_commons.dev.floors.assert_floor` and trips
:func:`~lab_commons.dev.floors.assert_floor_still_binds` is what says the two arms are not one arm
written twice.

THE LABEL GETS A CONTROL OF ITS OWN, which is unusual for a string and is the point. A wrong *what*
does not raise; it puts the wrong guard's name in the refusal. That cannot be caught by a signature,
so it is asserted here: the message a caller reads must carry the label it passed.
"""

from __future__ import annotations

import pytest

from lab_commons.dev.floors import (
    FloorMisdeclared,
    FloorUnmet,
    SlackFloor,
    assert_floor,
    assert_floor_still_binds,
    slack,
)

#: One scan's label. Planted rather than imported, so nothing here depends on a consumer's
#: vocabulary -- which is the fact the signature refuses to guess.
WHAT = 'planted-corpus'


def test_the_slack_reading_is_signed_so_a_caller_sees_which_side_it_is_on() -> None:
    """The pure reading both arms are built on, at and on either side of the floor."""
    assert slack(208, floor=180) == 28
    assert slack(180, floor=180) == 0, 'sitting exactly on the floor is legal and must read as zero room'
    assert slack(3, floor=180) == -177, 'an unmet floor must read NEGATIVE, not clamp to zero'


def test_a_scan_below_its_floor_is_refused_and_the_one_above_it_is_not() -> None:
    """THE CHECK, both directions: the collapsed walk reds and the honest neighbour is left alone."""
    assert_floor(180, floor=180, what=WHAT)
    assert_floor(208, floor=180, what=WHAT)
    with pytest.raises(FloorUnmet, match='read 3, below its measured floor of 180'):
        assert_floor(3, floor=180, what=WHAT)


def test_an_empty_walk_is_the_shape_the_floor_exists_for() -> None:
    """The case every copy of this refusal was written for: zero read, zero offenders, green."""
    with pytest.raises(FloorUnmet, match='Finding NOTHING is vacuous'):
        assert_floor(0, floor=1, what=WHAT)


def test_a_floor_of_zero_is_refused_as_the_vacuity_written_down() -> None:
    """THE FLOOR'S OWN FLOOR, and it is a different exception because a different file fixes it."""
    for declared in (0, -1):
        with pytest.raises(FloorMisdeclared, match='refuses nothing'):
            assert_floor(0, floor=declared, what=WHAT)
    # A large population cannot redeem a floor that refuses nothing: the declaration is judged first.
    with pytest.raises(FloorMisdeclared, match='refuses nothing'):
        assert_floor(9999, floor=0, what=WHAT)


def test_the_misdeclaration_is_not_caught_by_the_arm_that_catches_a_short_scan() -> None:
    """The two exceptions must be TELLABLE APART, or a caller cannot act on either."""
    assert not issubclass(FloorMisdeclared, FloorUnmet)
    assert not issubclass(FloorUnmet, FloorMisdeclared)
    assert not issubclass(SlackFloor, FloorUnmet)
    for kind in (FloorMisdeclared, FloorUnmet, SlackFloor):
        assert issubclass(kind, AssertionError), (
            f'{kind.__name__} must be an AssertionError: a guard that fails is a FAILURE, and a '
            f'RuntimeError reads as a broken test rather than a broken tree.'
        )


def test_the_refusal_names_the_scan_the_caller_named() -> None:
    """THE CONTROL FOR THE LABEL: a string argument whose wrong value MISDIRECTS rather than raises."""
    with pytest.raises(FloorUnmet) as short:
        assert_floor(1, floor=5, what='absolute-tolerance (src)')
    assert 'absolute-tolerance (src)' in str(short.value)
    assert 'CJK' not in str(short.value), (
        "a default label would put some other guard's name in this refusal, which is the defect this "
        'argument has no default for.'
    )
    with pytest.raises(SlackFloor) as slackened:
        assert_floor_still_binds(2000, floor=180, headroom=200, what='package source')
    assert 'package source' in str(slackened.value)


def test_an_outgrown_floor_is_refused_and_a_floor_with_room_left_is_not() -> None:
    """THE RATCHET'S SECOND SIDE, driven on both sides of the headroom."""
    assert_floor_still_binds(208, floor=180, headroom=200, what=WHAT)
    assert_floor_still_binds(380, floor=180, headroom=200, what=WHAT)  # exactly AT the headroom still binds
    with pytest.raises(SlackFloor, match='past the 200 headroom'):
        assert_floor_still_binds(381, floor=180, headroom=200, what=WHAT)


def test_a_headroom_of_zero_is_refused_because_it_pins_the_exact_count() -> None:
    """The count-pin failure, refused at the door: a band that admits no growth is not a band."""
    for declared in (0, -5):
        with pytest.raises(FloorMisdeclared, match='A headroom is a band, not a pin'):
            assert_floor_still_binds(180, floor=180, headroom=declared, what=WHAT)


def test_the_two_arms_are_not_one_arm_written_twice() -> None:
    """The proof the second side is a SEPARATE capability: one population clears one and trips the other.

    Without this, the slack arm could be a re-spelling of the low arm and every test above would
    still pass -- which is exactly how a detector that never fires survives review.
    """
    assert_floor(2000, floor=180, what=WHAT)
    with pytest.raises(SlackFloor):
        assert_floor_still_binds(2000, floor=180, headroom=200, what=WHAT)

    with pytest.raises(FloorUnmet):
        assert_floor(3, floor=180, what=WHAT)
    # An UNMET floor is not a SLACK floor: the second arm must stay silent on it, or one broken
    # walk would be reported twice under two different diagnoses.
    assert_floor_still_binds(3, floor=180, headroom=200, what=WHAT)
