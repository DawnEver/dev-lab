"""``lab_commons.dev.famtests.storedreadings`` -- every arm driven GREEN and driven RED.

EVERY RED HERE IS REACHABLE, which is the difference from ``boxseat``'s suite and is worth stating
because it is a property of the subject rather than of the effort put in: this body reads TEXT and
compares it against a callable the consumer supplies, so both halves of every arm can be planted
without replacing anything under test. Nothing is stubbed and nothing is monkeypatched; the only
injected thing is ``derive``, which is an argument by design because a planted row names no file.

THE CORPUS ROWS BELOW ARE REAL. They are copied verbatim from the two labs' placement rosters as they
stood on 2026-09-19, with the paths kept, because the reader's whole risk is that a regex guessed in
the abstract finds nothing in the prose people actually write. A reader tested only against sentences
its own author invented is a reader tested against itself.
"""

from __future__ import annotations

import pytest

from lab_commons.dev import floors
from lab_commons.dev.famtests.storedreadings import (
    HISTORICAL_MARKERS,
    MARKER_WINDOW,
    PERCENT,
    NoSpellings,
    StaleReading,
    UndatedHistory,
    assert_history_is_dated,
    assert_stored_readings_are_live,
    assert_the_reader_still_convicts,
    claims_in,
    disagreements,
)

#: The spellings the two labs write between them, measured 2026-09-19 over both rosters' prose: those
#: four keys and nothing else carry a ``key=value`` reading.
_SPELLINGS = frozenset({'own', 'repo', 'project', 'hits', PERCENT})

#: VERBATIM from ``optimi-lab/tests/architecture/_placement.py`` at 2026-09-19. One current reading and
#: one former one, marked the way that author marks it.
_A_REAL_ROW = (
    'MEASURED 2026-09-19: own=21 hits=0, down from own=87, admitted by the binder ceiling. Its '
    '`BELOW_THE_BAR` entry was deleted on 2026-09-18 when its shortfall went away.'
)

#: VERBATIM from ``motronics`` scripts roster at 2026-09-19 -- the DELTA spelling, where the change is
#: an arrow rather than a marker word. Five rows in the family write a reading this way.
_AN_ARROW_ROW = 'MEASURED 2026-09-17 with `measure_density`: own=86 -> 39, ADMITTED on the second.'

#: VERBATIM from ``wdg-lab`` at 2026-09-19 -- two dated readings of the same spelling in one row, the
#: older of which is history by SUPERSESSION and carries no marker word at all.
_A_SUPERSEDED_ROW = 'Measured 2026-09-17: own=103 repo=0. RE-MEASURED 2026-09-18 after the adoption: own=20 repo=0.'


def _derive(_path: str) -> dict[str, float]:
    return {'own': 21.0, 'hits': 0.0, 'repo': 0.0, 'project': 0.0, PERCENT: 0.0}


def test_the_planted_control_convicts_every_shape_the_module_refuses() -> None:
    """The shipped control, run on this repo's own spelling. If this reds, nothing below matters."""
    assert_the_reader_still_convicts(spelling='own')


def test_a_marked_former_reading_is_not_re_derived() -> None:
    """``down from own=87`` is the row's history and must NOT be judged against the live file.

    This is the arm the whole module turns on, and it was earned by the scan that PRODUCED the
    brief this module answers: that sweep took the LAST ``own=`` in each row, which in this very
    sentence is the 87, and convicted a correct row of storing a number it had already retired.
    """
    claims = claims_in(_A_REAL_ROW, spellings=_SPELLINGS)
    live = [claim for claim in claims if not claim.historical]
    assert [(claim.spelling, claim.value) for claim in live] == [('own', 21.0), ('hits', 0.0)]
    former = [claim for claim in claims if claim.historical]
    assert [(claim.spelling, claim.value, claim.why) for claim in former] == [('own', 87.0, 'marker')]
    assert former[0].at == '2026-09-19'


