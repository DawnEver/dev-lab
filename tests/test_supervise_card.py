"""The host's status card: one small JSON a supervise cycle publishes, read without ssh (2026-11-13).

Debugging a forge host must not need the user's one-time code. The card is what a reader needs first -- each
declared component up or down, memory against the supervisor's cap, every metric (disk free, a queue depth a probe
declares), the last error, the installed dev-lab sha, the last auto-upgrade audit line -- and a reader judges it
STALE when it is older than :data:`STALE_CYCLES` intervals, because a card nobody rewrites says "up" forever.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dev_lab.supervise import card as status
from dev_lab.supervise import cli
from dev_lab.supervise.loop import CycleResult
from dev_lab.supervise.verdict import Anomaly, Severity

_AT = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


def _anomaly(source: str, message: str = 'gitea answered 502') -> Anomaly:
    found = Anomaly(kind=source.split('.', 1)[1], severity=Severity.CRITICAL, message=message)
    found.source = source
    return found


def _card(result: CycleResult, previous: dict | None = None, **extra: object) -> dict:
    return status.card(
        result, _AT, components=('http_health', 'disk_usage'), interval_s=300, previous=previous, **extra
    )


def test_a_component_with_an_anomaly_shows_down_and_its_error_is_the_last_error() -> None:
    """PLANTED CONTROL: one component down is down; the other stays up -- the card can say no."""
    result = CycleResult(status='degraded', metrics={'root_free_gb': 3.5}, anomalies=[_anomaly('http_health.down')])
    found = _card(result)
    assert found['components'] == {'http_health': 'down', 'disk_usage': 'up'}
    assert found['status'] == 'degraded'
    assert found['metrics'] == {'root_free_gb': 3.5}
    assert found['last_error'] == {'at': _AT.isoformat(), 'source': 'http_health.down', 'message': 'gitea answered 502'}


def test_a_healthy_cycle_keeps_the_previous_last_error_and_every_component_up() -> None:
    before = {'last_error': {'at': '2026-11-13T11:00:00+00:00', 'source': 'x.y', 'message': 'old'}}
    found = _card(CycleResult(status='healthy'), previous=before)
    assert set(found['components'].values()) == {'up'}
    assert found['last_error'] == before['last_error'], 'the last error is remembered, not wiped by a quiet cycle'


def test_an_error_message_is_redacted_before_it_is_published() -> None:
    token = 'A' * 32
    result = CycleResult(status='degraded', anomalies=[_anomaly('http_health.down', f'refused Bearer {token}')])
    assert token not in json.dumps(_card(result))


def test_the_card_carries_the_installed_sha_memory_against_its_cap_and_the_last_audit_line(tmp_path: Path) -> None:
    audit = tmp_path / 'audit.jsonl'
    audit.write_text('{"result": "refused"}\n{"from": "a", "to": "b", "result": "upgraded"}\n', encoding='utf-8')
    cgroup = tmp_path / 'cg'
    (cgroup / 'system.slice' / 'sup.service').mkdir(parents=True)
    (cgroup / 'system.slice' / 'sup.service' / 'memory.current').write_text(f'{64 * 2**20}\n', encoding='utf-8')
    (cgroup / 'system.slice' / 'sup.service' / 'memory.max').write_text(f'{256 * 2**20}\n', encoding='utf-8')
    proc = tmp_path / 'self-cgroup'
    proc.write_text('0::/system.slice/sup.service\n', encoding='utf-8')
    found = _card(
        CycleResult(status='healthy'),
        installed='0123abc',
        upgrade=status.last_audit(audit),
        memory=status.own_memory(proc, cgroup),
    )
    assert found['dev_lab'] == '0123abc'
    assert found['upgrade'] == {'from': 'a', 'to': 'b', 'result': 'upgraded'}
    assert found['memory'] == {'current_mb': 64.0, 'max_mb': 256.0}


def test_no_cap_and_no_audit_read_as_absent_never_as_zero(tmp_path: Path) -> None:
    proc = tmp_path / 'self-cgroup'
    proc.write_text('0::/\n', encoding='utf-8')
    (tmp_path / 'memory.current').write_text('1048576\n', encoding='utf-8')
    (tmp_path / 'memory.max').write_text('max\n', encoding='utf-8')
    assert status.own_memory(proc, tmp_path) == {'current_mb': 1.0, 'max_mb': None}
    assert status.own_memory(tmp_path / 'absent', tmp_path) is None
    assert status.last_audit(tmp_path / 'absent.jsonl') is None


def test_the_card_is_written_whole_and_world_readable(tmp_path: Path) -> None:
    path = tmp_path / 'status' / 'card.json'
    status.write(path, _card(CycleResult(status='healthy')))
    assert json.loads(path.read_text(encoding='utf-8'))['at'] == _AT.isoformat()
    assert list(path.parent.iterdir()) == [path], 'no temporary file is left beside it'


@pytest.mark.parametrize(
    ('age', 'stale'),
    [(timedelta(minutes=5), False), (timedelta(minutes=15), False), (timedelta(minutes=16), True)],
)
def test_a_card_older_than_its_stale_cycles_is_flagged_stale(age: timedelta, *, stale: bool) -> None:
    """PLANTED CONTROL on both sides of the line: 3 cycles of 300 s is fresh at 15 min, stale past it."""
    found = _card(CycleResult(status='healthy'))
    assert status.is_stale(found, _AT + age) is stale
    rendered = status.render('forge', found, _AT + age)
    assert ('STALE' in rendered) is stale


def test_the_rendering_names_what_is_down_and_the_last_error() -> None:
    result = CycleResult(status='degraded', metrics={'runner_queue': 4.0}, anomalies=[_anomaly('http_health.down')])
    rendered = status.render('forge', _card(result, installed='0123abc'), _AT)
    assert 'forge: degraded' in rendered
    assert 'down: http_health' in rendered
    assert 'runner_queue=4' in rendered
    assert 'gitea answered 502' in rendered
    assert '0123abc' in rendered


def test_a_card_that_is_not_one_is_refused_by_name() -> None:
    with pytest.raises(ValueError, match='not a status card'):
        status.render('forge', {'hello': 'world'}, _AT)


def test_a_check_handed_a_card_publishes_it_with_every_enabled_component(tmp_path: Path) -> None:
    """End to end through the verb the unit runs: the card names the enabled component, not the disabled ones."""
    config = tmp_path / 'supervise.toml'
    config.write_text(
        f"[state]\nfile = '{(tmp_path / 'state.json').as_posix()}'\n"
        f"[components.disk_usage]\nenabled = true\n[[components.disk_usage.paths]]\nname = 'root'\n"
        f"path = '{tmp_path.as_posix()}'\nwarn_percent = 100\ncritical_percent = 100\n"
        + ''.join(
            f'[components.{name}]\nenabled = false\n'
            for name in (
                'http_health',
                'shell_probe',
                'process_monitor',
                'log_scanner',
                'heartbeat',
                'progress_tracker',
                'deploy',
                'host_pressure',
            )
        ),
        encoding='utf-8',
    )
    path = tmp_path / 'www' / 'card.json'
    cli.main(['check', '--project', str(tmp_path), '--config', str(config), '--card', str(path)])
    found = status.read(path)
    assert found is not None
    assert 'disk_usage' in found['components']
    assert 'http_health' not in found['components']
    assert 'root_free_gb' in found['metrics']
