"""Break-glass waves: a code opens one, merges inside it are announced by the server, the audit needs a code.

Every planted control refuses before any forge write.
"""

from __future__ import annotations

import base64
import contextlib
import json
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from _forge_fake import Loopback, Recorder, answer, serve
from _ops_fixtures import ALPHA, GLASS, MIRROR, NOW, code, config

from dev_lab.dev.breakglass import reason
from dev_lab.dev.reviewgate import DeclarationUnread
from dev_lab.ops.breakglass import BreakglassRefused, ClientForge, Server, merge_message
from dev_lab.ops.config import Breakglass, OpsConfig
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
    #: The repo's ``pyproject.toml`` at its default branch; ``None`` plants one the forge cannot serve.
    manifest: str | None = '[tool.dev_lab.integrator]\nintegration = "integrate/main"\n'

    def declaration(self) -> str:
        if self.manifest is None:
            unread = 'pyproject.toml at main cannot be read: 404'
            raise DeclarationUnread(unread)
        return self.manifest

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
    #: Each repository URL the server asked a forge for.
    asked: list[str] = field(default_factory=list)
    clock: list[float] = field(default_factory=lambda: [NOW])
    key: str = KEY
    #: Seconds every clock read sleeps: widens each read-modify-write window, as a loaded host would.
    delay: float = 0.0

    @property
    def server(self) -> Server:
        return Server(
            self.config,
            self._forge,
            lambda t, d: self.alerts.append((t, d)),
            self._now,
            key=self.key,
        )

    def _forge(self, url: str) -> FakeForge:
        self.asked.append(url)
        return self.forge

    def _now(self) -> float:
        time.sleep(self.delay)
        return self.clock[0]

    def ask(self, action: str, **fields: object) -> str:
        return self.server.handle(json.dumps({'action': action, **fields}))

    def merge(self, **overrides: object) -> str:
        return self.ask('merge', **{'repo': ALPHA, 'pr': 7, 'head': HEAD, 'reason': 'review-bot is down', **overrides})

    def later(self, seconds: float) -> None:
        self.clock[0] += seconds

    def code(self) -> str:
        return code(int((self.clock[0] - NOW) // STEP))


@pytest.fixture
def host(tmp_path: Path) -> Host:
    return Host(config(tmp_path, [], extra='wave_hours = 4.0\nmax_merges = 3'))


def test_a_wave_merges_without_a_code_announces_each_merge_and_audits_on_close(host: Host) -> None:
    assert 'open for 4 h, at most 3' in host.ask('open', code=host.code())
    assert host.merge().startswith(f'merged {ALPHA}#7')
    assert [call[0] for call in host.forge.calls] == ['comment', 'merge']
    assert reason(host.forge.calls[1][2]) == 'review-bot is down'  # the existing Break-Glass notice reads it
    merged = [a for a in host.alerts if a[0] == f'break-glass MERGED {ALPHA}#7']
    assert HEAD in merged[0][1]  # the SERVER's announcement names the head that actually merged
    assert KEY in merged[0][1]  # ... and the ssh key that asked for it
    report = host.ask('close')
    assert f'{ALPHA}#7 at aaaaaaaaaaaa by key {KEY}: review-bot is down' in report
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
    assert 'audit' in host.ask('status')  # closed by the expiry, before the merge was judged


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
    host.merge()
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
        ({'repo': 'alpha'}, FakeForge(), 'not a repository this host serves'),
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
    host = Host(config(tmp_path, [], extra='lockout_after = 2\nlockout_minutes = 1'))
    _wrong(host, 2)
    with pytest.raises(BreakglassRefused, match='too many wrong codes'):
        host.ask('open', code=host.code())
    host.later(60)
    assert 'open for' in host.ask('open', code=host.code())


def _race(count: int, run: Callable[[], object]) -> None:
    gate = threading.Barrier(count)

    def one() -> None:
        gate.wait()
        with contextlib.suppress(BreakglassRefused):
            run()

    threads = [threading.Thread(target=one) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


def test_parallel_sessions_spend_one_code_once(host: Host) -> None:
    valid = host.code()
    host.delay = 0.02
    _race(6, lambda: host.ask('open', code=valid))
    stamp = datetime.fromtimestamp(NOW, UTC).strftime('%Y%m%dT%H%M%SZ')
    assert not any('OPENED' in a[0] for a in host.alerts)  # opening is never alerted; the losers are refused
    assert host.config.breakglass is not None
    lines = Path(host.config.breakglass.log).read_text(encoding='utf-8').splitlines()
    assert [json.loads(line).get('wave') for line in lines if json.loads(line)['outcome'] == 'opened'] == [stamp]


def test_parallel_wrong_codes_cannot_outrun_the_lockout(host: Host) -> None:
    host.delay = 0.02
    _race(10, lambda: host.ask('open', code='000000'))
    assert [a[0] for a in host.alerts].count('break-glass LOCKED OUT') == 1
    with pytest.raises(BreakglassRefused, match='too many wrong codes'):
        host.ask('open', code=host.code())


def test_an_alert_that_fails_never_loses_the_audit_or_the_merge(host: Host) -> None:
    host.ask('open', code=host.code())

    def broken(_title: str, _body: str) -> None:
        unreachable = 'telegram unreachable'
        raise OSError(unreachable)

    server = host.server
    server.alert = broken
    said = server.handle(json.dumps({'action': 'merge', 'repo': ALPHA, 'pr': 7, 'head': HEAD,
                                     'reason': 'review-bot is down'}))  # fmt: skip
    assert said.startswith('merged')
    assert host.config.breakglass is not None
    outcomes = [json.loads(line)['outcome'] for line in
                Path(host.config.breakglass.log).read_text(encoding='utf-8').splitlines()]  # fmt: skip
    assert 'merged' in outcomes
    assert any(outcome.startswith('alert failed') for outcome in outcomes)


@pytest.mark.parametrize(
    'fields',
    [{'hours': 0}, {'hours': -1}, {'hours': float('nan')}, {'hours': 'x'}, {'max_merges': 0}, {'max_merges': 1.5}],
)
def test_bad_bounds_are_refused_before_the_code_is_spent(host: Host, fields: dict[str, object]) -> None:
    valid = host.code()
    with pytest.raises(BreakglassRefused, match='malformed'):
        host.ask('open', code=valid, **fields)
    assert 'open for' in host.ask('open', code=valid)


@pytest.mark.parametrize(
    'fields',
    [{'pr': 'seven'}, {'pr': 0}, {'head': 'not-a-sha'}, {'repo': ''}, {'reason': 5}],
)
def test_a_malformed_merge_is_refused_by_the_parser(host: Host, fields: dict[str, object]) -> None:
    host.ask('open', code=host.code())
    with pytest.raises(BreakglassRefused, match='malformed'):
        host.merge(**fields)
    assert host.forge.calls == []


def test_an_internal_failure_is_not_relabelled_malformed(host: Host) -> None:
    host.ask('open', code=host.code())

    def boom(_root: Path) -> FakeForge:
        internal = 'internal'
        raise KeyError(internal)

    server = host.server
    server.forge_for = boom
    with pytest.raises(KeyError):
        server.handle(json.dumps({'action': 'merge', 'repo': ALPHA, 'pr': 7, 'head': HEAD,
                                  'reason': 'review-bot is down'}))  # fmt: skip


def test_an_unreadable_declaration_is_a_refusal_audited_and_alerted(host: Host) -> None:
    host.forge = FakeForge(manifest=None)
    host.ask('open', code=host.code())
    with pytest.raises(BreakglassRefused, match='cannot be read'):
        host.merge()
    assert host.forge.calls == []
    assert any('REFUSED' in a[0] for a in host.alerts)


def test_each_repo_is_merged_on_its_own_forge(host: Host) -> None:
    host.ask('open', code=host.code())
    assert 'merged github.com/owner/alpha#7' in host.merge(repo=MIRROR)
    host.merge(repo=ALPHA)
    assert host.asked == [GLASS[1], GLASS[0]]  # one name, two forges: each merged on its own


def test_break_glass_serves_its_own_repos_not_the_promoted_ones(tmp_path: Path) -> None:
    promoted = 'https://gitea.example/owner/beta.git'
    planted = Host(config(tmp_path, [promoted]))
    planted.ask('open', code=planted.code())
    with pytest.raises(BreakglassRefused, match='beta is not a repository'):
        planted.merge(repo='gitea.example/owner/beta')
    planted.merge(repo=MIRROR)  # control: a repo break-glass declares, promoted here or not


@pytest.mark.parametrize(
    ('bad', 'why'),
    [
        ({'tokens': {'gitea.example': 't'}}, 'github.com names no token'),  # planted: a forge with no token
        ({'tokens': {'gitea.example': 't', 'github.com': 'g', 'gitlab.example': 'l'}}, 'gitlab.example'),  # unused
        ({'repos': (*GLASS, 'https://gitea.example/owner/alpha')}, 'twice'),  # the exact same identity again
        ({'repos': ()}, 'serves no repo'),
    ],
)
def test_a_break_glass_declaration_that_lies_is_refused_at_load(
    tmp_path: Path, bad: dict[str, object], why: str
) -> None:
    built = config(tmp_path, [])
    assert built.breakglass is not None
    table: dict[str, Any] = {'account': 'b', 'totp': 't', 'state': 's', 'log': 'l', 'repos': GLASS,
             'tokens': {'gitea.example': 't', 'github.com': 'g'}, **bad}  # fmt: skip
    with pytest.raises(ValueError, match=why):
        Breakglass(**table)


def test_one_name_on_two_forges_or_owners_is_two_repos(tmp_path: Path) -> None:
    other = 'https://github.com/someone/alpha.git'
    built = config(tmp_path, [], glass=(*GLASS, other))
    assert built.breakglass is not None
    assert [built.breakglass.repo(i) for i in (ALPHA, MIRROR, 'github.com/someone/alpha')] == [*GLASS, other]
    assert built.breakglass.repo('alpha') is None


def test_each_forge_names_its_token_once(host: Host) -> None:
    role = host.config.breakglass
    assert role is not None
    assert role.token_file(GLASS[1]) == role.tokens['github.com']
    assert role.token_file(GLASS[0]) == role.tokens['gitea.example']
    assert role.token_file(GLASS[0]) != role.token_file(GLASS[1])


@pytest.fixture
def loopback() -> Iterator[Loopback]:
    for httpd in serve():
        yield Loopback(httpd)


@pytest.mark.parametrize(
    ('url', 'api', 'prefix', 'auth', 'merge'),
    [
        ('https://github.com/owner/gamma.git', 'api.github.com', '/repos/owner/gamma', 'Bearer', 'PUT'),
        ('https://gitea.example/owner/alpha.git', 'gitea.example', '/api/v1/repos/owner/alpha', 'token', 'POST'),
    ],
)
def test_the_client_forge_reads_and_merges_on_either_backend(
    loopback: Loopback, url: str, api: str, *, prefix: str, auth: str, merge: str
) -> None:
    pull = {'number': 7, 'title': 't', 'body': '', 'state': 'open', 'html_url': '', 'user': {'login': 'u'},
            'head': {'ref': 'pr/x', 'sha': HEAD}, 'base': {'ref': 'integrate/main'}}  # fmt: skip
    manifest = base64.b64encode(b'[tool.dev_lab.integrator]\nintegration = "integrate/main"\n').decode()
    answer('GET', prefix, (200, {'default_branch': 'main'}))
    answer('GET', f'{prefix}/contents/pyproject.toml', (200, {'content': manifest}))
    answer('GET', f'{prefix}/pulls/7', (200, pull))
    answer('POST', f'{prefix}/issues/7/comments', (201, {'id': 1, 'body': 'b', 'html_url': '', 'user': {'login': 'u'}}))
    answer(merge, f'{prefix}/pulls/7/merge', (200, {'merged': True}))
    forge = ClientForge(url, 'secret', transport=loopback)
    assert 'integrate/main' in forge.declaration()
    assert forge.pull(7) == ('open', 'integrate/main', HEAD)
    forge.comment(7, 'BREAK-GLASS')
    forge.merge(7, head=HEAD, message=merge_message(7, 'integrate/main', 'review-bot is down', 'w'))
    assert set(loopback.asked) == {api}
    sent = Recorder.received
    assert {r['headers']['Authorization'] for r in sent} == {f'{auth} secret'}
    assert sent[1]['path'] == f'{prefix}/contents/pyproject.toml?ref=main'
    merged = sent[-1]
    assert (merged['method'], merged['path']) == (merge, f'{prefix}/pulls/7/merge')
    body = json.dumps(merged['body'])
    assert HEAD in body
    assert 'Break-Glass: review-bot is down' in body


# User ruling 2026-11-04: one wave sent three alerts. Opening is audited only; every merge is announced at once; the
# close/expiry audit and its reminders are sent only for a wave that merged something.


def _titles(host: Host) -> list[str]:
    return [a[0] for a in host.alerts]


def _outcomes(host: Host) -> list[str]:
    assert host.config.breakglass is not None
    log = Path(host.config.breakglass.log).read_text(encoding='utf-8').splitlines()
    return [json.loads(line)['outcome'] for line in log]


def _wave_id(host: Host) -> str:
    return host.ask('status').split()[1][:-1]


def test_opening_a_wave_alerts_nothing_and_is_audited(host: Host) -> None:
    host.ask('open', code=host.code())
    assert host.alerts == []
    assert _outcomes(host) == ['opened']


def test_a_wave_that_merged_alerts_each_merge_then_its_audit(host: Host) -> None:
    host.ask('open', code=host.code())
    host.merge()
    host.ask('close')
    wave = _wave_id(host)
    assert _titles(host) == [f'break-glass MERGED {ALPHA}#7', f'break-glass wave {wave} closed: AUDIT AND ACKNOWLEDGE']


def test_closing_an_empty_wave_alerts_nothing_and_is_audited(host: Host) -> None:
    host.ask('open', code=host.code())
    host.ask('close')
    assert host.alerts == []
    assert _outcomes(host) == ['opened', 'closed']


@pytest.mark.parametrize('merged', [True, False])
def test_an_expired_wave_alerts_its_audit_only_if_it_merged(host: Host, *, merged: bool) -> None:
    host.ask('open', code=host.code(), hours=1)
    if merged:
        host.merge()
    host.later(HOUR + 1)
    host.server.tick()
    wave = _wave_id(host)
    audit = [f'break-glass wave {wave} closed: AUDIT AND ACKNOWLEDGE']
    assert _titles(host) == ([f'break-glass MERGED {ALPHA}#7', *audit] if merged else [])
    assert _outcomes(host)[-1] == 'closed'


@pytest.mark.parametrize('merged', [True, False])
def test_reminders_only_chase_a_wave_that_merged(host: Host, *, merged: bool) -> None:
    host.ask('open', code=host.code())
    if merged:
        host.merge()
    host.ask('close')
    host.alerts.clear()
    host.later(24 * HOUR)
    host.server.tick()
    reminded = [f'break-glass wave {_wave_id(host)} awaits acknowledgement']
    assert _titles(host) == (reminded if merged else [])
