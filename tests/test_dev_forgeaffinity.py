"""HPC ACCOUNT AFFINITY (user ruling 2026-10-30): verify accounts claim a verify part at once, others after a grace."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from importlib.metadata import entry_points
from pathlib import Path

import pytest
from lab_commons.compute.model import INTEGRATION, REQUEST, Candidate, Ranked
from lab_commons.hpc.affinity import READER
from lab_commons.hpc.shell import FULL

from dev_lab.dev import forgeaffinity, forgehosts
from dev_lab.dev.forgeaffinity import COLD, DEFERRED, GRACE, covers, declared, deferral, defers, saturated
from dev_lab.dev.forgeclaim import Claim
from dev_lab.dev.forgehosts import HostCard
from dev_lab.dev.forgeschedule import NOT_ADMITTED
from dev_lab.dev.hpchost import spec

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
FULL_UP = {'x': f'{NOT_ADMITTED}: lacking cpu'}
ME = Claim('G', 'bot', NOW + timedelta(hours=6), 'ada/research')


def _defers(*, waited_min: float, backlog: int = 0, busy: bool = False, warm: bool = True, hosts=('ada/v1',)) -> str:
    return defers(waited=timedelta(minutes=waited_min), backlog=backlog, busy=busy, warm_here=warm, hosts=hosts)


def _card(host: str, *, verify=('tests/*',), waiting: dict[str, str] | None = None, at: datetime = NOW) -> HostCard:
    return HostCard(host, 'bot', 'linux', at.isoformat(), waiting=waiting or {}, verify=verify)


def _part(sha: str, *, age_min: float, kind: str = INTEGRATION) -> Ranked:
    since = NOW - timedelta(minutes=age_min)
    return Ranked(Candidate('o/r', 'integrate/main', sha, 'base', kind, since, FULL), 1.0, 1.0, 1.0, 0.0)


def _deferral(cards: list[HostCard], *ranked: Ranked, warm: bool = True) -> Callable[[Candidate], str]:
    return deferral(list(ranked), cards, me=ME, now=NOW, history=lambda _sha: (), warm_here=warm)


def test_an_affined_seat_orders_a_covered_part_first_and_nothing_else() -> None:
    assert covers(('tests/*',), 'tests/base')
    assert not covers((), 'tests/base'), 'PLANTED CONTROL: an account declaring no affinity lifts nothing'
    assert not covers(('tests/*',), ''), 'a request has no part context: an idle verify account is free for it'


@pytest.mark.parametrize(('waited', 'expect'), [(19.9, 'waits'), (20.0, 'claims')], ids=['before-grace', 'after-grace'])
def test_a_research_seat_claims_a_covered_part_only_after_the_grace(waited: float, expect: str) -> None:
    assert timedelta(minutes=20) == GRACE
    assert ('waits' if _defers(waited_min=waited) else 'claims') == expect


@pytest.mark.parametrize(
    ('backlog', 'verify', 'expect'),
    [(2, 'saturated', 'claims'), (1, 'saturated', 'waits'), (2, 'free', 'waits')],
    ids=['backlog-and-busy-claims-early', 'busy-without-backlog-waits', 'backlog-with-a-free-verify-host-waits'],
)
def test_a_backlog_behind_saturated_verify_accounts_lets_a_research_seat_claim_early(
    backlog: int, verify: str, expect: str
) -> None:
    deferred = _defers(waited_min=1, backlog=backlog, busy=verify == 'saturated')
    assert ('waits' if deferred else 'claims') == expect


def test_with_no_live_affined_account_nothing_is_deferred() -> None:
    assert _defers(waited_min=0, hosts=()) == ''
    assert _defers(waited_min=0).startswith(DEFERRED), 'PLANTED CONTROL: a live affined account defers it'


def test_cache_affinity_a_warm_research_seat_claims_at_the_grace_a_cold_one_later() -> None:
    at_grace = GRACE.total_seconds() / 60
    assert _defers(waited_min=at_grace, warm=True) == ''
    assert _defers(waited_min=at_grace, warm=False).startswith(DEFERRED)
    later = (GRACE + COLD).total_seconds() / 60
    assert _defers(waited_min=later, warm=False) == '', 'PLANTED CONTROL: the cold seat still claims'


def test_the_verify_accounts_are_saturated_only_when_none_is_free() -> None:
    assert saturated([_card('ada/v1', waiting=FULL_UP), _card('ada/v2', waiting=FULL_UP)])
    assert not saturated([_card('ada/v1', waiting=FULL_UP), _card('ada/v2')]), 'PLANTED CONTROL: one is free'


def test_the_deferral_reads_the_live_affined_cards_and_the_backlog() -> None:
    young, other = _part('a' * 40, age_min=1), _part('b' * 40, age_min=1)
    saturated_v1 = [_card('ada/v1', waiting=FULL_UP)]
    assert _deferral(saturated_v1, young)(young.candidate).startswith(DEFERRED), 'a backlog of one is none'
    assert _deferral(saturated_v1, young, other)(young.candidate) == '', 'a backlog of two behind a saturated v1'
    stale = [_card('ada/v1', at=NOW - timedelta(days=1))]
    assert _deferral(stale, young)(young.candidate) == '', 'a dark verify account claims nothing: do not wait'
    unaffined = [_card('ada/r2', verify=())]
    assert _deferral(unaffined, young)(young.candidate) == '', 'PLANTED CONTROL: only an affined card defers'
    request = _part('c' * 40, age_min=1, kind=REQUEST)
    assert _deferral([_card('ada/v1')], request)(request.candidate) == '', 'a request is never deferred'


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


def test_a_seat_is_warm_for_a_repo_it_finished_a_run_of_lately(tmp_path: Path, monkeypatch) -> None:
    table = tmp_path / 'learned.json'
    monkeypatch.setattr(forgeaffinity, 'learned_path', lambda _url: table)
    assert not forgeaffinity.warm('u'), 'no run here ever: cold'
    table.write_text('{}', encoding='utf-8')
    written = table.stat().st_mtime
    assert forgeaffinity.warm('u', now=written + 3600)
    assert not forgeaffinity.warm('u', now=written + 25 * 3600), 'PLANTED CONTROL: a day-old run is cold'


def _seat(host: str, *, verify=('tests/*',), holds=(), waiting=None, at: datetime = NOW) -> HostCard:
    return HostCard(host, 'bot', 'linux', at.isoformat(), holds=holds, waiting=waiting or {}, verify=verify)


def test_research_reads_the_verify_accounts_and_which_are_busy_off_the_host_cards() -> None:
    """The one source: each verify account's card. Busy = a verify part held, or one it covers waiting on it."""
    cards = [
        _seat('ada/idle'),
        _seat('ada/running', holds=('abcdef012345 base',)),
        _seat('ada/claimable', waiting={'integrate/main@abcdef012345:base': f'{NOT_ADMITTED}: lacking cpu'}),
        _seat('ada/uncovered', verify=('tests/gpu',), waiting={'integrate/main@abcdef012345:base': 'serves'}),
        _seat('ada/gone', holds=('abcdef012345 base',), at=NOW - timedelta(days=1)),
        _seat('ada/research', verify=()),
        _seat(forgehosts.host_id('ada/opaque')),
        _seat('box', verify=()),
    ]
    held = forgeaffinity.research_affinity_of(cards, now=NOW)
    assert held.verify == {'idle', 'running', 'claimable', 'uncovered', 'gone'}
    assert held.busy == {'running', 'claimable'}, 'a stale card claims nothing; an uncovered wait is not verify work'


def test_with_no_affinity_declared_on_any_card_the_reader_returns_none() -> None:
    """PLANTED CONTROL: research placement stays exactly as it was when no account declares ``verify``."""
    assert forgeaffinity.research_affinity_of([_seat('ada/a', verify=()), _seat('box', verify=())], now=NOW) is None


def test_the_reader_is_installed_where_lab_commons_looks_for_it() -> None:
    (point,) = entry_points(group=READER)
    assert point.load() is forgeaffinity.research_affinity
