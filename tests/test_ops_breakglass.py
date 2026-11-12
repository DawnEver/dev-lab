"""Break-glass waves: a consent credential opens one, merges inside it are announced by the server.

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
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgestatus import CommitStatus
from dev_lab.dev.netverb import Report
from dev_lab.dev.reviewgate import DeclarationUnread
from dev_lab.ops.breakglass import BreakglassRefused, ClientForge, Server, merge_message
from dev_lab.ops.config import Breakglass, OpsConfig
from dev_lab.ops.configcheck import LABEL
from dev_lab.ops.consent.issuer import Issuer
from dev_lab.ops.served import app_of_forge
from dev_lab.ops.totp import STEP

HEAD = 'a' * 40
KEY = 'SHA256:agentkey'
HOUR = 3600.0
DECLARED = '[tool.dev_lab.integrator]\nintegration = "integrate/main"\n'
GREEN = (
    CommitStatus('tests/base', 'success', 'scope=full ran=3 hands=-', ''),
    CommitStatus('tests/security', 'success', 'nothing found', ''),
)


@dataclass
class FakeForge:
    state: str = 'open'
    base: str = 'integrate/main'
    head: str = HEAD
    calls: list[tuple[str, int, str]] = field(default_factory=list)
    #: The head's statuses; green tests by default, as every break-glass merge needs.
    posted: list[CommitStatus] = field(default_factory=lambda: list(GREEN))
    #: The repo's ``pyproject.toml`` per ref; an absent ref is one the forge cannot serve. The default branch
    #: (``main``) declares nothing, as a member's old data commit did: only the PR's base may be read.
    manifests: dict[str, str] = field(default_factory=lambda: {'integrate/main': DECLARED})
    #: Each PR's labels (none by default); a PR in ``unreadable`` plants a forge that cannot answer for them.
    labelled: dict[int, tuple[str, ...]] = field(default_factory=dict)
    unreadable: frozenset[int] = frozenset()

    def labels(self, number: int) -> tuple[str, ...]:
        if number in self.unreadable:
            raise ForgeCallFailed(Report(f'GET /pulls/{number}', (), 1))
        return self.labelled.get(number, ())

    def declaration(self, ref: str) -> str:
        if ref not in self.manifests:
            unread = f'pyproject.toml at {ref} cannot be read: 404'
            raise DeclarationUnread(unread)
        return self.manifests[ref]

    def pull(self, number: int) -> tuple[str, str, str]:
        del number
        return self.state, self.base, self.head

    def statuses(self, head: str) -> list[CommitStatus]:
        del head
        return list(self.posted)

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
    #: Whether a channel delivers; ``False`` models every channel failing (the alert is still recorded as tried).
    delivers: bool = True
    #: Each repository URL the server asked a forge for.
    asked: list[str] = field(default_factory=list)
    clock: list[float] = field(default_factory=lambda: [NOW])
    key: str = KEY
    #: Seconds every clock read sleeps: widens each read-modify-write window, as a loaded host would.
    delay: float = 0.0

    #: Replaces the issuer's registration (``None``: the real one).
    register: Callable[[Any, int], object] | None = None

    @property
    def issuer(self) -> Issuer:
        role = self.config.consent
        assert role is not None
        return Issuer(Path(role.totp), Path(role.key), Path(role.state), role.issuer, self._now)

    @property
    def server(self) -> Server:
        issuer = self.issuer
        return Server(self.config, self._forge, self._alert, self._now, consent_key=issuer.public(),
                      register=self.register or issuer.register, key=self.key)  # fmt: skip

    def grant(self, *, hours: float = 4, max_merges: int = 3) -> dict[str, Any]:
        """A ``breakglass.wave`` credential the user granted now (each grant spends the next TOTP step)."""
        request = {
            'action': 'breakglass.wave',
            'subject': 'test wave',
            'params': {'hours': hours, 'max_merges': max_merges},
        }
        credential = self.issuer.issue(request, self.code())
        self.later(STEP)
        return credential

    def open(self, **params: float) -> str:
        return self.ask('open', credential=self.grant(**params))

    def _alert(self, title: str, body: str) -> bool:
        self.alerts.append((title, body))
        return self.delivers

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
    return Host(config(tmp_path, [], extra='wave_hours_max = 4.0'))


def test_a_wave_merges_without_a_code_and_summarizes_on_close(host: Host) -> None:
    assert 'open for 4 h, at most 3' in host.open()
    assert host.merge().startswith(f'merged {ALPHA}#7')
    assert [call[0] for call in host.forge.calls] == ['comment', 'merge']
    assert reason(host.forge.calls[1][2]) == 'review-bot is down'  # the existing Break-Glass notice reads it
    report = host.ask('close')
    [(_title, summary)] = host.alerts
    assert HEAD in summary  # the SERVER's summary names the head that actually merged
    assert KEY in summary  # ... and the ssh key that asked for it
    assert f'{ALPHA}#7 at {HEAD} by key {KEY}: review-bot is down' in report
    assert 'awaits acknowledgement' not in report
    assert 'audit' in host.ask('status')


def test_a_credential_opens_one_wave_only(host: Host) -> None:
    credential = host.grant()
    host.ask('open', credential=credential)
    host.ask('close')
    with pytest.raises(BreakglassRefused, match='already used'):
        host.ask('open', credential=credential)


def test_a_tampered_credential_is_refused_and_opens_nothing(host: Host) -> None:
    credential = host.grant()
    with pytest.raises(BreakglassRefused, match='signature'):
        host.ask('open', credential=credential | {'params': {'hours': 4, 'max_merges': 0}})
    assert 'no wave' in host.ask('status')
    assert 'open for' in host.ask('open', credential=credential)  # the control: the untouched one opens


def test_an_unreachable_issuer_refuses_to_open_a_wave(host: Host) -> None:
    def down(_credential: object, _amount: int) -> object:
        unreachable = 'issuer down'
        raise ConnectionError(unreachable)

    host.register = down
    with pytest.raises(BreakglassRefused, match='never admitted'):
        host.open()
    assert 'no wave' in host.ask('status')


def test_a_second_open_wave_is_refused(host: Host) -> None:
    host.open()
    host.later(STEP)
    with pytest.raises(BreakglassRefused, match='is open'):
        host.open()


def test_a_merge_outside_a_wave_is_refused(host: Host) -> None:
    with pytest.raises(BreakglassRefused, match='no break-glass wave is open'):
        host.merge()
    assert host.forge.calls == []


def test_a_manual_merge_of_a_needs_consent_pr_is_refused(host: Host) -> None:
    host.open()
    host.forge.labelled[7] = (LABEL,)
    with pytest.raises(BreakglassRefused, match=f'labelled {LABEL}: .* lands only by its own consent'):
        host.merge()
    assert host.forge.calls == []
    host.forge.labelled[7] = ()  # PLANTED CONTROL: the same PR without the label merges
    assert 'merged' in host.merge()


def test_a_manual_merge_whose_labels_cannot_be_read_is_refused(host: Host) -> None:  # PLANTED CONTROL
    host.open()
    host.forge.unreadable = frozenset({7})
    with pytest.raises(BreakglassRefused, match='labels cannot be read'):
        host.merge()
    assert host.forge.calls == []


def test_a_merge_after_expiry_is_refused_and_the_expiry_closes_the_wave(host: Host) -> None:
    host.open(hours=1)
    host.later(HOUR + 1)
    with pytest.raises(BreakglassRefused, match='no break-glass wave is open'):
        host.merge()
    assert host.forge.calls == []
    assert 'audit' in host.ask('status')  # closed by the expiry, before the merge was judged


@pytest.fixture
def roomy(tmp_path: Path) -> Host:
    bounds = 'wave_hours_max = 24.0\nmax_merges_max = 10'
    return Host(config(tmp_path, [], extra=bounds))


def test_a_request_may_ask_up_to_the_ceiling(roomy: Host) -> None:
    said = roomy.open(hours=24, max_merges=10)  # planted control: exactly the ceilings
    assert 'open for 24 h, at most 10 merge(s)' in said
    opened = [json.loads(line) for line in Path(roomy.config.breakglass.log).read_text(encoding='utf-8').splitlines()]
    assert set(opened[-1]) >= {'consent'}  # the audit names the credential that opened the wave
    assert (opened[-1]['hours'], opened[-1]['max_merges']) == (24, 10)


@pytest.mark.parametrize(
    ('fields', 'ceiling'), [({'hours': 24.5}, 'wave_hours_max = 24 h'), ({'max_merges': 11}, 'max_merges_max = 10')]
)
def test_a_request_above_a_ceiling_is_refused_naming_it(roomy: Host, fields: dict[str, float], ceiling: str) -> None:
    with pytest.raises(BreakglassRefused, match=ceiling):
        roomy.open(**fields)
    assert 'open for' in roomy.open()  # never clamped


def test_no_merge_ceiling_admits_any_cap(host: Host) -> None:
    assert 'at most 50 merge(s)' in host.open(max_merges=50)


def test_a_merge_beyond_the_cap_is_refused(host: Host) -> None:
    host.open(max_merges=1)
    host.merge()
    with pytest.raises(BreakglassRefused, match='no break-glass wave is open'):  # the cap ended the wave
        host.merge()
    assert len(host.forge.calls) == 2


def test_an_unacknowledged_audit_never_blocks_the_next_wave(host: Host) -> None:
    host.open()
    host.ask('close')
    assert 'open for' in host.open()
    assert host.merge().startswith('merged')


def test_ack_needs_no_code_and_records_who(host: Host) -> None:
    host.open()
    host.ask('close')
    assert host.ask('ack', by='user@ws').endswith('acknowledged by user@ws')
    assert 'acknowledged' in host.ask('status')
    with pytest.raises(BreakglassRefused, match='no wave awaits'):
        host.ask('ack', by='user@ws')


@pytest.mark.parametrize(
    ('overrides', 'forge', 'why'),
    [
        ({'repo': 'alpha'}, FakeForge(), 'not a repository this host serves'),
        ({'reason': 'short'}, FakeForge(), 'at least 10'),
        ({}, FakeForge(state='closed'), 'closed, not open'),
        ({}, FakeForge(base='main', manifests={'main': DECLARED}), 'not the integration branch integrate/main'),
        ({}, FakeForge(head='b' * 40), 'not the aaaaaaaaaaaa you were shown'),
    ],
)
def test_planted_pr_controls_refuse_before_any_write(
    host: Host, overrides: dict[str, str], forge: FakeForge, why: str
) -> None:
    host.forge = forge
    host.open()
    with pytest.raises(BreakglassRefused, match=why):
        host.merge(**overrides)
    assert forge.calls == []
    assert host.config.breakglass is not None
    assert 'refused' in Path(host.config.breakglass.log).read_text(encoding='utf-8')


def test_a_malformed_request_is_refused(host: Host) -> None:
    with pytest.raises(BreakglassRefused, match='malformed'):
        host.server.handle('not json')
    with pytest.raises(BreakglassRefused, match='malformed'):
        host.ask('launch')


def test_the_key_is_in_the_wave_record_and_every_audit_line(host: Host) -> None:
    host.open()
    host.merge()
    assert host.config.breakglass is not None
    state = Path(host.config.breakglass.state) / 'waves'
    [record] = state.glob('*.json')
    assert json.loads(record.read_text(encoding='utf-8'))['merges'][0]['key'] == KEY
    lines = Path(host.config.breakglass.log).read_text(encoding='utf-8').splitlines()
    assert {json.loads(line)['key'] for line in lines} == {KEY}


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


def test_parallel_sessions_spend_one_credential_once(host: Host) -> None:
    credential = host.grant()
    host.delay = 0.02
    _race(6, lambda: host.ask('open', credential=credential))
    stamp = datetime.fromtimestamp(host.clock[0], UTC).strftime('%Y%m%dT%H%M%SZ')
    assert not any('OPENED' in a[0] for a in host.alerts)  # opening is never alerted; the losers are refused
    assert host.config.breakglass is not None
    lines = Path(host.config.breakglass.log).read_text(encoding='utf-8').splitlines()
    assert [json.loads(line).get('wave') for line in lines if json.loads(line)['outcome'] == 'opened'] == [stamp]


def test_an_alert_that_fails_never_loses_the_audit_or_the_merge(host: Host) -> None:
    host.open()

    def broken(_title: str, _body: str) -> bool:
        unreachable = 'telegram unreachable'
        raise OSError(unreachable)

    server = host.server
    server.alert = broken
    said = server.handle(json.dumps({'action': 'merge', 'repo': ALPHA, 'pr': 7, 'head': HEAD,
                                     'reason': 'review-bot is down'}))  # fmt: skip
    assert said.startswith('merged')
    server.handle(json.dumps({'action': 'close'}))
    assert host.config.breakglass is not None
    outcomes = [json.loads(line)['outcome'] for line in
                Path(host.config.breakglass.log).read_text(encoding='utf-8').splitlines()]  # fmt: skip
    assert 'merged' in outcomes
    assert any(outcome.startswith('alert failed') for outcome in outcomes)


@pytest.mark.parametrize('fields', [{'hours': 0}, {'hours': 4.5}])
def test_bad_bounds_are_refused_before_the_credential_is_spent(host: Host, fields: dict[str, float]) -> None:
    with pytest.raises(BreakglassRefused, match='outside the ceiling'):
        host.open(**fields)
    assert 'open for' in host.open()


def test_an_open_without_a_credential_is_malformed(host: Host) -> None:
    with pytest.raises(BreakglassRefused, match='malformed'):
        host.ask('open', code='123456')


@pytest.mark.parametrize(
    'fields',
    [{'pr': 'seven'}, {'pr': 0}, {'head': 'not-a-sha'}, {'repo': ''}, {'reason': 5}],
)
def test_a_malformed_merge_is_refused_by_the_parser(host: Host, fields: dict[str, object]) -> None:
    host.open()
    with pytest.raises(BreakglassRefused, match='malformed'):
        host.merge(**fields)
    assert host.forge.calls == []


def test_an_internal_failure_is_not_relabelled_malformed(host: Host) -> None:
    host.open()

    def boom(_root: Path) -> FakeForge:
        internal = 'internal'
        raise KeyError(internal)

    server = host.server
    server.forge_for = boom
    with pytest.raises(KeyError):
        server.handle(json.dumps({'action': 'merge', 'repo': ALPHA, 'pr': 7, 'head': HEAD,
                                  'reason': 'review-bot is down'}))  # fmt: skip


def test_an_unreadable_declaration_is_a_refusal_audited_and_alerted(host: Host) -> None:
    host.forge = FakeForge(manifests={'main': DECLARED})  # PLANTED CONTROL: only the default branch declares
    host.open()
    with pytest.raises(BreakglassRefused, match=r'pyproject\.toml at integrate/main cannot be read'):
        host.merge()
    assert host.forge.calls == []
    assert any('REFUSED' in a[0] for a in host.alerts)


def test_the_declaration_is_read_at_the_prs_base_not_the_default_branch(host: Host) -> None:
    host.forge = FakeForge()  # the default branch ``main`` declares nothing; the base ``integrate/main`` does
    host.open()
    assert 'merged' in host.merge()
    assert [call[0] for call in host.forge.calls] == ['comment', 'merge']


def test_each_repo_is_merged_on_its_own_forge(host: Host) -> None:
    host.open()
    assert 'merged github.com/owner/alpha#7' in host.merge(repo=MIRROR)
    host.merge(repo=ALPHA)
    assert host.asked == [GLASS[1], GLASS[0]]  # one name, two forges: each merged on its own


def test_break_glass_serves_its_own_repos_not_the_promoted_ones(tmp_path: Path) -> None:
    promoted = 'https://gitea.example/owner/beta.git'
    planted = Host(config(tmp_path, [promoted]))
    planted.open()
    with pytest.raises(BreakglassRefused, match='beta is not a repository'):
        planted.merge(repo='gitea.example/owner/beta')
    planted.merge(repo=MIRROR)  # control: a repo break-glass declares, promoted here or not


@pytest.mark.parametrize(
    ('bad', 'why'),
    [
        ({'apps': {}}, 'github.com names no token'),  # planted: a forge with no credential
        ({'tokens': {'gitea.example': 't', 'gitlab.example': 'l'}}, 'gitlab.example'),  # unused
        ({'repos': (*GLASS, 'https://gitea.example/owner/alpha')}, 'twice'),  # the exact same identity again
        ({'repos': ()}, 'serves no repo'),
        ({'wave_hours_max': 0.0}, 'must be positive'),
        ({'wave_hours_max': float('nan')}, 'must be positive'),
        ({'max_merges_max': -1}, 'must not be negative'),
    ],
)
def test_a_break_glass_declaration_that_lies_is_refused_at_load(
    tmp_path: Path, bad: dict[str, object], why: str
) -> None:
    built = config(tmp_path, [])
    assert built.breakglass is not None
    table: dict[str, Any] = {'account': 'b', 'state': 's', 'log': 'l', 'repos': GLASS,
             'tokens': {'gitea.example': 't'}, 'apps': {'github.com': {'app_id': 1, 'key_file': 'k'}},
             **bad}  # fmt: skip
    with pytest.raises(ValueError, match=why):
        Breakglass(**table)


def test_one_name_on_two_forges_or_owners_is_two_repos(tmp_path: Path) -> None:
    other = 'https://github.com/someone/alpha.git'
    built = config(tmp_path, [], glass=(*GLASS, other))
    assert built.breakglass is not None
    assert [built.breakglass.repo(i) for i in (ALPHA, MIRROR, 'github.com/someone/alpha')] == [*GLASS, other]
    assert built.breakglass.repo('alpha') is None


def test_each_forge_names_its_credential_once(host: Host) -> None:
    role = host.config.breakglass
    assert role is not None
    assert app_of_forge(role.apps, GLASS[1]) == (4242, Path(role.apps['github.com']['key_file']))
    assert role.token_file(GLASS[0]) == role.tokens['gitea.example']
    assert app_of_forge(role.apps, GLASS[0]) is None


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
            'head': {'ref': 'pr/x', 'sha': HEAD}, 'base': {'ref': 'integrate/main'},
            'labels': [{'name': 'needs-consent'}]}  # fmt: skip
    manifest = base64.b64encode(b'[tool.dev_lab.integrator]\nintegration = "integrate/main"\n').decode()
    answer('GET', f'{prefix}/contents/pyproject.toml', (200, {'content': manifest}))
    answer('GET', f'{prefix}/pulls/7', (200, pull))
    answer('GET', f'{prefix}/pulls/7', (200, pull))
    answer('POST', f'{prefix}/issues/7/comments', (201, {'id': 1, 'body': 'b', 'html_url': '', 'user': {'login': 'u'}}))
    answer(merge, f'{prefix}/pulls/7/merge', (200, {'merged': True}))
    forge = ClientForge(url, 'secret', transport=loopback)
    assert 'integrate/main' in forge.declaration('integrate/main')
    assert forge.pull(7) == ('open', 'integrate/main', HEAD)
    assert forge.labels(7) == ('needs-consent',)
    forge.comment(7, 'BREAK-GLASS')
    forge.merge(7, head=HEAD, message=merge_message(7, 'integrate/main', 'review-bot is down', 'w'))
    assert set(loopback.asked) == {api}
    sent = Recorder.received
    assert {r['headers']['Authorization'] for r in sent} == {f'{auth} secret'}
    assert sent[0]['path'] == f'{prefix}/contents/pyproject.toml?ref=integrate/main'
    merged = sent[-1]
    assert (merged['method'], merged['path']) == (merge, f'{prefix}/pulls/7/merge')
    body = json.dumps(merged['body'])
    assert HEAD in body
    assert 'Break-Glass: review-bot is down' in body


# User ruling 2026-11-04: "break glass still sends three messages -- one final acceptance is enough". A wave sends
# ONE alert, its summary, when it ENDS (closed, cap reached, expired) and only if it merged; never one per merge.


def _titles(host: Host) -> list[str]:
    return [a[0] for a in host.alerts]


def _outcomes(host: Host) -> list[str]:
    assert host.config.breakglass is not None
    log = Path(host.config.breakglass.log).read_text(encoding='utf-8').splitlines()
    return [json.loads(line)['outcome'] for line in log]


def _wave_id(host: Host) -> str:
    return host.ask('status').split()[1][:-1]


def _summary(host: Host) -> str:
    return f'break-glass wave {_wave_id(host)} ended: AUDIT AND ACKNOWLEDGE'


def test_opening_a_wave_alerts_nothing_and_is_audited(host: Host) -> None:
    host.open()
    assert host.alerts == []
    assert _outcomes(host) == ['opened']


def test_a_merge_alerts_nothing_while_the_wave_is_open(host: Host) -> None:
    host.open()
    host.merge()
    host.merge(pr=8)
    assert host.alerts == []
    assert _outcomes(host) == ['opened', 'merged', 'merged']


def test_closing_a_wave_that_merged_sends_one_summary_of_every_merge(host: Host) -> None:
    host.open()
    host.merge()
    host.merge(pr=8, reason='numerics-lab gate is wedged')
    host.ask('close')
    [(title, body)] = host.alerts
    assert title == _summary(host)
    assert f'{ALPHA}#7 at {HEAD} by key {KEY}: review-bot is down' in body
    assert f'{ALPHA}#8 at {HEAD} by key {KEY}: numerics-lab gate is wedged' in body
    assert f'by key {KEY}, ended' in body  # who opened it
    assert 'opened 20' in body  # the window: when it opened and when it ended
    assert 'ended 20' in body


def test_reaching_the_cap_ends_the_wave_and_sends_its_summary(host: Host) -> None:
    host.open(max_merges=2)
    host.merge()
    assert host.alerts == []
    host.merge(pr=8)
    assert _titles(host) == [_summary(host)]
    assert 'audit' in host.ask('status')  # ended, not open
    host.ask('close')
    host.server.tick()
    assert len(host.alerts) == 1


@pytest.mark.parametrize('merged', [True, False])
def test_an_expired_wave_sends_its_summary_only_if_it_merged(host: Host, *, merged: bool) -> None:
    host.open(hours=1)
    if merged:
        host.merge()
    host.later(HOUR + 1)
    host.server.tick()
    assert _titles(host) == ([_summary(host)] if merged else [])
    assert _outcomes(host)[-1] == ('summarized' if merged else 'closed')


def test_closing_an_empty_wave_alerts_nothing_and_is_audited(host: Host) -> None:
    host.open()
    host.ask('close')
    host.server.tick()
    assert host.alerts == []
    assert _outcomes(host) == ['opened', 'closed']


def test_the_summary_is_sent_once_however_often_the_tick_runs(host: Host) -> None:
    host.open()
    host.merge()
    host.ask('close')
    for _ in range(3):
        host.later(24 * HOUR)
        host.server.tick()
    assert _titles(host) == [_summary(host)]  # no reminders either: one wave, one message


def test_a_summary_no_channel_delivered_is_resent_by_the_next_tick_only(host: Host) -> None:
    host.open()
    host.merge()
    host.delivers = False
    host.ask('close')
    host.server.tick()
    assert _titles(host) == [_summary(host)] * 2  # tried on close, retried by the tick
    host.delivers = True
    host.server.tick()
    host.server.tick()
    assert _titles(host) == [_summary(host)] * 3  # delivered once, then never again


def test_a_raising_channel_is_a_failed_delivery_retried_next_tick(host: Host) -> None:
    host.open()
    host.merge()
    server = host.server

    def broken(_title: str, _body: str) -> bool:
        unreachable = 'telegram unreachable'
        raise OSError(unreachable)

    server.alert = broken
    server.handle(json.dumps({'action': 'close'}))
    host.server.tick()
    assert _titles(host) == [_summary(host)]
    assert _outcomes(host).count('summarized') == 1


def test_planted_control_a_wave_marked_summarized_is_never_resent(host: Host) -> None:
    host.open()
    host.merge()
    host.delivers = False
    host.ask('close')
    assert host.config.breakglass is not None
    state = Path(host.config.breakglass.state) / 'waves' / f'{_wave_id(host)}.json'
    data = json.loads(state.read_text(encoding='utf-8'))
    assert data['summarized'] is None  # control: the failed delivery left it unmarked ...
    data['summarized'] = NOW
    state.write_text(json.dumps(data), encoding='utf-8')
    host.delivers = True
    host.server.tick()
    assert _titles(host) == [_summary(host)]  # ... and the mark alone stops the resend


def test_the_summary_carries_no_secret(host: Host) -> None:
    host.open()
    host.merge()
    host.ask('close')
    assert host.config.breakglass is not None
    body = host.alerts[0][1]
    assert host.config.consent is not None
    secrets = [host.config.consent.totp, *host.config.breakglass.tokens.values()]
    for path in (Path(name) for name in secrets):
        if path.is_file():
            assert path.read_text(encoding='utf-8').strip() not in body
    assert host.code() not in body


def test_a_wave_written_before_summaries_reads_as_already_summarized(host: Host) -> None:
    host.open()
    host.merge()
    host.delivers = False
    host.ask('close')
    assert host.config.breakglass is not None
    state = Path(host.config.breakglass.state) / 'waves' / f'{_wave_id(host)}.json'
    data = json.loads(state.read_text(encoding='utf-8'))
    del data['summarized'], data['key']
    data['reminded'] = None  # the earlier format: it alerted on close and reminded
    state.write_text(json.dumps(data), encoding='utf-8')
    host.delivers = True
    host.server.tick()
    assert _titles(host) == [_summary(host)]  # the close's try only: an old wave is never re-alerted


def _merged_lines(host: Host) -> list[dict[str, object]]:
    assert host.config.breakglass is not None
    lines = Path(host.config.breakglass.log).read_text(encoding='utf-8').splitlines()
    return [json.loads(line) for line in lines if json.loads(line)['outcome'] == 'merged']


def _comments(host: Host) -> list[str]:
    return [str(call[2]) for call in host.forge.calls if call[0] == 'comment']


def test_an_untested_head_merges_in_an_open_wave_and_says_untested(host: Host) -> None:
    # User ruling 2026-11-11: break-glass bypasses the tests too -- and the audit says so.
    host.forge.posted = [CommitStatus('pr-current', 'failure', 'stale lock', '')]
    host.open()
    said = host.merge()
    assert 'merged untested' in said
    assert [call for call in host.forge.calls if call[0] == 'merge']
    (line,) = _merged_lines(host)
    assert str(line['tests']).startswith('untested: ')
    assert 'tests/security is not yet judged' in str(line['tests'])
    assert any('merged untested' in body for body in _comments(host))


def test_planted_control_the_same_untested_head_without_a_wave_is_refused(host: Host) -> None:
    host.forge.posted = [CommitStatus('pr-current', 'failure', 'stale lock', '')]
    with pytest.raises(BreakglassRefused, match='no break-glass wave is open'):
        host.merge()
    assert not [call for call in host.forge.calls if call[0] == 'merge']
    assert not _merged_lines(host)


def test_a_red_head_merges_with_its_reds_named(host: Host) -> None:
    host.forge.posted = [GREEN[1], CommitStatus('tests/base', 'failure', 'VERDICT result=fail', '')]
    host.open()
    assert 'merged red (tests/base)' in host.merge()
    (line,) = _merged_lines(host)
    assert str(line['tests']).startswith('red: tests/base; ')
    assert any('merged red (tests/base)' in body for body in _comments(host))
    host.ask('close')
    assert 'red: tests/base' in host.alerts[-1][1]  # the wave's one summary names it too


def test_every_declared_test_green_merges_as_passed(host: Host) -> None:
    host.open()
    assert 'merged' in host.merge()
    assert [line['tests'] for line in _merged_lines(host)] == ['passed']
