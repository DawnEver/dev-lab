"""HPC ACCOUNT AFFINITY (user ruling 2026-10-30): verify accounts claim a verify part; research never borrows it."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from importlib.metadata import entry_points
from pathlib import Path

from lab_commons.compute.model import INTEGRATION, REQUEST, Candidate
from lab_commons.hpc.affinity import READER
from lab_commons.hpc.grants import Affinity
from lab_commons.hpc.shell import FULL

from dev_lab.dev import forgeaffinity, forgehosts
from dev_lab.dev.forgeaffinity import DEFERRED, covers, declared, deferral, defers
from dev_lab.dev.forgehosts import HostCard
from dev_lab.dev.hpchost import spec

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


def _card(host: str, *, verify=('tests/*',), at: datetime = NOW) -> HostCard:
    return HostCard(host, 'bot', 'linux', at.isoformat(), verify=verify)


def _part(sha: str, *, age_min: float, kind: str = INTEGRATION) -> Candidate:
    return Candidate('o/r', 'integrate/main', sha, 'base', kind, NOW - timedelta(minutes=age_min), FULL)


def _deferral(cards: list[HostCard], *, borrow: bool = False) -> Callable[[Candidate], str]:
    return deferral(cards, now=NOW, borrow=borrow)


def test_an_affined_seat_orders_a_covered_part_first_and_nothing_else() -> None:
    assert covers(('tests/*',), 'tests/base')
    assert not covers((), 'tests/base'), 'PLANTED CONTROL: an account declaring no affinity lifts nothing'
    assert not covers(('tests/*',), ''), 'a request has no part context: no affinity covers it'


def test_a_research_seat_never_claims_a_verify_part_even_after_30_min_and_on_a_backlog() -> None:
    """User ruling 2026-10-30: no grace, no backlog release -- the part waits for the verify accounts."""
    backlog = [_part(f'{n:040x}', age_min=30 + n) for n in range(5)]
    defer = _deferral([_card('ada/v1')])
    assert all(defer(one).startswith(DEFERRED) for one in backlog)
    assert deferral([_card('ada/v1')], now=NOW, borrow=False, mine=('tests/*',))(backlog[0]) == '', (
        'PLANTED CONTROL: the verify seat itself claims it'
    )


def test_with_no_live_verify_card_nothing_is_deferred_so_the_forge_never_deadlocks() -> None:
    old = _part('a' * 40, age_min=1)
    assert _deferral([])(old) == ''
    assert _deferral([_card('ada/v1', at=NOW - timedelta(days=1))])(old) == '', 'a dark verify account claims nothing'
    assert _deferral([_card('ada/r2', verify=())])(old) == '', 'only an affined card defers'
    assert _deferral([_card('ada/v1')])(old).startswith(DEFERRED), 'PLANTED CONTROL: a live verify card defers it'


def test_only_the_users_opt_in_lets_a_research_seat_claim_a_verify_part() -> None:
    old = _part('a' * 40, age_min=1)
    assert _deferral([_card('ada/v1')], borrow=True)(old) == ''
    assert defers(hosts=['ada/v1'], borrow=False).startswith(DEFERRED), 'PLANTED CONTROL: without it, it waits'


def test_a_request_is_never_deferred() -> None:
    request = _part('c' * 40, age_min=1, kind=REQUEST)
    assert _deferral([_card('ada/v1')])(request) == ''


def test_a_seat_reads_its_affinity_off_its_own_deploy_row(tmp_path: Path) -> None:
    rows = (
        spec.Repo('r', 'https://forge.example.org/o/r.git', 'main', verify=('tests/*',)),
        spec.Repo('q', 'https://forge.example.org/o/q', 'main'),
    )
    path = tmp_path / 'config.toml'
    path.write_text(spec.render(spec.Deployment('h', 'src', '3.13', rows)), encoding='utf-8')
    assert declared(path, 'https://forge.example.org/o/r') == ('tests/*',)
    assert declared(path, 'https://forge.example.org/o/q.git') == (), 'PLANTED CONTROL: q declares none'
    assert declared(tmp_path / 'absent.toml', 'https://forge.example.org/o/r') == (), 'a workstation has no [deploy]'


def _seat(host: str, *, verify=('tests/*',), at: datetime = NOW) -> HostCard:
    return HostCard(host, 'bot', 'linux', at.isoformat(), verify=verify)


def test_research_reads_the_verify_accounts_off_the_host_cards() -> None:
    """The one source: each verify account's card, live or stale -- a dark verify account is still not research's."""
    cards = [
        _seat('ada/live'),
        _seat('ada/gpu', verify=('tests/gpu',)),
        _seat('ada/gone', at=NOW - timedelta(days=1)),
        _seat('ada/research', verify=()),
        _seat(forgehosts.host_id('ada/opaque')),
        _seat('box', verify=()),
    ]
    held = forgeaffinity.research_affinity_of(cards)
    assert held == Affinity(verify=frozenset({'live', 'gpu', 'gone'}))


def test_with_no_affinity_declared_on_any_card_the_reader_returns_none() -> None:
    """PLANTED CONTROL: research placement stays exactly as it was when no account declares ``verify``."""
    assert forgeaffinity.research_affinity_of([_seat('ada/a', verify=()), _seat('box', verify=())]) is None


def test_the_reader_is_installed_where_lab_commons_looks_for_it() -> None:
    (point,) = entry_points(group=READER)
    assert point.load() is forgeaffinity.research_affinity
