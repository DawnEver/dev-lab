"""The controls for :mod:`lab_commons.dev.famtests.density` -- every reader, both ways.

WHAT IS PROVED HERE. Not "the meter runs": what this file owns is that each reader FIRES on a planted
shape and STAYS SILENT on the honest neighbour beside it. A meter reading everything as one repo's and
a meter reading nothing as one repo's both pass a one-sided test, and the second is indistinguishable
from a tree of honest binders -- which is exactly the failure the density arm exists to catch in its
consumers.

EVERY NO-DEFAULT ARGUMENT GETS A COUNTER-CONTROL, and the argument for a signature is never the
signature. It is that a WRONG value REPORTS A NUMBER rather than raising: an undeclared delegation home
inflates a binder into a mechanism, an empty vocabulary reads every file as saturated, and a missing
second signal leaves a repo fact spelled as a path invisible. So the wrong value is planted and the
wrong reading is asserted directly.
"""

from __future__ import annotations

import re

import pytest

from lab_commons.dev.famtests.density import (
    Density,
    NoSignals,
    assert_readings_convict,
    assert_the_meter_still_convicts,
    code_and_delegation,
    code_only,
    justified,
    measure_density,
    meter_readings,
    noun_pattern,
    nouns_in,
)

#: One repo's vocabulary and one repo's delegation home. PLANTED rather than imported, so nothing here
#: depends on a consumer's answer -- which is the fact the signatures refuse to guess.
NOUNS = ('widget', 'sprocket')
HOME = 'lab_commons'


def a_noun() -> re.Pattern[str]:
    """The whole-identifier reading of `NOUNS` -- what three of the four rosters take."""
    return noun_pattern(NOUNS, match_identifier_parts=False)


# --------------------------------------------------------------------------- THE NOUN PATTERN


def test_the_empty_vocabulary_is_refused_because_it_would_match_every_line() -> None:
    with pytest.raises(NoSignals, match='position zero'):
        noun_pattern((), match_identifier_parts=False)


def test_the_boundary_policy_has_no_default_and_the_two_answers_differ_on_a_real_shape() -> None:
    """`widget_size` is nothing to three rosters and a hit to motronics' scripts roster."""
    whole = noun_pattern(NOUNS, match_identifier_parts=False)
    parts = noun_pattern(NOUNS, match_identifier_parts=True)
    assert nouns_in('x = widget_size', noun=whole) == set()
    assert nouns_in('x = widget_size', noun=parts) == {'widget'}
    # And the widening does NOT become substring matching, which is the defect the family paid for.
    assert nouns_in('x = widgetry', noun=parts) == set()


def test_a_noun_is_found_in_prose_and_that_generosity_is_the_hit_readings_whole_point() -> None:
    source = '"""All about the widget."""\n\nvalue = 1\n'
    assert nouns_in(source, noun=a_noun()) == {'widget'}
    assert nouns_in('\n'.join(code_only(source)), noun=a_noun()) == set()


# --------------------------------------------------------------------------- THE CODE READING


def test_a_trailing_comment_is_blanked_without_taking_the_code_beside_it() -> None:
    lines = code_only('value = sprocket  # about the widget\n')
    assert [line.rstrip() for line in lines] == ['value = sprocket']
    assert len(lines[0]) == len('value = sprocket  # about the widget'), 'blanked in place, so no column moves'
    assert nouns_in('\n'.join(lines), noun=a_noun()) == {'sprocket'}


def test_a_delegation_home_must_be_declared_or_a_binder_reads_as_its_own_mechanism() -> None:
    """THE NO-DEFAULT COUNTER-CONTROL: the wrong set does not raise, it INFLATES the reading."""
    source = f'from {HOME}.dev import helper\n\nhelper(1)\nhelper(2)\n'
    declared = measure_density(source, signals=(a_noun(),), delegation_homes=(HOME,))
    guessed = measure_density(source, signals=(a_noun(),), delegation_homes=())
    assert declared.own == 0
    assert guessed.own == 3, 'an undeclared home leaves every delegating line counted as own mechanism'


