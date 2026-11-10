"""A hosted review runs under the base's declared month, its spend charged to the forge's shared ledger.

Every test plants its control: the same PR with the one fact flipped behaves the other way.
"""

from __future__ import annotations

import dataclasses
import os
import tomllib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from _forge_state import StateForge
from _review_doubles import _state
from test_dev_forgereview import _DECLARED, FakeCommand, _can, _forge, _work

from dev_lab.dev.forgereview import review_tick
from dev_lab.dev.forgereview_advice import trusted_bodies
from dev_lab.dev.forgereview_claim import UNREVIEWED_STATUS
from dev_lab.dev.forgereview_declared import review_from
from dev_lab.dev.reviewbudget import NO_REVIEW_ALLOTMENT, Month, NoReviewAllotment, Spend
from dev_lab.dev.reviewcap import UNREVIEWED, waiver_of
from dev_lab.dev.reviewledger import (
    HELD_ELSEWHERE,
    HOLD,
    LEDGER_UNREAD,
    SPENT,
    Entry,
    derived_config,
    hold,
    month_key,
    spend_of,
)

_NOW = datetime(2026, 11, 10, 12, tzinfo=UTC)
_MONTH = Month('anthropic', 100.0)


class MemoryLedger:
    """The forge ledger's contract in memory: ids monotonic, like forge asset ids."""

    def __init__(self, entries: tuple[Entry, ...] = ()) -> None:  # noqa: D107
        self.held: list[Entry] = list(entries)
        self.next = max((one.id for one in entries), default=0) + 1

    def entries(self) -> tuple[Entry, ...]:
        return tuple(self.held)

    def append(self, entry: Entry) -> Entry:
        stored = dataclasses.replace(entry, id=self.next)
        self.next += 1
        self.held.append(stored)
        return stored

    def withdraw(self, entry: Entry) -> None:
        self.held = [one for one in self.held if one.id != entry.id]


class Broken(MemoryLedger):
    def entries(self) -> tuple[Entry, ...]:
        msg = 'the records home did not answer'
        raise OSError(msg)


def _hosted_ai_lab(spent_after: float) -> Callable[..., Spend]:
    """A hosted runner's ai-lab: no review allotment until the derived machine file is pointed at, then its spend."""

    def spend(*_: object) -> Spend:
        if 'LAB_COMMONS_CONFIG' not in os.environ:
            raise NoReviewAllotment(NO_REVIEW_ALLOTMENT)
        return Spend(budget_usd=0.0, spent_usd=spent_after)

    return spend


def _tick(
    work: Path, forge: StateForge, *, month: Month | None, ledger: MemoryLedger, hosted: bool = True,
    spent_after: float = 0.5,
) -> tuple[FakeCommand, tuple[str, ...]]:  # fmt: skip
    command = FakeCommand()
    review = dataclasses.replace(_DECLARED, month=month)
    lines = review_tick(work, forge, review, base='integrate/main', run=command, ready=_can, host='job',
                        clock=lambda: _NOW, spend=_hosted_ai_lab(spent_after), ledger=lambda _client: ledger,
                        hosted=lambda: hosted)  # fmt: skip
    return command, lines


@pytest.fixture(autouse=True)
def _no_machine_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv('LAB_COMMONS_CONFIG', raising=False)
    monkeypatch.setenv('RUNNER_TEMP', str(tmp_path))


def test_a_declared_month_and_an_empty_ledger_run_the_hosted_review_and_charge_the_forge(tmp_path: Path) -> None:
    """The review runs, holds its cap, then settles at what ai-lab reported. PLANTED CONTROL: no declaration skips."""
    work, head = _work(tmp_path)
    forge, _ = _forge(head)
    ledger = MemoryLedger()
    command, lines = _tick(work, forge, month=_MONTH, ledger=ledger, spent_after=0.5)
    assert command.ran != [], lines
    kinds = [(one.kind, one.usd) for one in ledger.held]
    assert kinds == [(HOLD, 1.0), (SPENT, 0.5)], 'the initial cap is month/100, settled at the run spend'
    assert 'LAB_COMMONS_CONFIG' not in os.environ, 'the derived machine file is the run scope alone'
    (tmp_path / 'control').mkdir()
    work, head = _work(tmp_path / 'control')
    forge, number = _forge(head)
    command, _ = _tick(work, forge, month=None, ledger=(untouched := MemoryLedger()))
    assert command.ran == []
    assert untouched.held == []
    assert waiver_of(trusted_bodies(forge, number)) == f'{UNREVIEWED}: review skipped: {NO_REVIEW_ALLOTMENT}'


def test_a_ledger_at_the_month_skips_the_hosted_review_named(tmp_path: Path) -> None:
    """The forge ledger is the month's spend: at the amount nothing runs. PLANTED CONTROL: one cent under runs."""
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    full = MemoryLedger((Entry(month_key(_NOW), 7, 'a1', HOLD, 100.0, 1),))
    command, _ = _tick(work, forge, month=_MONTH, ledger=full)
    assert command.ran == []
    assert 'monthly review budget spent: 100.00/100.00 USD' in _state(forge, head)[1]
    assert (waiver_of(trusted_bodies(forge, number)) or '').startswith(f'{UNREVIEWED}: review monthly')
    assert len(full.held) == 1, 'a skipped review holds nothing'
    (tmp_path / 'control').mkdir()
    work, head = _work(tmp_path / 'control')
    forge, _ = _forge(head)
    last_month = Entry('2026-10', 7, 'b2', HOLD, 100.0, 2)
    command, _ = _tick(work, forge, month=_MONTH, ledger=MemoryLedger((last_month,)))
    assert command.ran != [], "last month's charge is not this month's"


