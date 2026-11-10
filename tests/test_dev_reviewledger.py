"""The family's ONE review month, charged by every reviewer -- the judge and every runner -- to ONE ledger.

Every test plants its control: the same PR with the one fact flipped behaves the other way.
"""

from __future__ import annotations

import dataclasses
import json
import os
import tomllib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from _forge_state import StateForge
from _review_doubles import _state
from test_dev_forgereview import _DECLARED, FakeCommand, _can, _forge, _work

from dev_lab.dev import forgesecrets
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgereview import review_tick
from dev_lab.dev.forgereview_advice import trusted_bodies
from dev_lab.dev.forgereview_declared import review_from
from dev_lab.dev.forgesecrets import Target
from dev_lab.dev.reviewbudget import NO_REVIEW_ALLOTMENT, Month, NoReviewAllotment, Spend
from dev_lab.dev.reviewcap import UNREVIEWED, waiver_of
from dev_lab.dev.reviewledger import (
    HELD_ELSEWHERE,
    HOLD,
    LEDGER_TOKEN,
    LEDGER_UNREAD,
    MONTH_VAR,
    NO_LEDGER_TOKEN,
    SPENT,
    Entry,
    FamilyMonth,
    declared_month,
    derived_config,
    forge_ledger,
    hold,
    month_here,
    month_key,
    spend_of,
)

_NOW = datetime(2026, 11, 10, 12, tzinfo=UTC)
_LEDGER_URL = 'https://github.com/example-org/records'
_MONTH = Month('anthropic', 100.0)
_FAMILY = FamilyMonth(_MONTH, _LEDGER_URL)
_TOKEN = 'github_pat_planted-ledger-token'  # noqa: S105 -- a planted control value


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


def _ai_lab(spent_after: float, *, judge: bool = False) -> Callable[..., Spend]:
    """A runner's ai-lab (no allotment until the derived file is pointed at), or the judge's (its month to date).

    The first read inside the run is its start; every later one has the run's *spent_after* on top.
    """
    reads: list[int] = []

    def spend(*_: object) -> Spend:
        if not judge and 'LAB_COMMONS_CONFIG' not in os.environ:
            raise NoReviewAllotment(NO_REVIEW_ALLOTMENT)
        reads.append(1)
        base = 40.0 if judge else 0.0
        return Spend(budget_usd=0.0, spent_usd=base + (spent_after if len(reads) > 1 else 0.0))

    return spend


def _tick(
    work: Path, forge: StateForge, *, family: FamilyMonth | None, ledger: MemoryLedger, hosted: bool = True,
    spent_after: float = 0.5, run: Callable[..., str] | None = None,
) -> tuple[FakeCommand, tuple[str, ...]]:  # fmt: skip
    command = FakeCommand()
    lines = review_tick(work, forge, _DECLARED, base='integrate/main', run=run or command, ready=_can, host='job',
                        clock=lambda: _NOW, spend=_ai_lab(spent_after, judge=not hosted), month=lambda: family,
                        ledger=lambda _family: ledger, hosted=lambda: hosted)  # fmt: skip
    return command, lines


@pytest.fixture(autouse=True)
def _no_machine_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv('LAB_COMMONS_CONFIG', raising=False)
    monkeypatch.delenv(LEDGER_TOKEN, raising=False)
    monkeypatch.setenv('RUNNER_TEMP', str(tmp_path))


def _fresh(tmp_path: Path, name: str) -> tuple[Path, StateForge, int, str]:
    (tmp_path / name).mkdir()
    work, head = _work(tmp_path / name)
    forge, number = _forge(head)
    return work, forge, number, head


def test_a_runner_with_the_family_month_reviews_and_charges_the_one_ledger(tmp_path: Path) -> None:
    """The review holds its cap, then settles at what ai-lab reported. PLANTED CONTROL: no variable skips, named."""
    work, forge, _, _ = _fresh(tmp_path, 'a')
    ledger = MemoryLedger()
    command, lines = _tick(work, forge, family=_FAMILY, ledger=ledger, spent_after=0.5)
    assert command.ran != [], lines
    assert [(one.kind, one.usd, one.tag) for one in ledger.held] == [(HOLD, 1.0, 'o/r#1'), (SPENT, 0.5, 'o/r#1')]
    assert 'LAB_COMMONS_CONFIG' not in os.environ, 'the derived machine file is the run scope alone'
    work, forge, number, _ = _fresh(tmp_path, 'control')
    command, _ = _tick(work, forge, family=None, ledger=(untouched := MemoryLedger()))
    assert command.ran == []
    assert untouched.held == []
    assert waiver_of(trusted_bodies(forge, number)) == f'{UNREVIEWED}: review skipped: {NO_REVIEW_ALLOTMENT}'