def test_an_aliased_import_is_still_delegation_and_the_home_itself_is_bound() -> None:
    """The alias reaches `h(1)`; the home's own spelling reaches a dotted call site."""
    source = f'from {HOME}.dev import helper as h\nimport {HOME}.dev.shards\n\nh(1)\n{HOME}.dev.shards.take()\n'
    _, bound = code_and_delegation(source, delegation_homes=(HOME,))
    assert bound == {'h', 'shards', HOME}
    assert measure_density(source, signals=(a_noun(),), delegation_homes=(HOME,)).own == 0


# --------------------------------------------------------------------------- THE METER


def test_a_meter_with_no_signals_is_refused_rather_than_reading_zero_everywhere() -> None:
    with pytest.raises(NoSignals, match='vacuous'):
        measure_density('value = 1\n', signals=(), delegation_homes=())


def test_a_signal_matching_the_empty_string_is_refused_from_the_other_side() -> None:
    with pytest.raises(NoSignals, match='matches the empty string'):
        measure_density('value = 1\n', signals=(re.compile('(x?)'),), delegation_homes=())


def test_a_line_carrying_either_signal_counts_once_and_not_twice() -> None:
    """The two-signal shape motronics uses: a noun OR an owned basename, never double-counted."""
    owned = re.compile(r'(?<![A-Za-z0-9_.\-])(runner\.py)(?![A-Za-z0-9_\-])')
    source = "value = widget_of('runner.py')\nother = 2\n"
    one = measure_density(source, signals=(a_noun(),), delegation_homes=())
    two = measure_density(source, signals=(a_noun(), owned), delegation_homes=())
    assert one.hits == 0, 'the noun reading alone cannot see a path, which is why a second signal exists'
    assert two.hits == 1, 'a line carrying both signals is one repo line, not two'
    assert two.own == 2


def test_the_percentage_of_a_file_with_no_own_lines_is_zero_rather_than_a_division() -> None:
    assert Density(own=0, hits=0).percent == 0.0


# --------------------------------------------------------------------------- THE JUDGEMENT


def test_justified_takes_its_bars_rather_than_closing_over_a_modules_own() -> None:
    """The defect a consumer paid for: ONE reading, two rosters' ceilings, two opposite verdicts."""
    reading = Density(own=47, hits=0)
    assert justified(reading, ceiling=50, minimum_pct=3.0) is True
    assert justified(reading, ceiling=40, minimum_pct=3.0) is False


def test_a_file_above_the_ceiling_is_admitted_by_density_alone() -> None:
    assert justified(Density(own=100, hits=3), ceiling=50, minimum_pct=3.0) is True
    assert justified(Density(own=100, hits=2), ceiling=50, minimum_pct=3.0) is False


# --------------------------------------------------------------------------- THE PLANTED CONTROL


def test_the_planted_control_holds_against_the_meter_that_ships_today() -> None:
    assert assert_the_meter_still_convicts(noun_witness='widget', delegation_home=HOME) is None


def test_the_planted_control_is_driven_and_every_one_of_its_arms_has_been_seen_to_fire() -> None:
    """The judging half is handed WRONG readings, one defect at a time, and must name each.

    An assertion nobody has seen fail is a declaration, and this file's whole subject is declarations
    that lie. Driving `assert_readings_convict` over readings a test SUPPLIES is what makes the split
    from `meter_readings` worth having: the shipped meter cannot be broken from a test, so the
    readings are broken instead.
    """
    honest = meter_readings(noun_witness='widget', delegation_home=HOME)
    said = {'noun_witness': 'widget', 'delegation_home': HOME}

    with pytest.raises(AssertionError, match='PROSE BOUGHT DENSITY'):
        assert_readings_convict({**honest, 'prose': Density(own=2, hits=1)}, **said)

    with pytest.raises(AssertionError, match='STOPPED CONVICTING'):
        assert_readings_convict({**honest, 'dense': Density(own=2, hits=0)}, **said)

    with pytest.raises(AssertionError, match='DELEGATION IS BEING COUNTED'):
        assert_readings_convict({**honest, 'binder': Density(own=4, hits=0)}, **said)

    with pytest.raises(AssertionError, match='two code lines as two'):
        assert_readings_convict({**honest, 'dense': Density(own=1, hits=1)}, **said)
