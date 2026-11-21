"""The HTTPS door (dev_lab.ops.httpsdoor): consent and break-glass without a client key, behind the Caddy allowlist.

User directive and ruling 2026-11-21: a workstation opens break-glass by itself with dev-lab + the user's code; the
door authorizes by TOTP / signed credential only, sits behind ``[ops.caddy] allow`` (fail closed), throttles every
code-taking peer (rate limit + lockout + alert), and its relay listens on 127.0.0.1 only. Every refusal here has a
planted control beside it that passes.
"""

from __future__ import annotations

import dataclasses
import http.client
import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from _ops_fixtures import ALPHA, NOW, config
from test_ops_breakglass import HEAD, Host

from dev_lab.dev import forgebreakglass
from dev_lab.ops import httpsdoor, install
from dev_lab.ops.breakglass import Server, Throttled, Unauthorized
from dev_lab.ops.caddy import Door, doors_routed
from dev_lab.ops.config import load
from dev_lab.ops.consent import door, serve
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.consent.door import endpoint_send
from dev_lab.ops.forcecommand import files as forced
from dev_lab.ops.httpsdoor import PEER_ENV, HttpsDoor, Throttle, https_send

PEER = '128.243.1.2'
DOOR = HttpsDoor(https_port=8781, https_site='g.example', https_attempts=3)


class Clock:
    def __init__(self) -> None:
        """Start at the fixtures' NOW."""
        self.now = NOW

    def __call__(self) -> float:
        return self.now


def _throttle(tmp_path: Path, alerts: list[tuple[str, float]], clock: Clock) -> Throttle:
    return Throttle(tmp_path, DOOR, now=clock, on_lock=lambda who, until: alerts.append((who, until)),
                    refused=ConsentRefused)  # fmt: skip


# --- the throttle: rate limit + lockout + one alert ------------------------------------------------------------------


def test_the_attempt_past_the_allowance_locks_the_peer_and_alerts_once(tmp_path: Path) -> None:
    alerts: list[tuple[str, float]] = []
    clock = Clock()
    guard = _throttle(tmp_path, alerts, clock)
    for _ in range(DOOR.https_attempts):  # PLANTED CONTROL: the allowance itself passes
        guard.strike(PEER)
    with pytest.raises(ConsentRefused, match=f'too many attempts from {PEER}'):
        guard.strike(PEER)
    assert [who for who, _ in alerts] == [PEER]
    with pytest.raises(ConsentRefused, match='too many attempts'):
        guard.check(PEER)  # locked: every request refused ...
    assert len(alerts) == 1  # ... and the lockout alerted once, when it began
    guard.check('128.243.9.9')  # PLANTED CONTROL: another peer is not locked by this one
    clock.now += DOOR.https_lock_minutes * 60 + 1
    guard.check(PEER)  # the lockout ends


def test_attempts_outside_the_window_do_not_add_up(tmp_path: Path) -> None:
    clock = Clock()
    guard = _throttle(tmp_path, [], clock)
    for _ in range(DOOR.https_attempts * 3):
        guard.strike(PEER)
        clock.now += DOOR.https_window_minutes * 60 / DOOR.https_attempts + 1


def test_a_door_that_lies_is_refused_at_load() -> None:
    with pytest.raises(ValueError, match='not a TCP port'):
        HttpsDoor(https_port=70000, https_site='g')
    with pytest.raises(ValueError, match='without https_site'):
        HttpsDoor(https_port=8781)
    with pytest.raises(ValueError, match='rate limit'):
        HttpsDoor(https_port=8781, https_site='g', https_attempts=0)
    assert HttpsDoor().https_port == 0  # PLANTED CONTROL: undeclared is no door, not an error


# --- the relay: 127.0.0.1 only, one JSON line, the peer Caddy saw ----------------------------------------------------


@pytest.fixture
def relay() -> Iterator[tuple[int, list[tuple[str, str]]]]:
    seen: list[tuple[str, str]] = []

    def run(line: str, who: str) -> tuple[int, str]:
        seen.append((line, who))
        return 0, 'answered'

    server = httpsdoor.relay(0, '/dev-lab/consent', run, serve_forever=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], seen
    finally:
        server.shutdown()
        server.server_close()