def test_two_repos_draw_on_one_month(tmp_path: Path) -> None:
    """Another repo's charge on the ONE ledger is this repo's month too: at the amount nothing runs.

    PLANTED CONTROLS: the same charge last month runs; and a second repo's hold sees the first's and withdraws.
    """
    work, forge, number, head = _fresh(tmp_path, 'a')
    other = Entry(month_key(_NOW), 'p/q', 7, 'a1', HOLD, 100.0, 1)
    full = MemoryLedger((other,))
    command, _ = _tick(work, forge, family=_FAMILY, ledger=full)
    assert command.ran == []
    assert 'monthly review budget spent: 100.00/100.00 USD' in _state(forge, head)[1]
    assert (waiver_of(trusted_bodies(forge, number)) or '').startswith(f'{UNREVIEWED}: review monthly')
    assert full.held == [other], 'a skipped review holds nothing'
    work, forge, _, _ = _fresh(tmp_path, 'control')
    last_month = MemoryLedger((dataclasses.replace(other, month='2026-10'),))
    command, _ = _tick(work, forge, family=_FAMILY, ledger=last_month)
    assert command.ran != [], "last month's charge is not this month's"
    shared = MemoryLedger()
    assert hold(shared, Month('anthropic', 15.0), repo='o/r', number=1, usd=10.0, now=_NOW) is not None
    assert hold(shared, Month('anthropic', 15.0), repo='p/q', number=1, usd=10.0, now=_NOW) is None
    assert [one.tag for one in shared.held] == ['o/r#1']


def test_the_judge_charges_the_same_ledger_and_keeps_its_own_machine_file(tmp_path: Path) -> None:
    """A host with a machine file charges the ONE ledger what the run spent, its ai-lab reading its own file.

    PLANTED CONTROL: on a runner the derived file is pointed at; on the judge it never is.
    """
    seen: list[str | None] = []
    command = FakeCommand()

    def run(argv: object, where: Path) -> str:
        seen.append(os.environ.get('LAB_COMMONS_CONFIG'))
        return command(argv, where)

    work, forge, _, _ = _fresh(tmp_path, 'judge')
    ledger = MemoryLedger()
    _tick(work, forge, family=_FAMILY, ledger=ledger, hosted=False, spent_after=2.0, run=run)
    assert seen, 'the review ran'
    assert all(one is None for one in seen), "the judge's ai-lab keeps its machine file"
    assert [(one.kind, one.usd) for one in ledger.held] == [(HOLD, 1.0), (SPENT, 2.0)], 'the run, not the month'
    work, forge, _, _ = _fresh(tmp_path, 'control')
    seen.clear()
    _tick(work, forge, family=_FAMILY, ledger=MemoryLedger(), hosted=True, run=run)
    assert seen
    assert all(one is not None for one in seen)


def test_the_judge_and_a_runner_read_the_same_month_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """The judge's machine file and the variable ``secrets month`` derives from it are ONE month.

    PLANTED CONTROLS: a runner with no variable has none; a month with no ledger is refused by name.
    """
    ai_lab = {'standing': {'review': {'provider': 'anthropic', 'amount': 750, 'currency': 'USD'}}}
    judge = declared_month(ai_lab, {'ledger': _LEDGER_URL})
    assert judge == FamilyMonth(Month('anthropic', 750), _LEDGER_URL)
    wrote: list[tuple[str, str]] = []
    target = Target('hub', Path(), Forge('github.com', 'o', 'hub'))
    monkeypatch.setattr(forgesecrets, '_reachable', lambda _repos: ([target], []))
    code = forgesecrets.main(['month'], members=dict, month=lambda: judge,
                             variable=lambda _t, name, value: wrote.append((name, value)))  # fmt: skip
    assert code == 0
    assert wrote == [(MONTH_VAR, judge.text())]
    monkeypatch.setattr('dev_lab.dev.reviewledger.hosted_here', lambda: True)
    assert month_here({MONTH_VAR: wrote[0][1]}) == judge
    assert month_here({}) is None
    with pytest.raises(ValueError, match='names no ledger'):
        declared_month(ai_lab, {})
    assert declared_month({}, {'ledger': _LEDGER_URL}) is None
    assert forgesecrets.main(['month'], members=dict, month=lambda: None, variable=lambda *_: None) == 2


def test_a_malformed_variable_is_refused_by_name() -> None:
    bad = ('nope', '[]', json.dumps({'provider': 'anthropic', 'amount': 1}),
           json.dumps({'provider': 'anthropic', 'amount': 1, 'currency': 'CNY', 'ledger': _LEDGER_URL}))  # fmt: skip
    for one in bad:
        with pytest.raises(ValueError, match=f'{MONTH_VAR}|month|ledger'):
            FamilyMonth.from_text(one)
    assert FamilyMonth.from_text(_FAMILY.text()) == _FAMILY, 'PLANTED CONTROL'


