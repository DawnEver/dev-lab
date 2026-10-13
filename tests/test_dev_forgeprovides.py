"""WHAT A HOST PROVIDES: declared per machine, read onto its card, the only key a part needs beyond its OS."""

from __future__ import annotations

import pytest

from lab_commons.dev.forgeprovides import NO_PROVIDER, lacking, needs, provided, served_parts, unserved
from lab_commons.hpc.platforms import read_table

TABLE = read_table(
    '[tool.lab_commons.capabilities]\njmag = { engine = true }\ndev_checkout = { on = ["windows", "macos"] }\n'
)


def test_the_machine_file_declares_what_this_host_provides() -> None:
    assert provided({'jmag': {'seats': 4}, 'dev_checkout': {}}) == {'jmag': {'seats': 4}, 'dev_checkout': {}}
    assert provided({}) == {}


@pytest.mark.parametrize('table', [{'jmag': 4}, {'jmag': {'seats': 0}}, {'jmag': {'seats': 'four'}}, {'Linux': {}}])
def test_a_malformed_capability_is_refused_by_name(table: dict[str, object]) -> None:
    with pytest.raises(ValueError, match=r'\[capabilities'):
        provided(table)


def test_a_part_needs_its_engine_or_the_host_capabilities_its_os_carries() -> None:
    assert needs(TABLE, 'jmag') == ('jmag',)
    assert needs(TABLE, 'windows') == ('dev_checkout',)
    assert needs(TABLE, 'linux') == (), 'the cluster part needs no host capability: a host lacking one claims it'


def test_a_host_lacking_a_capability_is_never_offered_the_part() -> None:
    assert lacking(('jmag',), {}) == f'{NO_PROVIDER} jmag'
    assert lacking(('jmag',), {'jmag': {'seats': 4}}) == ''
    assert lacking((), {}) == ''


def test_a_host_serves_its_os_and_every_declared_engine_it_provides() -> None:
    declared = ('jmag', 'windows')
    assert served_parts('windows', {'jmag': {}}, declared, cluster=False) == ('windows', 'jmag')
    assert served_parts('windows', {}, declared, cluster=False) == ('windows',), 'PLANTED CONTROL: not provided'
    assert served_parts('windows', {'femm': {}}, declared, cluster=False) == ('windows',), 'not declared here'
    assert served_parts('linux', {'jmag': {}}, declared, cluster=True) == ('linux',), 'a cluster runs no engine part'


def test_the_queue_names_the_capability_no_live_host_provides() -> None:
    hosts = [('windows', {}), ('linux', {})]
    assert unserved('jmag', needs(TABLE, 'jmag'), hosts) == f'{NO_PROVIDER} jmag'
    assert unserved('windows', needs(TABLE, 'windows'), hosts) == f'{NO_PROVIDER} dev_checkout'
    assert unserved('linux', needs(TABLE, 'linux'), hosts) == ''
    assert unserved('jmag', needs(TABLE, 'jmag'), [*hosts, ('windows', {'jmag': {'seats': 4}})]) == ''
    assert unserved('macos', (), hosts) == 'no host serves macos'
