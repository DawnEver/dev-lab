"""Break-glass waves: a code opens one, merges inside it are announced by the server, the audit needs a code.

Every planted control refuses before any forge write.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from _ops_fixtures import NOW, code, config, git, origin

from dev_lab.dev.breakglass import reason
from dev_lab.ops.breakglass import BreakglassRefused, Server
from dev_lab.ops.config import OpsConfig
from dev_lab.ops.totp import STEP

HEAD = 'a' * 40
KEY = 'SHA256:agentkey'
HOUR = 3600.0


@dataclass
class FakeForge:
    state: str = 'open'
    base: str = 'integrate/main'
    head: str = HEAD
    calls: list[tuple[str, int, str]] = field(default_factory=list)

    def pull(self, number: int) -> tuple[str, str, str]:
        del number
        return self.state, self.base, self.head

    def comment(self, number: int, body: str) -> None:
        self.calls.append(('comment', number, body))

    def merge(self, number: int, *, head: str, message: str) -> None:
        del head
        self.calls.append(('merge', number, message))


@dataclass
class Host:
    config: OpsConfig
    forge: FakeForge = field(default_factory=FakeForge)
    alerts: list[tuple[str, str]] = field(default_factory=list)
    clock: list[float] = field(default_factory=lambda: [NOW])
    key: str = KEY

    @property
    def server(self) -> Server:
        return Server(
            self.config,
            lambda _root: self.forge,
            lambda t, d: self.alerts.append((t, d)),
            lambda: self.clock[0],
            key=self.key,
        )

    def ask(self, action: str, **fields: object) -> str:
        return self.server.handle(json.dumps({'action': action, **fields}))

    def merge(self, **overrides: object) -> str:
        return self.ask(
            'merge', **{'repo': 'alpha', 'pr': 7, 'head': HEAD, 'reason': 'review-bot is down', **overrides}
        )

    def later(self, seconds: float) -> None:
        self.clock[0] += seconds

    def code(self) -> str:
        return code(int((self.clock[0] - NOW) // STEP))


@pytest.fixture
def host(tmp_path: Path) -> Host:
    url, _ = origin(tmp_path)
    built = config(tmp_path, [url], extra='wave_hours = 4.0\nmax_merges = 3')
    git(tmp_path, 'clone', '-q', url, str(built.checkout(url)))
    return Host(built)


def test_a_wave_merges_without_a_code_announces_each_merge_and_audits_on_close(host: Host) -> None:
    assert 'open for 4 h, at most 3' in host.ask('open', code=host.code())
    assert host.merge().startswith('merged alpha#7')
    assert [call[0] for call in host.forge.calls] == ['comment', 'merge']
    assert reason(host.forge.calls[1][2]) == 'review-bot is down'  # the existing Break-Glass notice reads it
    merged = [a for a in host.alerts if a[0] == 'break-glass MERGED alpha#7']
    assert HEAD in merged[0][1]  # the SERVER's announcement names the head that actually merged
    assert KEY in merged[0][1]  # ... and the ssh key that asked for it
    report = host.ask('close')
    assert f'alpha#7 at aaaaaaaaaaaa by key {KEY}: review-bot is down' in report
    assert 'awaits acknowledgement' not in report
    assert 'audit' in host.ask('status')


@pytest.mark.parametrize('bad', ['', '000000', 'abcdef'])
def test_opening_without_a_right_code_is_refused(host: Host, bad: str) -> None:
    with pytest.raises(BreakglassRefused):
        host.ask('open', code=bad)
    assert 'no wave' in host.ask('status')


def test_a_replayed_open_code_is_refused(host: Host) -> None:
    used = host.code()
    host.ask('open', code=used)
    host.ask('close')
    with pytest.raises(BreakglassRefused, match='already used'):
        host.ask('open', code=used)


def test_a_second_open_wave_is_refused(host: Host) -> None:
    host.ask('open', code=host.code())
    host.later(STEP)
    with pytest.raises(BreakglassRefused, match='is open'):
        host.ask('open', code=host.code())


def test_a_merge_outside_a_wave_is_refused(host: Host) -> None:
    with pytest.raises(BreakglassRefused, match='no break-glass wave is open'):
        host.merge()
    assert host.forge.calls == []


def test_a_merge_after_expiry_is_refused_and_the_expiry_closes_the_wave(host: Host) -> None:
    host.ask('open', code=host.code(), hours=1)
    host.later(HOUR + 1)
    with pytest.raises(BreakglassRefused, match='no break-glass wave is open'):
        host.merge()
    assert host.forge.calls == []
    assert any('AUDIT AND ACKNOWLEDGE' in a[0] for a in host.alerts)


def test_the_client_may_only_shorten_the_window(host: Host) -> None:
    assert 'open for 4 h' in host.ask('open', code=host.code(), hours=99)


def test_a_merge_beyond_the_cap_is_refused(host: Host) -> None:
    host.ask('open', code=host.code(), max_merges=1)
    host.merge()
    with pytest.raises(BreakglassRefused, match='cap of 1'):
        host.merge()
    assert len(host.forge.calls) == 2


def test_an_unacknowledged_audit_never_blocks_the_next_wave(host: Host) -> None:
    host.ask('open', code=host.code())
    host.ask('close')
    host.later(STEP)
    assert 'open for' in host.ask('open', code=host.code())
    assert host.merge().startswith('merged')


def test_ack_needs_no_code_and_records_who(host: Host) -> None:
    host.ask('open', code=host.code())
    host.ask('close')
    assert host.ask('ack', by='user@ws').endswith('acknowledged by user@ws')
    assert 'acknowledged' in host.ask('status')
    with pytest.raises(BreakglassRefused, match='no wave awaits'):
        host.ask('ack', by='user@ws')


def test_the_tick_reminds_an_unacknowledged_audit_once_per_period(host: Host) -> None:
    host.ask('open', code=host.code())
    host.ask('close')
    host.alerts.clear()
    host.server.tick()
    assert host.alerts == []
    host.later(24 * HOUR)
    host.server.tick()
    host.server.tick()
    assert [a[0] for a in host.alerts] == [
        f'break-glass wave {host.ask("status").split()[1][:-1]} awaits acknowledgement'
    ]


@pytest.mark.parametrize(
    ('overrides', 'forge', 'why'),
    [
        ({'repo': 'beta'}, FakeForge(), 'not a repository this host serves'),
        ({'reason': 'short'}, FakeForge(), 'at least 10'),
        ({}, FakeForge(state='closed'), 'closed, not open'),
        ({}, FakeForge(base='main'), 'not the integration branch integrate/main'),
        ({}, FakeForge(head='b' * 40), 'not the aaaaaaaaaaaa you were shown'),
    ],
)
def test_planted_pr_controls_refuse_before_any_write(
    host: Host, overrides: dict[str, str], forge: FakeForge, why: str
) -> None:
    host.forge = forge
    host.ask('open', code=host.code())
    with pytest.raises(BreakglassRefused, match=why):
        host.merge(**overrides)
    assert forge.calls == []
    assert host.config.breakglass is not None
    assert 'refused' in Path(host.config.breakglass.log).read_text(encoding='utf-8')


def test_a_missing_secret_refuses_naming_enrol(host: Host) -> None:
    assert host.config.breakglass is not None
    Path(host.config.breakglass.totp).unlink()
    with pytest.raises(BreakglassRefused, match='enrol'):
        host.ask('open', code=host.code())


def test_a_malformed_request_is_refused(host: Host) -> None:
    with pytest.raises(BreakglassRefused, match='malformed'):
        host.server.handle('not json')
    with pytest.raises(BreakglassRefused, match='malformed'):
        host.ask('launch')


def test_the_key_is_in_the_wave_record_and_every_audit_line(host: Host) -> None:
    host.ask('open', code=host.code())
    host.merge()
    assert host.config.breakglass is not None
    state = Path(host.config.breakglass.state) / 'waves'
    [record] = state.glob('*.json')
    assert json.loads(record.read_text(encoding='utf-8'))['merges'][0]['key'] == KEY
    lines = Path(host.config.breakglass.log).read_text(encoding='utf-8').splitlines()
    assert {json.loads(line)['key'] for line in lines} == {KEY}


def _wrong(host: Host, times: int) -> None:
    for _ in range(times):
        with pytest.raises(BreakglassRefused):
            host.ask('open', code='000000')


def test_five_wrong_codes_lock_out_even_a_right_code_and_alert_once(host: Host) -> None:
    _wrong(host, 5)
    assert [a[0] for a in host.alerts].count('break-glass LOCKED OUT') == 1
    with pytest.raises(BreakglassRefused, match='too many wrong codes'):
        host.ask('open', code=host.code())
    _wrong(host, 3)
    assert [a[0] for a in host.alerts].count('break-glass LOCKED OUT') == 1


def test_the_lockout_survives_a_restart_and_ends_after_its_minutes(host: Host) -> None:
    _wrong(host, 5)
    restarted = Host(host.config, clock=host.clock)  # a fresh Server reads the persisted lockout
    with pytest.raises(BreakglassRefused, match='too many wrong codes'):
        restarted.ask('open', code=restarted.code())
    restarted.later(15 * 60)
    assert 'open for' in restarted.ask('open', code=restarted.code())


def test_a_right_code_resets_the_count(host: Host) -> None:
    _wrong(host, 4)
    host.ask('open', code=host.code())
    host.ask('close')
    host.later(STEP)
    _wrong(host, 4)
    host.later(STEP)
    assert 'open for' in host.ask('open', code=host.code())
    assert 'break-glass LOCKED OUT' not in [a[0] for a in host.alerts]


def test_the_lockout_bounds_are_configured(tmp_path: Path) -> None:
    url, _ = origin(tmp_path)
    built = config(tmp_path, [url], extra='lockout_after = 2\nlockout_minutes = 1')
    git(tmp_path, 'clone', '-q', url, str(built.checkout(url)))
    host = Host(built)
    _wrong(host, 2)
    with pytest.raises(BreakglassRefused, match='too many wrong codes'):
        host.ask('open', code=host.code())
    host.later(60)
    assert 'open for' in host.ask('open', code=host.code())