def test_the_ledger_token_never_reaches_a_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``secrets sync --secret`` says a sha256 prefix; the ledger client holds the token; an entry never names it.

    PLANTED CONTROL: with no token anywhere the ledger is refused by name, and the refusal carries no value.
    """
    target = Target('hub', Path(), Forge('github.com', 'o', 'hub'))
    monkeypatch.setattr(forgesecrets, '_reachable', lambda _repos: ([target], []))
    wrote: list[tuple[str, str]] = []
    assert forgesecrets.main(['sync', '--secret', LEDGER_TOKEN], stdin=lambda: _TOKEN, members=dict,
                             write=lambda _t, name, value: wrote.append((name, value))) == 0  # fmt: skip
    assert wrote == [(LEDGER_TOKEN, _TOKEN)]
    said = capsys.readouterr()
    assert _TOKEN not in said.out + said.err
    assert f'{LEDGER_TOKEN} set (sha256 ' in said.out
    ledger = forge_ledger(_FAMILY, token=_TOKEN)
    assert ledger.client.token == _TOKEN
    assert ledger.client.forge.identity == 'github.com/example-org/records'
    entry = Entry(month_key(_NOW), 'o/r', 1, 'ab', HOLD, 1.0)
    assert _TOKEN not in entry.name + json.dumps(entry.__dict__)
    monkeypatch.setattr('dev_lab.dev.reviewledger.hosted_here', lambda: True)
    with pytest.raises(ValueError, match='no ledger token') as refused:
        forge_ledger(_FAMILY)
    assert str(refused.value) == NO_LEDGER_TOKEN


def test_an_unreadable_ledger_skips_named_and_runs_nothing(tmp_path: Path) -> None:
    """No ledger, no hold, no run: the race bound would not hold. PLANTED CONTROL: a readable ledger runs (above)."""
    work, forge, number, _ = _fresh(tmp_path, 'a')
    command, _ = _tick(work, forge, family=_FAMILY, ledger=Broken())
    assert command.ran == []
    assert LEDGER_UNREAD in (waiver_of(trusted_bodies(forge, number)) or '')


def test_two_racing_holds_never_both_pass_a_month_that_holds_one() -> None:
    """THE RACE BOUND: A has appended its hold but not yet re-read when B holds; B sees A's older hold and withdraws.

    PLANTED CONTROL: a month that holds both admits B too.
    """
    for amount, b_admitted in ((15.0, False), (20.0, True)):
        ledger = MemoryLedger()
        ledger.append(Entry(month_key(_NOW), 'p/q', 1, 'aa', HOLD, 10.0))  # A, another repo, mid-hold
        second = hold(ledger, Month('anthropic', amount), repo='o/r', number=2, usd=10.0, now=_NOW)
        assert (second is not None) == b_admitted
        assert sum(one.usd for one in ledger.held) <= amount, 'the admitted holds fit the month'
        assert len(ledger.held) == (2 if b_admitted else 1), 'a refused hold is withdrawn'


def test_a_settled_run_charges_its_spend_not_its_hold() -> None:
    month = month_key(_NOW)
    entries = (Entry(month, 'o/r', 3, 'aa', HOLD, 10.0, 1), Entry(month, 'o/r', 3, 'aa', SPENT, 2.5, 2),
               Entry(month, 'p/q', 3, 'bb', HOLD, 10.0, 3))  # fmt: skip
    spend = spend_of(_MONTH, entries, now=_NOW)
    assert spend.spent_usd == 12.5
    assert spend.of('o/r#3') == 2.5
    assert spend.of('p/q#3') == 10.0, 'the same number in another repo is another PR'
    assert spend.provider == 'anthropic'


def test_an_entry_name_round_trips_and_other_files_are_not_entries() -> None:
    one = Entry('2026-11', 'some-org/a.repo_x', 12, 'deadbeef', HOLD, 1.25, 9)
    assert Entry.parse(one.name, 9) == one
    assert Entry.parse('run-' + '0' * 40 + '-unit-x.json.gz', 1) is None


def test_the_derived_machine_file_allots_the_review_what_the_month_has_left() -> None:
    doc = tomllib.loads(derived_config(_MONTH, 42.5))
    assert doc['ai_lab']['spend_cap']['anthropic'] == {'amount': 42.5, 'currency': 'USD'}
    assert doc['ai_lab']['standing']['review'] == {'provider': 'anthropic', 'amount': 42.5, 'currency': 'USD'}


def test_no_repo_declares_a_month_of_its_own() -> None:
    """One month for the family: a per-repo ``month`` is an unknown key. PLANTED CONTROL: no key parses."""
    with pytest.raises(ValueError, match='unknown key'):
        review_from('[tool.dev_lab.review]\nmonth = { provider = "anthropic", amount = 100 }\n', 'x')
    assert review_from('', 'x') is not None


def test_a_concurrent_hold_names_why_the_review_skipped() -> None:
    assert 'concurrent' in HELD_ELSEWHERE