def test_a_host_with_a_machine_file_keeps_its_own_allotment_even_with_a_declared_month(tmp_path: Path) -> None:
    """The judge's path is unchanged: a host with a machine file never reads the declared month, nor the ledger.

    PLANTED CONTROL: the same declaration on a host with no machine file runs the review.
    """
    work, head = _work(tmp_path)
    forge, _ = _forge(head)
    ledger = MemoryLedger()
    command, _ = _tick(work, forge, month=_MONTH, ledger=ledger, hosted=False)
    assert command.ran == []
    assert ledger.held == []
    assert _state(forge, head) == ('pending', f'{UNREVIEWED_STATUS} review skipped: {NO_REVIEW_ALLOTMENT}')
    (tmp_path / 'control').mkdir()
    work, head = _work(tmp_path / 'control')
    forge, _ = _forge(head)
    command, _ = _tick(work, forge, month=_MONTH, ledger=MemoryLedger(), hosted=True)
    assert command.ran != []


def test_an_unreadable_ledger_skips_named_and_runs_nothing(tmp_path: Path) -> None:
    """No ledger, no hold, no run: the race bound would not hold. PLANTED CONTROL: a readable ledger runs (above)."""
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    command, _ = _tick(work, forge, month=_MONTH, ledger=Broken())
    assert command.ran == []
    assert LEDGER_UNREAD in (waiver_of(trusted_bodies(forge, number)) or '')


def test_two_racing_holds_never_both_pass_a_month_that_holds_one() -> None:
    """THE RACE BOUND: A has appended its hold but not yet re-read when B holds; B sees A's older hold and withdraws.

    A's own re-read counts only holds no newer than its own, so A is admitted whatever B did: of the two, exactly
    the older runs. PLANTED CONTROL: a month that holds both admits B too.
    """
    for amount, b_admitted in ((15.0, False), (20.0, True)):
        ledger = MemoryLedger()
        ledger.append(Entry(month_key(_NOW), 1, 'aa', HOLD, 10.0))  # A, mid-hold
        second = hold(ledger, Month('anthropic', amount), number=2, usd=10.0, now=_NOW)
        assert (second is not None) == b_admitted
        assert sum(one.usd for one in ledger.held) <= amount, 'the admitted holds fit the month'
        assert len(ledger.held) == (2 if b_admitted else 1), 'a refused hold is withdrawn'


def test_a_settled_run_charges_its_spend_not_its_hold() -> None:
    month = month_key(_NOW)
    entries = (Entry(month, 3, 'aa', HOLD, 10.0, 1), Entry(month, 3, 'aa', SPENT, 2.5, 2),
               Entry(month, 4, 'bb', HOLD, 10.0, 3))  # fmt: skip
    spend = spend_of(_MONTH, entries, now=_NOW, repo_tag='o/r')
    assert spend.spent_usd == 12.5
    assert spend.of('o/r#3') == 2.5
    assert spend.provider == 'anthropic'


def test_an_entry_name_round_trips_and_other_files_are_not_entries() -> None:
    one = Entry('2026-11', 12, 'deadbeef', HOLD, 1.25, 9)
    assert Entry.parse(one.name, 9) == one
    assert Entry.parse('run-' + '0' * 40 + '-unit-x.json.gz', 1) is None


def test_the_derived_machine_file_allots_the_review_what_the_month_has_left() -> None:
    doc = tomllib.loads(derived_config(_MONTH, 42.5))
    assert doc['ai_lab']['spend_cap']['anthropic'] == {'amount': 42.5, 'currency': 'USD'}
    assert doc['ai_lab']['standing']['review'] == {'provider': 'anthropic', 'amount': 42.5, 'currency': 'USD'}


def test_the_month_is_declared_once_in_the_review_table_and_a_bad_one_is_refused() -> None:
    """Undeclared is ``None`` (today's behaviour); a declared one parses. PLANTED CONTROLS: each malformed shape."""
    assert review_from('', 'x').month is None
    text = '[tool.dev_lab.review]\nmonth = { provider = "anthropic", amount = 100, currency = "USD" }\n'
    assert review_from(text, 'x').month == Month('anthropic', 100)
    for bad in ('{ provider = "anthropic", amount = 100, currency = "CNY" }', '{ provider = "", amount = 1 }',
                '{ provider = "anthropic", amount = -1 }', '{ provider = "anthropic" }', '100',
                '{ provider = "anthropic", amount = 1, usd = 1 }'):  # fmt: skip
        with pytest.raises(ValueError, match='month'):
            review_from(f'[tool.dev_lab.review]\nmonth = {bad}\n', 'x')


def test_a_concurrent_hold_names_why_the_review_skipped() -> None:
    assert 'concurrent' in HELD_ELSEWHERE
