"""The journal, which was the one thing in the package that grew with uptime."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev_lab.supervise import cli


def _lines(path: Path) -> list[str]:
    """Return the journal's non-empty lines."""
    return [line for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def test_a_small_journal_is_only_appended_to(tmp_path: Path) -> None:
    """The ordinary case: nothing is rewritten, so nothing can be lost by a rewrite."""
    journal = tmp_path / 'cycles.jsonl'
    for number in range(5):
        cli._append_bounded(journal, json.dumps({'n': number}) + '\n')
    assert [json.loads(line)['n'] for line in _lines(journal)] == [0, 1, 2, 3, 4]


def test_a_journal_past_its_ceiling_keeps_the_newest_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """THE POINT OF THE CEILING: one record per cycle, forever, is unbounded by construction.

    Measured at a five-minute interval that is about 2 MB a month -- small on a 40 GB disk and
    unbounded all the same. The state module's docstring names its predecessor's growing log ring
    as one of the defects this package exists to fix; this file had no ring at all, and
    `_read_journal` reads it whole, so it was also an unbounded allocation in the daily digest on a
    host whose entire discipline is about what a process may allocate.

    The ceilings are moved down rather than writing four megabytes to prove it. What is asserted is
    the invariant rather than a survivor list: the file is bounded, and the record that survived is
    the NEWEST one. A trim that kept the oldest records would bound the file just as well and lose
    everything a digest is ever asked about.
    """
    ceiling, keep = 200, 3
    monkeypatch.setattr(cli, 'JOURNAL_MAX_BYTES', ceiling)
    monkeypatch.setattr(cli, 'JOURNAL_KEPT', keep)
    journal = tmp_path / 'cycles.jsonl'
    for number in range(50):
        cli._append_bounded(journal, json.dumps({'n': number}) + '\n')
    kept = [json.loads(line)['n'] for line in _lines(journal)]
    assert kept[-1] == 49, 'the newest record is the one a digest is asked about'
    assert len(kept) < 50, 'nothing was trimmed at all'
    one_line = len(json.dumps({'n': 49})) + 1
    assert journal.stat().st_size <= ceiling + one_line, 'the file is bounded by its ceiling'


def test_a_half_written_line_is_skipped_rather_than_fatal(tmp_path: Path) -> None:
    """A LOG THAT CANNOT BE PARSED IN FULL IS STILL MOSTLY TRUE.

    The digest is a convenience built on a log, and refusing to read any of it because one line was
    caught mid-write would be the wrong trade.
    """
    journal = tmp_path / 'cycles.jsonl'
    journal.write_text('{"n": 1}\nnot json\n{"n": 2}\n', encoding='utf-8')
    assert [entry['n'] for entry in cli._read_journal(journal)] == [1, 2]


def test_a_missing_journal_reads_as_nothing(tmp_path: Path) -> None:
    """A digest before any cycle has run is an empty summary, not an error."""
    assert cli._read_journal(tmp_path / 'absent.jsonl') == []
