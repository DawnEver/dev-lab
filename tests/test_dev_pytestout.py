r"""THE TRANSCRIPT READERS, DRIVEN BY REAL PYTEST TRANSCRIPTS AND BY A REAL PYTEST RUN.

EVERY ARM PLANTS THE THING IT CLAIMS TO CATCH, and the two arms that matter most plant the SHAPES
the two forks of this reader disagreed on before they were merged -- because a reader written from
one repo's transcripts is a reader that has only seen one repo's incidents:

* :func:`test_an_interrupt_banner_is_not_a_summary_line` plants
  ``!!! Interrupted: 3 errors during collection !!!``, which the unanchored fork read as a summary
  saying three errors. It is the only arm that would have failed against the code this module
  replaced in this package, and it is what the anchor is for.
* :func:`test_a_cursor_motion_escape_is_stripped_and_a_bare_esc_survives` plants an erase-line
  sequence, which the narrow ``[0-9;]*m`` fork left in the text while reporting it had cleaned it,
  and a LONE ``ESC``, which a greedy pattern would have eaten along with the content after it.

THE FLOOR IS ASSERTED ON EVERY READER RATHER THAN DESCRIBED: a transcript with no summary, no
collection line and no marker answers ``None``/``None``/``()``, and each of those is checked to be
DISTINGUISHABLE from the zero-shaped reading a completed-but-empty run gives. That distinction is
the whole subject -- ``0 collected`` is a run that found nothing, ``None`` is a run that never said.

THE LAST ARM RUNS PYTEST. Every other arm is a string constant, which measures this file's author
against this file's code; :func:`test_a_real_pytest_subprocess_is_read_by_every_reader` spawns a
real interpreter over a real two-test file and asserts the readers against what it actually printed,
so a grammar that drifts from pytest's own output has somewhere to fail.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from lab_commons.dev.floors import assert_floor
from lab_commons.dev.pytestout import (
    TRUNCATION_MARKERS,
    collected_count,
    markers_in,
    strip_ansi,
    summary_body,
    summary_counts,
)

#: A complete, ordinary run: a collection line, per-file progress, and a decorated summary rule.
COMPLETE = (
    'collected 7 items\n'
    '\n'
    'tests/test_a.py ....                        [ 57%]\n'
    'tests/test_b.py ..F                         [100%]\n'
    '\n'
    'FAILED tests/test_b.py::test_c - assert 0\n'
    '===================== 1 failed, 6 passed in 3.21s =====================\n'
)

#: The conftest incident, 2026-09-02, in the shape it actually arrived in: the suite exits having
#: printed neither a summary nor a collection line. Every reader must answer an ABSENCE here.
NO_SUMMARY = (
    "ImportError while loading conftest 'tests/conftest.py'.\nModuleNotFoundError: No module named 'motronics'\n"
)

#: A run that finished over an EMPTY selection. It is the reading ``NO_SUMMARY`` must never be
#: confused with: the remedies are opposite -- widen the selection vs. fix the interpreter.
EMPTY_BUT_COMPLETE = 'collected 0 items\n\n========================= no tests ran in 0.01s =========================\n'

#: THE MINIMUM NUMBER OF MARKERS the vocabulary must hold to be a vocabulary. Eight live today; the
#: floor is below that with room for one retirement, and a fork that arrived with only the two this
#: package knew before the merge (``INTERNALERROR`` and an interrupt banner) fails it.
MARKER_FLOOR = 6


def test_the_marker_vocabulary_is_a_population_and_not_a_pair() -> None:
    """THE FLOOR ON THE DATA. A two-entry vocabulary reads exactly like an eight-entry clean scan."""
    assert_floor(len(TRUNCATION_MARKERS), floor=MARKER_FLOOR, what='pytest truncation markers')
    assert len(set(TRUNCATION_MARKERS)) == len(TRUNCATION_MARKERS), TRUNCATION_MARKERS


def test_a_complete_run_reads_as_its_own_numbers() -> None:
    """The positive side: every reader answers, and the numbers are pytest's own."""
    assert collected_count(COMPLETE) == 7
    assert summary_body(COMPLETE) == '1 failed, 6 passed in 3.21s'
    assert summary_counts(COMPLETE) == {'failed': 1, 'passed': 6}
    assert markers_in(COMPLETE) == ()


def test_a_transcript_with_no_summary_answers_an_ABSENCE_and_never_a_zero() -> None:
    """THE FLOOR, PLANTED. ``None`` is not ``0`` and the two readings have opposite remedies."""
    assert collected_count(NO_SUMMARY) is None
    assert summary_body(NO_SUMMARY) is None
    assert summary_counts(NO_SUMMARY) is None

    assert collected_count(EMPTY_BUT_COMPLETE) == 0
    assert summary_counts(EMPTY_BUT_COMPLETE) is None
    assert collected_count(NO_SUMMARY) != collected_count(EMPTY_BUT_COMPLETE)


def test_the_conftest_failure_is_NAMED_rather_than_left_as_a_silent_absence() -> None:
    """The marker is what turns "no summary" into the one fact that fixes it."""
    assert markers_in(NO_SUMMARY) == ('ImportError while loading conftest',)
    assert markers_in(EMPTY_BUT_COMPLETE) == ()