def test_an_arrow_delta_reads_as_both_a_former_and_a_current_number() -> None:
    """``own=86 -> 39`` -- the left half is history, the right half is the claim to re-derive."""
    claims = claims_in(_AN_ARROW_ROW, spellings=_SPELLINGS)
    assert [(claim.value, claim.historical, claim.why) for claim in claims] == [
        (86.0, True, 'arrow'),
        (39.0, False, 'live'),
    ]


def test_an_older_dated_reading_of_the_same_spelling_is_history_without_a_marker_word() -> None:
    """SUPERSESSION. An author who re-measures under a later date has retired the earlier reading."""
    claims = claims_in(_A_SUPERSEDED_ROW, spellings=_SPELLINGS)
    assert [(claim.value, claim.at, claim.why) for claim in claims] == [
        (103.0, '2026-09-17', 'superseded'),
        (0.0, '2026-09-17', 'superseded'),
        (20.0, '2026-09-18', 'live'),
        (0.0, '2026-09-18', 'live'),
    ]


def test_a_marker_too_far_in_front_does_not_excuse_a_live_claim() -> None:
    """The window's OTHER side. A marker is adjacent in every row of the corpus; distance is not a mark."""
    distant = 'down from an earlier shape. ' + 'x' * MARKER_WINDOW + ' MEASURED 2026-09-19: own=99.'
    claims = claims_in(distant, spellings=_SPELLINGS)
    assert [(claim.value, claim.historical) for claim in claims] == [(99.0, False)]


def test_a_percentage_is_read_at_the_precision_its_author_wrote() -> None:
    """``-> 0.00%`` against a live 0.004 agrees; against 0.01 it does not. Not a tolerance -- a reading."""
    rows = {'p': 'MEASURED 2026-09-19: own=21 -> 0.00%.'}

    def close(_path: str) -> dict[str, float]:
        return {'own': 21.0, PERCENT: 0.004}

    def apart(_path: str) -> dict[str, float]:
        return {'own': 21.0, PERCENT: 0.014}

    stale, read = disagreements(rows, spellings=_SPELLINGS, derive=close)
    assert (stale, read) == ({}, 2)
    stale, _ = disagreements(rows, spellings=_SPELLINGS, derive=apart)
    assert set(stale) == {'p'}


def test_a_stored_reading_that_no_longer_derives_is_refused_in_BOTH_directions() -> None:
    """EQUALITY, not ``<=``. A row reading HIGH and a row reading LOW are the same defect."""
    for stored in (14, 30):
        rows = {'tests/architecture/test_memory_lives_under_a_date.py': f'MEASURED 2026-09-19: own={stored} hits=0.'}
        with pytest.raises(StaleReading, match='test_memory_lives_under_a_date'):
            assert_stored_readings_are_live(
                rows, spellings=_SPELLINGS, derive=_derive, floor=1, headroom=8, what='planted'
            )


def test_the_refusal_quotes_the_row_its_date_and_the_live_number() -> None:
    """A refusal a reader cannot act on sends them to re-run the scan by hand."""
    rows = {'a/b.py': 'MEASURED 2026-09-19: own=30 hits=0.'}
    with pytest.raises(StaleReading) as refusal:
        assert_stored_readings_are_live(rows, spellings=_SPELLINGS, derive=_derive, floor=1, headroom=8, what='planted')
    message = str(refusal.value)
    assert "'own=30'" in message
    assert '2026-09-19' in message
    assert 're-derives to 21' in message
    assert HISTORICAL_MARKERS[0] in message


def test_an_agreeing_roster_passes_and_the_count_of_what_was_read_comes_back() -> None:
    """The GREEN half, and the count is the half that separates agreement from an unread corpus."""
    rows = {'a/b.py': _A_REAL_ROW}
    stale, read = disagreements(rows, spellings=_SPELLINGS, derive=_derive)
    assert stale == {}
    assert read == 2
    assert_stored_readings_are_live(rows, spellings=_SPELLINGS, derive=_derive, floor=1, headroom=8, what='planted')


