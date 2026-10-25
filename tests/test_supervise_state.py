"""The one state file: its key scheme, its atomicity, and what it does with a bad one."""

from __future__ import annotations

import json
from pathlib import Path

from dev_lab.supervise.state import (
    REMEDY_HISTORY,
    SCHEMA_VERSION,
    StateStore,
    clear_anomaly,
    count_anomaly,
    count_remedy,
    mark_notified,
    new_state,
    note_quiet,
    note_signature,
    read_anomaly,
)


def test_a_new_state_declares_its_version_and_holds_nothing() -> None:
    """One shape, stated once, so a future change to it is detectable rather than guessed at."""
    state = new_state()
    assert state['version'] == SCHEMA_VERSION
    assert state['anomalies'] == {}
    assert state['remedies'] == []
    assert state['last_quiet'] == ''
    assert state['components'] == {}


def test_a_missing_file_reads_as_a_fresh_state(tmp_path: Path) -> None:
    """A daemon that cannot read its own history should start a new one, not refuse to run."""
    assert StateStore(tmp_path / 'absent.json').read() == new_state()


def test_an_unparseable_file_reads_as_a_fresh_state_and_is_left_alone(tmp_path: Path) -> None:
    """The bad file stays on disk for a human, but it does not stop the supervisor."""
    path = tmp_path / 'state.json'
    path.write_text('{ this is not json', encoding='utf-8')
    assert StateStore(path).read() == new_state()
    assert path.read_text(encoding='utf-8') == '{ this is not json'


def test_a_state_from_another_schema_is_not_reinterpreted(tmp_path: Path) -> None:
    """A version this build does not know is a state it must not read as if it did."""
    path = tmp_path / 'state.json'
    path.write_text(json.dumps({'version': SCHEMA_VERSION + 1, 'anomalies': {'x': {}}}), encoding='utf-8')
    assert StateStore(path).read() == new_state()


def test_a_write_round_trips(tmp_path: Path) -> None:
    """The store is the only way state reaches disk, so it must read back what it wrote."""
    store = StateStore(tmp_path / 'state.json')
    state = new_state()
    count_anomaly(state, 'probe.unreachable')
    assert store.write(state) is True
    assert store.read()['anomalies']['probe.unreachable']['consecutive'] == 1


def test_the_write_creates_its_directory(tmp_path: Path) -> None:
    """A first run has no state directory yet, and must not fail on that."""
    store = StateStore(tmp_path / 'nested' / 'deeper' / 'state.json')
    assert store.write(new_state()) is True
    assert store.path.is_file()


def test_a_consecutive_count_rises_and_a_clean_cycle_drops_it() -> None:
    """The whole point of the count: telling 'just started' from 'failing since Tuesday'."""
    state = new_state()
    assert count_anomaly(state, 'probe.unreachable') == 1
    assert count_anomaly(state, 'probe.unreachable') == 2
    assert count_anomaly(state, 'probe.unreachable') == 3
    clear_anomaly(state, 'probe.unreachable')
    assert read_anomaly(state, 'probe.unreachable')['consecutive'] == 0


def test_two_sources_are_counted_apart() -> None:
    """The predecessor mixed `<kind>` and `<component>.<kind>` keys; here the key is always the source."""
    state = new_state()
    count_anomaly(state, 'http_health.unreachable')
    count_anomaly(state, 'http_health.unreachable')
    count_anomaly(state, 'disk_usage.root_full')
    assert read_anomaly(state, 'http_health.unreachable')['consecutive'] == 2
    assert read_anomaly(state, 'disk_usage.root_full')['consecutive'] == 1


def test_an_unchanged_signature_keeps_counting() -> None:
    """The same condition still true is what suppression is for."""
    state = new_state()
    assert note_signature(state, 'probe.unreachable', 'sha-abc') == 1
    assert note_signature(state, 'probe.unreachable', 'sha-abc') == 2
    assert note_signature(state, 'probe.unreachable', 'sha-abc') == 3


def test_a_changed_signature_restarts_the_count() -> None:
    """A situation that genuinely moved must release a suppression, not hide behind it."""
    state = new_state()
    note_signature(state, 'probe.unreachable', 'sha-abc')
    note_signature(state, 'probe.unreachable', 'sha-abc')
    assert note_signature(state, 'probe.unreachable', 'sha-def') == 1
    assert read_anomaly(state, 'probe.unreachable')['last_alert'] == ''


def test_marking_an_alert_records_when_it_went() -> None:
    """Cooldown needs the time, and nothing else in the entry supplies it."""
    state = new_state()
    mark_notified(state, 'probe.unreachable', '2026-10-03T20:00:00+00:00')
    assert read_anomaly(state, 'probe.unreachable')['last_alert'] == '2026-10-03T20:00:00+00:00'


def test_the_remedy_history_is_bounded() -> None:
    """An unbounded list would grow the state file for the life of the deployment."""
    state = new_state()
    for index in range(REMEDY_HISTORY + 10):
        count_remedy(state, {'source': 'x.y', 'action': 'restart', 'attempts': index})
    assert len(state['remedies']) == REMEDY_HISTORY
    assert state['remedies'][-1]['attempts'] == REMEDY_HISTORY + 9


def test_a_remedy_entry_is_a_copy_not_a_reference() -> None:
    """A caller that reuses its dict must not be able to rewrite history after the fact."""
    state = new_state()
    entry = {'source': 'x.y', 'action': 'restart', 'attempts': 1}
    count_remedy(state, entry)
    entry['attempts'] = 99
    assert state['remedies'][0]['attempts'] == 1


def test_the_quiet_timestamp_is_recorded() -> None:
    """A report says when the run was last fine, which needs a stamp rather than a flag."""
    state = new_state()
    note_quiet(state, '2026-10-03T20:00:00+00:00')
    assert state['last_quiet'] == '2026-10-03T20:00:00+00:00'