def _post(port: int, path: str, body: bytes, headers: dict[str, str] | None = None) -> tuple[int, dict[str, Any]]:
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    conn.request('POST', path, body=body, headers=headers or {})
    answer = conn.getresponse()
    return answer.status, json.loads(answer.read())


def test_the_relay_listens_on_loopback_only() -> None:
    server = httpsdoor.relay(0, '/dev-lab/consent', lambda _l, _p: (0, ''), serve_forever=False)
    try:
        assert server.server_address[0] == '127.0.0.1'
    finally:
        server.server_close()


def test_the_relay_runs_one_line_for_the_peer_caddy_named(relay: tuple[int, list[tuple[str, str]]]) -> None:
    port, seen = relay
    status, said = _post(port, '/dev-lab/consent', b'{"verb": "hello"}', {'X-Dev-Lab-Peer': PEER})
    assert (status, said) == (200, {'status': 0, 'output': 'answered'})
    assert seen == [('{"verb": "hello"}\n', PEER)]


def test_the_relay_refuses_another_path_two_lines_and_an_empty_body(relay: tuple[int, list[tuple[str, str]]]) -> None:
    port, seen = relay
    assert _post(port, '/elsewhere', b'{}')[0] == 404
    assert _post(port, '/dev-lab/consent', b'{}\n{}')[0] == 400
    assert _post(port, '/dev-lab/consent', b'')[0] == 413
    assert seen == []  # nothing reached the serve verb


# --- the client: system trust, optional pin, refusals that name their door -------------------------------------------


class FakeConn:
    def __init__(self, status: int, body: bytes, der: bytes = b'') -> None:
        """Answer *status* and *body*; the peer certificate is *der*."""
        self.status, self.body, self.sent = status, body, []
        self.sock = type('Sock', (), {'getpeercert': lambda _self, **_flags: der})()

    def connect(self) -> None:
        return None

    def close(self) -> None:
        return None

    def request(self, method: str, path: str, *, body: bytes, headers: dict[str, str]) -> None:
        del headers
        self.sent.append((method, path, body))

    def getresponse(self) -> FakeConn:
        return self

    def read(self) -> bytes:
        return self.body


def test_https_send_posts_one_line_and_returns_the_door_answer() -> None:
    conn = FakeConn(200, json.dumps({'status': 2, 'output': 'refused: x'}).encode())
    table = {'https': 'https://g.example/dev-lab/consent'}
    assert https_send(table, {'verb': 'hello'}, connect=lambda _h, _p: conn) == (2, 'refused: x')
    assert conn.sent == [('POST', '/dev-lab/consent', b'{"verb": "hello"}\n')]


def test_https_send_names_the_allowlist_on_403_and_the_door_when_unreachable() -> None:
    table = {'https': 'https://g.example/dev-lab/consent'}
    status, said = https_send(table, {}, connect=lambda _h, _p: FakeConn(403, b'forbidden'))
    assert status == 2
    assert 'outside the forge allowlist' in said

    def down(_h: str, _p: int) -> FakeConn:
        unreachable = 'no route'
        raise OSError(unreachable)

    status, said = https_send(table, {}, connect=down)
    assert status == httpsdoor.UNREACHABLE
    assert 'ssh endpoint' in said
    assert https_send({'https': 'http://g.example/x'}, {})[0] == 2  # plain http is never sent


def test_a_pin_mismatch_refuses_before_anything_is_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpsdoor, 'spki_pin', lambda der: f'sha256/{der.decode()}')
    conn = FakeConn(200, json.dumps({'status': 0, 'output': 'ok'}).encode(), der=b'rotated')
    table = {'https': 'https://g.example/dev-lab/consent', 'https_pin': 'sha256/declared'}
    status, said = https_send(table, {}, connect=lambda _h, _p: conn)
    assert status == httpsdoor.UNREACHABLE
    assert 'https_pin' in said
    assert conn.sent == []
    good = FakeConn(200, json.dumps({'status': 0, 'output': 'ok'}).encode(), der=b'declared')
    assert https_send(table, {}, connect=lambda _h, _p: good) == (0, 'ok')  # PLANTED CONTROL: the pinned key