def test_a_corpus_with_nothing_live_in_it_is_refused_rather_than_reported_clean() -> None:
    """THE FLOOR. Finding nothing is what a broken extractor returns and what a fixed roster returns."""
    with pytest.raises(floors.FloorUnmet):
        assert_stored_readings_are_live(
            {'a/b.py': 'no numbers at all here.'},
            spellings=_SPELLINGS,
            derive=_derive,
            floor=4,
            headroom=8,
            what='planted',
        )


def test_a_floor_the_corpus_has_outgrown_is_refused_too() -> None:
    """THE FLOOR'S OTHER SIDE: a number far under the population stops separating anything."""
    rows = {f'a/{index}.py': 'MEASURED 2026-09-19: own=21 hits=0.' for index in range(20)}
    with pytest.raises(floors.SlackFloor):
        assert_stored_readings_are_live(rows, spellings=_SPELLINGS, derive=_derive, floor=1, headroom=2, what='planted')


def test_a_derivation_that_cannot_answer_is_raised_rather_than_read_as_agreement() -> None:
    """The ``except Exception: continue`` that printed ``DISAGREE=0``, refused at its source."""
    rows = {'a/b.py': 'MEASURED 2026-09-19: own=21 project=3.'}
    with pytest.raises(KeyError, match='project'):
        disagreements(rows, spellings=_SPELLINGS, derive=lambda _path: {'own': 21.0})


def test_an_empty_spelling_set_is_refused_rather_than_finding_nothing() -> None:
    """A reader handed no vocabulary reads every roster in the family as clean."""
    with pytest.raises(NoSpellings):
        claims_in(_A_REAL_ROW, spellings=frozenset())
    with pytest.raises(NoSpellings):
        claims_in(_A_REAL_ROW, spellings=frozenset({'  '}))


def test_undated_history_is_refused() -> None:
    """``down from own=87`` with no date anywhere is a two-word amnesty on any number."""
    with pytest.raises(UndatedHistory, match='no date'):
        assert_history_is_dated(
            {'a/b.py': 'own=21 hits=0, down from own=87.'}, spellings=_SPELLINGS, floor=1, what='planted'
        )


def test_a_row_that_keeps_only_history_is_refused() -> None:
    """THE RATCHET'S OTHER SIDE: marking every number former must not buy a pass."""
    with pytest.raises(UndatedHistory, match='only as history'):
        assert_history_is_dated(
            {'a/b.py': 'MEASURED 2026-09-19: down from own=87.'}, spellings=_SPELLINGS, floor=1, what='planted'
        )


def test_a_corpus_that_has_stopped_recording_history_is_refused() -> None:
    """The capability half of the ratchet: a roster with no deltas left passes the live arm vacuously."""
    with pytest.raises(floors.FloorUnmet):
        assert_history_is_dated(
            {'a/b.py': 'MEASURED 2026-09-19: own=21 hits=0.'}, spellings=_SPELLINGS, floor=1, what='planted'
        )


def test_a_well_formed_row_clears_the_history_arm() -> None:
    """The GREEN half of both history arms, over the real corpus row."""
    assert_history_is_dated({'a/b.py': _A_REAL_ROW}, spellings=_SPELLINGS, floor=1, what='planted')


def test_every_arm_names_the_roster_it_refused() -> None:
    """``what`` has no default, and a refusal that does not say WHICH roster drifted misdirects."""
    with pytest.raises(StaleReading, match='the winding roster'):
        assert_stored_readings_are_live(
            {'a/b.py': 'MEASURED 2026-09-19: own=30.'},
            spellings=_SPELLINGS,
            derive=_derive,
            floor=1,
            headroom=8,
            what='winding',
        )
    with pytest.raises(UndatedHistory, match='the winding roster'):
        assert_history_is_dated({'a/b.py': 'own=21, down from own=87.'}, spellings=_SPELLINGS, floor=1, what='winding')
