"""WHAT A HOST PROVIDES: declared per machine, read onto its card; a part needs its need-set, nothing else."""

from __future__ import annotations

import pytest

from lab_commons.dev.forgeprovides import NO_PROVIDER, present, provided, unserved


def test_the_machine_file_declares_what_this_host_provides() -> None:
    assert provided({'jmag': {'seats': 4}, 'dev_checkout': {}}) == {'jmag': {'seats': 4}, 'dev_checkout': {}}
    assert provided({}) == {}


@pytest.mark.parametrize('table', [{'jmag': 4}, {'jmag': {'seats': 0}}, {'jmag': {'seats': 'four'}}, {'Linux': {}}])
def test_a_malformed_capability_is_refused_by_name(table: dict[str, object]) -> None:
    with pytest.raises(ValueError, match=r'\[capabilities'):
        provided(table)


def test_a_card_has_its_os_and_its_machine_file_resources() -> None:
    assert present('windows', {'jmag': {'seats': 4}}) == {'windows', 'jmag'}
    assert present('linux', {}) == {'linux'}


def test_the_queue_names_the_resource_no_live_host_has() -> None:
    hosts = [present('windows', {}), present('linux', {})]
    assert unserved({'jmag'}, hosts) == f'{NO_PROVIDER} jmag'
    assert unserved({'dev_checkout', 'windows'}, hosts) == f'{NO_PROVIDER} dev_checkout'
    assert unserved(set(), hosts) == '', 'base needs nothing: any live host serves it'
    assert unserved({'windows'}, hosts) == ''
    assert unserved({'jmag'}, [*hosts, present('windows', {'jmag': {}})]) == '', 'PLANTED CONTROL: one host has it'


def test_a_need_set_split_across_hosts_is_still_unserved() -> None:
    """Each resource exists somewhere, but no ONE host has both: a part runs on one host."""
    hosts = [present('windows', {}), present('linux', {'matlab': {}})]
    assert unserved({'matlab', 'windows'}, hosts) == f'{NO_PROVIDER} matlab+windows'
    assert unserved(set(), []) == 'no host serves it'
