"""A capped review warns and merges (ruling 2026-11-05): the waiver is read from trusted ledgers, not a status."""

from __future__ import annotations

from dev_lab.dev.forgereview_findings import Finding
from dev_lab.dev.forgereview_rounds import Ledger
from dev_lab.dev.reviewbudget import Raised, raise_line
from dev_lab.dev.reviewcap import capped_line, waiver_of

_HIGH = Finding('F-1', 'HIGH', security=False, rule='r', file='a.py', anchor='1', summary='s', category='c')


def _ledger(round_: int) -> str:
    return Ledger('a' * 40, round_, (_HIGH,)).line()


def test_a_ledger_at_the_cap_is_waived_naming_the_cap_and_its_open_findings() -> None:
    assert waiver_of([_ledger(3)], max_rounds=3) == 'Unreviewed: review capped at 3 rounds; open findings: F-1'


def test_a_ledger_below_the_cap_and_no_ledger_are_never_waived() -> None:
    """PLANTED CONTROL: the same ledger one round short, and a PR never reviewed, wait for the review."""
    assert waiver_of([_ledger(2)], max_rounds=3) is None
    assert waiver_of([], max_rounds=3) is None


def test_a_trusted_raise_moves_the_cap() -> None:
    raised = raise_line(Raised(None, 5, 'big PR', 'lead'))
    assert waiver_of([_ledger(3), raised], max_rounds=3) is None
    assert waiver_of([_ledger(5), raised], max_rounds=3) is not None


_BUDGET = 'budget reached: 11.00/10.00 USD; split the PR, or forge review cap 4 --usd <n>'


def test_a_recorded_dollar_cap_is_waived_naming_the_budget() -> None:
    """User ruling 2026-11-05: the dollar cap no longer blocks; the reviewing host's record names it."""
    said = waiver_of([_ledger(1), f'stopped\n\n{capped_line(_BUDGET)}'], max_rounds=3)
    assert said == 'Unreviewed: review budget reached: 11.00/10.00 USD; open findings: F-1'
    assert waiver_of([capped_line(_BUDGET)], max_rounds=3) == (
        'Unreviewed: review budget reached: 11.00/10.00 USD; open findings: none'
    )


def test_a_ledger_or_raise_after_the_record_supersedes_it() -> None:
    """PLANTED CONTROL: the same record, then a round ran again or the cap was raised: the review is back on."""
    record = capped_line(_BUDGET)
    assert waiver_of([record, _ledger(1)], max_rounds=3) is None
    assert waiver_of([record, raise_line(Raised(20.0, None, 'big PR', 'lead'))], max_rounds=3) is None
    assert waiver_of([_ledger(1)], max_rounds=3) is None
