"""WHAT A HOST PROVIDES: declared per machine, read onto its card; a part needs its need-set, nothing else."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from dev_lab.dev.forgehosts import HostCard
from dev_lab.dev.forgeprovides import NO_PROVIDER, present, supplied, unserved


def test_a_card_has_its_os_and_its_machine_file_resources() -> None:
    assert present('windows', {'jmag': {'seats': 4}}) == {'windows', 'jmag'}
    assert present('linux', {}) == {'linux'}


def test_the_queue_names_the_resource_no_live_host_has() -> None:
    hosts = [present('windows', {}), present('linux', {})]
    assert unserved({'jmag'}, hosts) == f'{NO_PROVIDER} jmag'
    assert unserved({'workstation', 'windows'}, hosts) == f'{NO_PROVIDER} workstation'
    assert unserved(set(), hosts) == '', 'base needs nothing: any live host serves it'
    assert unserved({'windows'}, hosts) == ''
    assert unserved({'jmag'}, [*hosts, present('windows', {'jmag': {}})]) == '', 'PLANTED CONTROL: one host has it'


def test_a_need_set_split_across_hosts_is_still_unserved() -> None:
    """Each resource exists somewhere, but no ONE host has both: a part runs on one host."""
    hosts = [present('windows', {}), present('linux', {'matlab': {}})]
    assert unserved({'matlab', 'windows'}, hosts) == f'{NO_PROVIDER} matlab+windows'
    assert unserved(set(), []) == 'no host serves it'


NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)


def _card(host: str, *, age_min: float) -> HostCard:
    """A Windows host whose JMAG probe reads present with one seat, last ticked *age_min* ago."""
    return HostCard(
        host=host, login='x', platform='windows', ticked=(NOW - timedelta(minutes=age_min)).isoformat(),
        supply={'jmag': 1.0}, tools={'jmag': {'present': True}},
    )  # fmt: skip


def test_a_stale_hosts_declared_resources_are_no_supply() -> None:
    """WS1/WS2 2026-10-28: stale since 10-25/10-27 and still read as jmag=1. A stale card supplies NOTHING."""
    stale, fresh = _card('WS1', age_min=24 * 60), _card('G', age_min=1)
    assert supplied(stale, NOW) == frozenset()
    assert unserved({'jmag'}, [supplied(stale, NOW)]) == f'{NO_PROVIDER} jmag'
    assert unserved({'jmag'}, [supplied(c, NOW) for c in (stale, fresh)]) == '', 'PLANTED CONTROL: a fresh one serves'
    assert supplied(fresh, NOW) == {'windows', 'jmag'}
