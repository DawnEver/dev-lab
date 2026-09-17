"""The shared always-loaded-pages body: both readings, all four movements, and a real planted tree.

The consumer-side control for :mod:`lab_commons.dev.famtests.rulespages`. What is checked here is
that the body SEES each movement, since the argument for replacing a bare total with a named set is
worth exactly as much as the evidence that the named set catches what the total missed -- so the
central case below plants a page that GROWS while a sibling SHRINKS by the same amount, which is the
edit a total reports as clean.

PLANTED ON DISK, not as dictionaries. The scan, the naming and the comparison are one mechanism from
a caller's side; a control that hands :func:`~lab_commons.dev.famtests.rulespages.ratchet_breaks` a
literal never finds out whether the reading that feeds it counts lines the same way.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lab_commons.dev.famtests.rulespages import (
    VacuousPageScan,
    assert_rules_ratchet,
    budget_overrun,
    page_lines,
    ratchet_breaks,
)


def _plant(root: Path, **pages: int) -> tuple[Path, ...]:
    """Write each named page with that many lines under *root*, and return them in sorted order."""
    for name, lines in pages.items():
        path = root / f'{name}.md'
        path.write_text('- a hard constraint.\n' * lines, encoding='utf-8')
    return tuple(sorted(root.glob('*.md')))


def test_the_reading_counts_lines_and_names_pages_relative_to_the_root(tmp_path: Path) -> None:
    """THE SCAN, and an empty page and an unread one must not be the same answer."""
    nested = tmp_path / 'rem'
    nested.mkdir()
    (tmp_path / 'one.md').write_text('a\nb\nc\n', encoding='utf-8')
    (nested / 'two.md').write_text('', encoding='utf-8')
    pages = (tmp_path / 'one.md', nested / 'two.md')
    assert page_lines(pages, root=tmp_path) == {'one.md': 3, 'rem/two.md': 0}


def test_a_page_that_grows_inside_a_siblings_shrink_is_refused(tmp_path: Path) -> None:
    """THE WHOLE ARGUMENT FOR THE SWAP, planted: the edit a total ceiling reports as clean.

    One page gains five lines, the other loses five. The sum is unchanged -- a bare total is silent
    -- and both halves are named here, because the budget freed by a shrink is paid back rather than
    lent to the page beside it.
    """
    pinned = {'a.md': 20, 'b.md': 20}
    pages = _plant(tmp_path, a=25, b=15)
    measured = page_lines(pages, root=tmp_path)
    assert sum(measured.values()) == sum(pinned.values()), 'the plant must leave the TOTAL untouched'
    assert budget_overrun(measured, ceiling=40) is None, 'so a total ceiling sees nothing here'
    breaks = ratchet_breaks(measured, pinned=pinned)
    assert 'grew 20 -> 25' in breaks['a.md']
    assert 'shrank 20 -> 15' in breaks['b.md']


def test_a_page_that_arrives_and_a_pin_left_behind_are_both_refused(tmp_path: Path) -> None:
    """THE TWO SIDES THAT GO MISSING: an unbudgeted arrival, and a waiver outliving its page."""
    pinned = {'a.md': 10, 'b.md': 10}
    measured = page_lines(_plant(tmp_path, a=10, b=10, c=7), root=tmp_path)
    assert 'unpinned' in ratchet_breaks(measured, pinned=pinned)['c.md']
    assert ratchet_breaks({'a.md': 10}, pinned=pinned)['b.md'].startswith('pinned and gone')
    assert ratchet_breaks({'a.md': 10, 'b.md': 10}, pinned=pinned) == {}, 'the clean case must be silent'


def test_the_total_ceiling_sees_what_the_named_set_cannot(tmp_path: Path) -> None:
    """THE OTHER HALF. Every page inside its own pin, and the document is still too big.

    Three arrivals, each pinned at a size nobody would argue with, summing past a budget nobody
    decided to spend. A per-page ratchet alone reports this clean, which is why both are kept.
    """
    pages = _plant(tmp_path, a=30, b=30, c=30)
    measured = page_lines(pages, root=tmp_path)
    pinned = dict.fromkeys(measured, 30)
    assert ratchet_breaks(measured, pinned=pinned) == {}, 'every page is exactly at its pin'
    overrun = budget_overrun(measured, ceiling=60)
    assert overrun is not None, 'three 30-line pages are 90 lines, and the ceiling is 60'
    assert '90 lines of always-loaded rules across 3 page(s)' in overrun


def test_the_floor_refuses_a_scan_that_read_nothing(tmp_path: Path) -> None:
    """A ratchet over a directory the walk did not enter reports what a compressed one reports."""
    with pytest.raises(VacuousPageScan, match='below the 2 floor'):
        assert_rules_ratchet(pages=(), root=tmp_path, pinned={}, ceiling=60, floor=2)


def test_the_assembled_check_passes_only_when_both_readings_agree(tmp_path: Path) -> None:
    """THE CALLER'S ENTRY POINT: clean once, then each reading is made to fail on its own."""
    pages = _plant(tmp_path, a=20, b=20)
    pinned = {'a.md': 20, 'b.md': 20}
    assert assert_rules_ratchet(pages=pages, root=tmp_path, pinned=pinned, ceiling=40, floor=2) == pinned
    with pytest.raises(AssertionError, match='the always-loaded rule set moved'):
        assert_rules_ratchet(pages=pages, root=tmp_path, pinned={'a.md': 20}, ceiling=40, floor=2)
    with pytest.raises(AssertionError, match='above the 39 ceiling'):
        assert_rules_ratchet(pages=pages, root=tmp_path, pinned=pinned, ceiling=39, floor=2)
