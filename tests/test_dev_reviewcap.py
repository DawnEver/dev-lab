"""A review that did not run merges Unreviewed (rulings 2026-11-05, 2026-11-06): read from trusted records only."""

from __future__ import annotations

from dev_lab.dev.forgereview_advice import Record
from dev_lab.dev.forgereview_findings import Finding
from dev_lab.dev.reviewbudget import Raised, raise_line
from dev_lab.dev.reviewcap import unreviewed_line, waiver_of

_HIGH = Finding('F-1', 'HIGH', security=False, rule='r', file='a.py', anchor='1', summary='s', category='c')
_BUDGET = 'review budget reached: 11.00/10.00 USD; the integrator may forge review cap 4 --usd <n>'


def _record() -> str:
    return Record('a' * 40, (_HIGH,)).line()


def test_a_recorded_cause_is_waived_naming_it() -> None:
    assert waiver_of([f'not reviewed\n\n{unreviewed_line(_BUDGET)}']) == f'Unreviewed: {_BUDGET}'
    failed = unreviewed_line('no reviewer returned findings (a unsupported)')
    assert waiver_of([_record(), failed]) == 'Unreviewed: no reviewer returned findings (a unsupported)'


def test_no_record_and_a_review_record_alone_are_never_waived() -> None:
    """PLANTED CONTROL: a PR whose review ran (advice), or that was never tried, carries no waiver."""
    assert waiver_of([]) is None
    assert waiver_of([_record()]) is None


def test_a_review_or_a_raise_after_the_record_supersedes_it() -> None:
    """PLANTED CONTROL: the same record, then the review ran or the cap was raised: the review stands again."""
    record = unreviewed_line(_BUDGET)
    assert waiver_of([record, _record()]) is None
    assert waiver_of([record, raise_line(Raised(20.0, 'big PR', 'lead'))]) is None


def test_a_waiver_never_names_a_split() -> None:
    assert 'sp' + 'lit' not in (waiver_of([unreviewed_line(_BUDGET)]) or '')