def test_an_interrupt_banner_is_not_a_summary_line() -> None:
    """THE CONTROL THE ANCHOR EXISTS FOR, and the one arm the unanchored fork failed.

    ``3 errors during collection`` carries the ``<count> <word>`` shape on a line that is not a
    summary. A reader that takes the last such line reports three errors for a run that printed no
    summary at all -- a NUMBER where the truth is an absence.
    """
    interrupted = 'collected 12 items\n!!!!! Interrupted: 3 errors during collection !!!!!\n'
    assert summary_body(interrupted) is None
    assert summary_counts(interrupted) is None
    assert collected_count(interrupted) == 12


def test_an_all_xfail_summary_is_not_read_as_a_truncated_run() -> None:
    """The 2026-08-29 incident: six outcome words the line pattern did not know."""
    for body in ('20 xfailed in 80.40s', '4 skipped in 0.10s', '2 xpassed, 1 deselected in 0.30s'):
        text = f'collected 20 items\n==================== {body} ====================\n'
        assert summary_body(text) == body, body
        assert summary_counts(text) is not None, body


def test_a_nested_runs_summary_never_answers_for_the_outer_one() -> None:
    """LAST for the summary, FIRST for the collection -- both ends of the same bracket, planted."""
    nested = (
        'collected 340 items\n'
        '----------------------------- Captured stdout -----------------------------\n'
        'collected 2 items\n'
        '========================= 2 passed in 0.01s =========================\n'
        '========================= 339 passed, 1 failed in 91.2s =========================\n'
    )
    assert summary_body(nested) == '339 passed, 1 failed in 91.2s'
    assert collected_count(nested) == 340


def test_a_cursor_motion_escape_is_stripped_and_a_bare_esc_survives() -> None:
    """BOTH SIDES OF THE ESCAPE GRAMMAR, and the narrow fork fails the first half."""
    coloured = '\x1b[31mFAILED\x1b[0m tests/test_b.py::\x1b[1mtest_c\x1b[0m - assert 0'
    assert strip_ansi(coloured) == 'FAILED tests/test_b.py::test_c - assert 0'

    erase_line = '\x1b[2Kcollected 5 items'
    assert strip_ansi(erase_line) == 'collected 5 items'
    assert collected_count(erase_line) is None, 'the pattern is anchored, so the strip must come first'
    assert collected_count(strip_ansi(erase_line)) == 5

    lone = 'a bare \x1b and an \x1b] that is not CSI'
    assert strip_ansi(lone) == lone


def test_a_coloured_summary_rule_reads_as_no_summary_until_it_is_stripped() -> None:
    """Why the strip is a reader on this page and not the caller's business."""
    coloured = '\x1b[32m===================== 3 passed in 1.00s =====================\x1b[0m\n'
    assert summary_body(coloured) is None
    assert summary_body(strip_ansi(coloured)) == '3 passed in 1.00s'


def test_a_marker_a_TEST_printed_is_not_a_marker_the_RUN_reported() -> None:
    """THE COLUMN RULE, PLANTED BOTH WAYS on the same marker in the same text."""
    echoed = "    assert 'node down' not in transcript\nE   AssertionError: node down\n"
    assert markers_in(echoed) == ()
    assert markers_in(echoed + '[gw3] node down: Not properly terminated\n') == ('node down', 'Not properly terminated')


def test_the_readers_are_pure_and_a_text_is_never_mutated() -> None:
    """A reading that changed its subject would make the CITED log a different text from the JUDGED one."""
    before = COMPLETE
    for reader in (collected_count, summary_body, summary_counts, markers_in, strip_ansi):
        reader(COMPLETE)
    assert before == COMPLETE


@pytest.mark.parametrize('flag', ['--color=yes', '--color=no'])
def test_a_real_pytest_subprocess_is_read_by_every_reader(tmp_path: Path, flag: str) -> None:
    """THE ONE ARM THAT IS NOT A STRING CONSTANT: real pytest, both colour modes, read end to end.

    A grammar checked only against fixtures its own author typed agrees with its author. This spawns
    a real interpreter over a real two-test file, one passing and one failing, and asserts the
    readers against what pytest ACTUALLY printed -- which is the only thing that can catch the
    grammar drifting away from the tool that writes it.
    """
    (tmp_path / 'test_planted.py').write_text(
        'def test_green() -> None:\n    assert True\n\n\ndef test_red() -> None:\n    assert False\n',
        encoding='utf-8',
    )
    run = subprocess.run(
        [sys.executable, '-m', 'pytest', '-p', 'no:cacheprovider', '-p', 'no:xdist', flag, str(tmp_path)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )
    plain = strip_ansi(run.stdout)
    assert collected_count(plain) == 2, run.stdout
    counts = summary_counts(plain)
    assert counts is not None, run.stdout
    assert counts.get('passed') == 1, counts
    assert counts.get('failed') == 1, counts
    assert markers_in(plain) == (), run.stdout