def test_endpoint_send_prefers_https_keeps_ssh_and_names_the_table_when_neither(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(door, 'https_send', lambda _table, _request: (0, 'https'))
    monkeypatch.setattr(door, 'ssh_send', lambda _table, _request: (0, 'ssh'))
    assert endpoint_send({'https': 'https://g/x', 'endpoint': 'c@h'}, {}) == (0, 'https')
    assert endpoint_send({'endpoint': 'c@h'}, {}) == (0, 'ssh')  # ssh stays selectable
    status, said = endpoint_send({}, {})
    assert status == 2
    assert '[consent]/[breakglass]' in said


# --- the consent issuer over HTTPS ------------------------------------------------------------------------------------


@pytest.fixture
def glass(tmp_path: Path) -> Host:
    return Host(config(tmp_path, [], extra='wave_hours_max = 4.0'))


def _guard(host: Host, alerts: list[tuple[str, float]], refused: type[Exception]) -> Throttle:
    state = Path(host.config.consent.state) if refused is ConsentRefused else Path(host.config.breakglass.state)
    return Throttle(state, DOOR, now=host._now, on_lock=lambda who, until: alerts.append((who, until)),
                    refused=refused)  # fmt: skip


def test_fetch_unspent_over_https_pays_a_code_and_over_ssh_none(glass: Host) -> None:
    line = json.dumps({'verb': 'fetch-unspent', 'plan': 'a' * 64})
    guard = _guard(glass, [], ConsentRefused)
    with pytest.raises(ConsentRefused, match='carries the code'):
        serve.handle(glass.issuer, line, https=guard, peer=PEER)
    with pytest.raises(ConsentRefused):
        serve.handle(glass.issuer, json.dumps({'verb': 'fetch-unspent', 'plan': 'a' * 64, 'code': '000000'}),
                     https=guard, peer=PEER)  # fmt: skip
    paid = json.dumps({'verb': 'fetch-unspent', 'plan': 'a' * 64, 'code': glass.code()})
    assert serve.handle(glass.issuer, paid, https=guard, peer=PEER) == '[]'  # PLANTED CONTROL: the code admits it
    assert serve.handle(glass.issuer, line) == '[]'  # ssh: the consent key admitted it, no code


def test_code_taking_verbs_lock_the_peer_even_for_a_right_code(glass: Host) -> None:
    alerts: list[tuple[str, float]] = []
    guard = _guard(glass, alerts, ConsentRefused)
    request = {'action': 'breakglass.wave', 'subject': 's', 'params': {'hours': 1, 'max_merges': 1}}
    wrong = json.dumps({'verb': 'issue', 'request': request, 'code': '000000'})
    for _ in range(DOOR.https_attempts):
        with pytest.raises(ConsentRefused):
            serve.handle(glass.issuer, wrong, https=guard, peer=PEER)
    right = json.dumps({'verb': 'issue', 'request': request, 'code': glass.code()})
    with pytest.raises(ConsentRefused, match='too many attempts'):
        serve.handle(glass.issuer, right, https=guard, peer=PEER)
    assert [who for who, _ in alerts] == [PEER]
    assert json.loads(serve.handle(glass.issuer, right, https=guard, peer='10.0.0.9'))['action'] == 'breakglass.wave'
    assert json.loads(serve.handle(glass.issuer, json.dumps({'verb': 'hello'}), https=guard, peer=PEER))['fields']


# --- break-glass over HTTPS: the wave's opening credential authorizes ------------------------------------------------


def _https(host: Host, alerts: list[tuple[str, float]] | None = None) -> Server:
    guard = _guard(host, [] if alerts is None else alerts, Throttled)
    return dataclasses.replace(host.server, https=guard, peer=PEER, key=f'https:{PEER}')


def _ask(server: Server, action: str, **fields: object) -> str:
    return server.handle(json.dumps({'action': action, **fields}))


def test_a_merge_over_https_needs_the_credential_that_opened_the_wave(glass: Host) -> None:
    opening = glass.grant()
    server = _https(glass)
    assert 'open for' in _ask(server, 'open', credential=opening)
    merge = {'repo': ALPHA, 'pr': 7, 'head': HEAD, 'reason': 'review-bot is down'}
    with pytest.raises(Unauthorized, match='carries the credential that opened the wave'):
        _ask(_https(glass), 'merge', **merge)
    other = glass.grant()  # a real, signed credential -- of no wave here
    with pytest.raises(Unauthorized, match='opened no break-glass wave'):
        _ask(_https(glass), 'merge', **merge, credential=other)
    forged = opening | {'subject': 'someone else'}
    with pytest.raises(Unauthorized, match='does not verify'):
        _ask(_https(glass), 'merge', **merge, credential=forged)
    assert glass.forge.calls == []
    assert 'merged' in _ask(_https(glass), 'merge', **merge, credential=opening)  # PLANTED CONTROL
    assert _ask(_https(glass), 'status').startswith('wave')  # a read: no credential


def test_ack_over_https_acknowledges_only_the_wave_its_credential_opened(glass: Host) -> None:
    opening = glass.grant()
    _ask(_https(glass), 'open', credential=opening)
    _ask(_https(glass), 'close', credential=opening)
    with pytest.raises(Unauthorized, match='not other'):
        _ask(_https(glass), 'ack', id='other', by='me', credential=opening)
    assert 'acknowledged by me' in _ask(_https(glass), 'ack', id='', by='me', credential=opening)


def test_failed_authorizations_lock_the_peer_and_the_lockout_alerts_once(glass: Host) -> None:
    alerts: list[tuple[str, float]] = []
    merge = {'repo': ALPHA, 'pr': 7, 'head': HEAD, 'reason': 'review-bot is down'}
    for _ in range(DOOR.https_attempts):
        with pytest.raises(Unauthorized):
            _ask(_https(glass, alerts), 'merge', **merge)
    with pytest.raises(Throttled):
        _ask(_https(glass, alerts), 'merge', **merge)
    with pytest.raises(Throttled):
        _ask(_https(glass, alerts), 'status')
    assert [who for who, _ in alerts] == [PEER]
    assert _ask(glass.server, 'status')  # PLANTED CONTROL: ssh (key-admitted) is not the throttled door


def test_over_ssh_a_merge_needs_no_credential(glass: Host) -> None:
    glass.open()
    assert 'merged' in glass.merge()


# --- Caddy: the door sits behind the allowlist, fail closed -----------------------------------------------------------

CADDYFILE = (
    'g.example {\n\t@campus remote_ip 10.0.0.0/8\n\thandle @campus {\n\t\treverse_proxy 127.0.0.1:3000\n\t}\n'
    '\trespond 403\n}\nopen.example {\n\trespond 200\n}\n'
)
ALLOW = ('128.243.0.0/16',)


def test_a_door_route_refuses_outside_the_allowlist_before_it_proxies() -> None:
    text = doors_routed(CADDYFILE, [Door('g.example', '/dev-lab/consent', 8781)], allow=ALLOW)
    route = text[text.index('handle /dev-lab/consent') :]
    assert route.index('not remote_ip 128.243.0.0/16') < route.index('respond @dev_lab_door_outside 403')
    assert route.index('respond @dev_lab_door_outside 403') < route.index('reverse_proxy 127.0.0.1:8781')
    assert 'header_up X-Dev-Lab-Peer {remote_host}' in route
    assert doors_routed(text, [Door('g.example', '/dev-lab/consent', 8781)], allow=ALLOW) == text  # idempotent
    assert doors_routed(text, [], allow=ALLOW) == CADDYFILE  # undeclared: the route is removed


def test_a_door_in_a_site_the_allowlist_does_not_govern_is_refused() -> None:
    with pytest.raises(ValueError, match='not an allowlisted site'):
        doors_routed(CADDYFILE, [Door('open.example', '/dev-lab/consent', 8781)], allow=ALLOW)
    with pytest.raises(ValueError, match='not a site'):
        doors_routed(CADDYFILE, [Door('absent.example', '/dev-lab/consent', 8781)], allow=ALLOW)


def _ops(tmp_path: Path, body: str) -> Path:
    path = tmp_path / 'ops.toml'
    path.write_text(f'[ops]\nhome = "/h"\npython = "/p"\n{body}', encoding='utf-8')
    return path


CONSENT = '[ops.consent]\naccount = "consent"\ntotp = "/t"\nkey = "/k"\nstate = "/s"\nhttps_port = 8781\n'


def test_config_refuses_a_door_outside_the_allowlisted_sites(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r'needs \[ops.caddy\]'):
        load(_ops(tmp_path, CONSENT + 'https_site = "g.example"\n'), structure_only=True)
    caddy = '[ops.caddy]\nallow = ["128.243.0.0/16"]\nsites = ["g.example"]\n'
    with pytest.raises(ValueError, match='not an allowlisted'):
        load(_ops(tmp_path, CONSENT + 'https_site = "open.example"\n' + caddy), structure_only=True)
    found = load(_ops(tmp_path, CONSENT + 'https_site = "g.example"\n' + caddy), structure_only=True)
    assert found.consent is not None
    assert found.consent.https_port == 8781  # PLANTED CONTROL: inside the allowlisted site it loads


def test_the_relay_may_sudo_only_the_https_serve_keeping_only_the_peer() -> None:
    rendered = forced('u', 'consent', (), 'ops consent serve', 'ops consent serve --https')
    sudoers = rendered['etc/sudoers.d/u-consent']
    assert f'env_keep += "{PEER_ENV}"' in sudoers
    assert 'NOPASSWD: ops consent serve --https\n' in sudoers
    assert PEER_ENV not in forced('u', 'consent', (), 'ops consent serve')['etc/sudoers.d/u-consent']


def test_install_renders_the_relay_unit_as_the_account_and_starts_it(tmp_path: Path) -> None:
    caddy = '[ops.caddy]\nallow = ["128.243.0.0/16"]\nsites = ["g.example"]\n'
    found = load(_ops(tmp_path, CONSENT + 'https_site = "g.example"\n' + caddy), structure_only=True)
    rendered = install.files(found)
    unit = rendered['etc/systemd/system/dev-lab-ops-consent-https.service']
    assert 'User=consent\n' in unit
    assert '--port 8781 --role consent -- sudo -n' in unit
    assert 'consent serve --https' in unit
    assert install.https_doors(found) == [Door('g.example', '/dev-lab/consent', 8781)]
    assert 'systemctl enable --now dev-lab-ops-consent-https.service' in install._https_steps(found)
    assert install._https_steps(dataclasses.replace(found, consent=None)) == []


# --- the client of the waves --------------------------------------------------------------------------------------


def test_a_workstation_that_did_not_open_the_wave_is_told_its_door(tmp_path: Path) -> None:
    sent: list[dict[str, Any]] = []

    def send(_table: object, request: dict[str, Any]) -> tuple[int, str]:
        sent.append(request)
        return 0, 'ok'

    table = {'https': 'https://g.example/dev-lab/breakglass'}
    assert forgebreakglass.wave_main(['close'], table=table, send=send, home=tmp_path) == 2
    assert sent == []
    assert forgebreakglass.wave_main(['close'], table={'endpoint': 'b@h'}, send=send, home=tmp_path) == 0  # ssh
    credential = {'id': 'c1', 'action': 'breakglass.wave'}
    forgebreakglass._opened(tmp_path, credential)  # what a successful open records
    sent.clear()
    assert forgebreakglass.wave_main(['close'], table=table, send=send, home=tmp_path) == 0
    assert sent[-1]['credential'] == credential


def test_the_peer_is_the_one_the_relay_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PEER_ENV, PEER)
    assert httpsdoor.peer() == PEER
    monkeypatch.delenv(PEER_ENV)
    assert httpsdoor.peer() == ''  # over ssh there is none
