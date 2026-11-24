"""The HTTPS door: one protocol, two transports -- the same key, the same serve line, refusals that name their door.

PLANTED CONTROLS for the admission (each next to the green it would otherwise fake): a bad signature, an undeclared
key, a replayed nonce, a stale time and a request signed before the relay started are each refused, while the same
envelope correctly signed by a declared key passes.
"""

from __future__ import annotations

import http.client
import json
import shutil
import subprocess
import sys
import threading
import time
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from dev_lab.dev import devschema
from dev_lab.ops import httpsclient, httpsdoor, install
from dev_lab.ops.access import keys_file
from dev_lab.ops.caddy import Door, doors_routed
from dev_lab.ops.config import load
from dev_lab.ops.consent import door
from dev_lab.ops.consent.door import endpoint_send, reach
from dev_lab.ops.httpsclient import https_send
from dev_lab.ops.httpsdoor import Gate, HttpsDoor, Refused, envelope, ssh_sign, ssh_verify
from dev_lab.ops.sshkey import ENV as AUTH_ENV
from dev_lab.ops.sshkey import fingerprint as auth_fingerprint

NOW = 1_800_000_000.0
PEER = '192.0.2.7'
DOOR = HttpsDoor(https_port=8792, https_site='g.example', https_attempts=3)
LINE = '{"verb": "hello"}'


def _keygen(where: Path, name: str) -> tuple[Path, str]:
    """A fresh ed25519 key pair at *where*/*name*: (private key path, public key line)."""
    private = where / name
    argv = [str(shutil.which('ssh-keygen')), '-q', '-t', 'ed25519', '-N', '', '-C', f'{name}@test', '-f', str(private)]
    subprocess.run(argv, check=True, capture_output=True)
    return private, private.with_name(name + '.pub').read_text(encoding='utf-8').strip()


@pytest.fixture(scope='module')
def keys(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[Path, str]]:
    assert shutil.which('ssh-keygen'), 'ssh-keygen is the signer and verifier of the door (OpenSSH >= 8.1)'
    where = tmp_path_factory.mktemp('keys')
    return {name: _keygen(where, name) for name in ('declared', 'stranger')}


class Clock:
    def __init__(self) -> None:
        """Start at NOW."""
        self.now = NOW

    def __call__(self) -> float:
        return self.now


def _gate(keys: dict[str, tuple[Path, str]], clock: Clock, role: str = 'consent') -> Gate:
    return Gate(role, lambda: [keys['declared'][1]], DOOR, now=clock)


def _signed(keys: dict[str, tuple[Path, str]], who: str = 'declared', *, role: str = 'consent', at: float = NOW,
            line: str = LINE, nonce: str = '') -> dict[str, Any]:  # fmt: skip
    private, public = keys[who]
    return envelope(role, line, public, ssh_sign(str(private)), now=at, nonce=nonce)


# --- admission: the planted controls ----------------------------------------------------------------------------------


def test_a_declared_key_signing_a_fresh_request_is_admitted(keys: dict[str, tuple[Path, str]]) -> None:
    assert _gate(keys, Clock()).verified(_signed(keys), PEER) == (keys['declared'][1], LINE)


def test_a_bad_signature_is_refused(keys: dict[str, tuple[Path, str]]) -> None:
    tampered = _signed(keys) | {'line': '{"verb": "issue", "code": "000000"}'}
    with pytest.raises(Refused, match='signature does not verify'):
        _gate(keys, Clock()).verified(tampered, PEER)
    forged = _signed(keys, 'stranger') | {'key': keys['declared'][1]}  # a stranger's signature naming the declared key
    with pytest.raises(Refused, match='signature does not verify'):
        _gate(keys, Clock()).verified(forged, PEER)


def test_an_undeclared_key_is_refused_naming_its_declaration(keys: dict[str, tuple[Path, str]]) -> None:
    with pytest.raises(Refused, match=r'not declared for consent.*\[dev\] client_keys'):
        _gate(keys, Clock()).verified(_signed(keys, 'stranger'), PEER)


def test_a_replay_is_refused(keys: dict[str, tuple[Path, str]]) -> None:
    gate, sent = _gate(keys, Clock()), _signed(keys)
    gate.verified(sent, PEER)
    with pytest.raises(Refused, match='nonce was already used'):
        gate.verified(sent, PEER)


def test_a_stale_request_and_one_signed_before_the_relay_started_are_refused(keys: dict[str, tuple[Path, str]]) -> None:
    clock = Clock()
    with pytest.raises(Refused, match='replay is refused'):
        _gate(keys, clock).verified(_signed(keys, at=NOW - httpsdoor.SKEW_S - 1), PEER)
    early = _signed(keys, at=NOW - 30)
    clock.now = NOW + 60  # the relay restarted: its nonce memory is gone, its start bounds the window
    restarted = Gate('consent', lambda: [keys['declared'][1]], DOOR, now=clock)
    with pytest.raises(Refused, match='before'):
        restarted.verified(early, PEER)


def test_a_consent_signature_never_opens_break_glass(keys: dict[str, tuple[Path, str]]) -> None:
    with pytest.raises(Refused, match='signature does not verify'):
        _gate(keys, Clock(), role='breakglass').verified(_signed(keys, role='consent'), PEER)


def test_repeated_refusals_lock_the_peer_and_a_lock_refuses_even_a_good_request(
    keys: dict[str, tuple[Path, str]],
) -> None:
    clock, stranger = Clock(), _signed(keys, 'stranger')
    gate = _gate(keys, clock)
    for _ in range(DOOR.https_attempts + 1):
        with pytest.raises(Refused, match='not declared'):
            gate.verified(stranger, PEER)
    with pytest.raises(Refused, match='locked'):
        gate.verified(_signed(keys), PEER)
    assert gate.verified(_signed(keys), '198.51.100.9')  # PLANTED CONTROL: another peer is not locked
    clock.now += DOOR.https_lock_minutes * 60 + 1
    assert gate.verified(_signed(keys, at=clock.now), PEER)


def test_the_verifier_is_ssh_keygen_and_rejects_another_namespace(keys: dict[str, tuple[Path, str]]) -> None:
    private, public = keys['declared']
    sig = ssh_sign(str(private))(b'm', 'dev-lab-consent')
    assert ssh_verify(public, b'm', sig, 'dev-lab-consent')
    assert not ssh_verify(public, b'm', sig, 'dev-lab-breakglass')
    assert not ssh_verify(public, b'n', sig, 'dev-lab-consent')


# --- the relay: an admitted line runs the ssh path's serve, as the verified key ---------------------------------------


@pytest.fixture
def relay(keys: dict[str, tuple[Path, str]]) -> Iterator[tuple[int, list[tuple[str, str]]]]:
    seen: list[tuple[str, str]] = []

    def run(line: str, key: str) -> tuple[int, str]:
        seen.append((line, key))
        return 0, 'answered'

    server = httpsdoor.relay(0, Gate('consent', lambda: [keys['declared'][1]], DOOR), run, serve_forever=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], seen
    finally:
        server.shutdown()
        server.server_close()


def _post(port: int, path: str, body: bytes) -> tuple[int, dict[str, Any]]:
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=30)
    conn.request('POST', path, body=body, headers={'X-Dev-Lab-Peer': PEER})
    answer = conn.getresponse()
    return answer.status, json.loads(answer.read())


def test_the_relay_listens_on_loopback_only(keys: dict[str, tuple[Path, str]]) -> None:
    server = httpsdoor.relay(0, _gate(keys, Clock()), lambda _l, _k: (0, ''), serve_forever=False)
    try:
        assert server.server_address[0] == '127.0.0.1'
    finally:
        server.server_close()


def test_the_relay_runs_an_admitted_line_and_refuses_the_rest_before_running(
    keys: dict[str, tuple[Path, str]], relay: tuple[int, list[tuple[str, str]]],
) -> None:  # fmt: skip
    port, seen = relay

    good = json.dumps(_signed(keys, at=time.time())).encode()
    assert _post(port, '/dev-lab/consent', good) == (200, {'status': 0, 'output': 'answered'})
    assert seen == [(LINE + '\n', keys['declared'][1])]
    status, said = _post(port, '/dev-lab/consent', good)  # replayed
    assert (status, said['status']) == (403, 2)
    assert 'already used' in said['output']
    status, said = _post(port, '/dev-lab/consent', json.dumps(_signed(keys, 'stranger', at=time.time())).encode())
    assert status == 403
    assert 'not declared' in said['output']
    assert _post(port, '/dev-lab/breakglass', good)[0] == 404
    assert len(seen) == 1, 'nothing refused reached the serve verb'


def test_sudo_run_hands_serve_the_key_as_sshds_own_record(keys: dict[str, tuple[Path, str]], tmp_path: Path) -> None:
    probe = tmp_path / 'probe.py'
    probe.write_text(
        'import os, sys\nfrom pathlib import Path\n'
        f'print(Path(os.environ[{AUTH_ENV!r}]).read_text().strip(), sys.stdin.read().strip())\n',
        encoding='utf-8',
    )

    status, said = httpsdoor.sudo_run([sys.executable, str(probe)])(LINE + '\n', keys['declared'][1])
    assert status == 0
    record, line = said.split('\n', 1)[0], said.strip().split(' ', 3)[-1]
    kind, blob = keys['declared'][1].split()[:2]
    assert record.startswith(f'publickey {kind} {blob}')
    assert line == LINE
    auth = tmp_path / 'auth'
    auth.write_text(f'publickey {kind} {blob}\n', encoding='utf-8')
    assert auth_fingerprint(str(auth)) == httpsdoor.fingerprint(keys['declared'][1])  # the ssh path's fingerprint


# --- the client -------------------------------------------------------------------------------------------------------


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


def _table(keys: dict[str, tuple[Path, str]], role: str = 'consent') -> dict[str, str]:
    return {'https': f'https://g.example/dev-lab/{role}', 'identity': str(keys['declared'][0])}


def test_https_send_posts_an_envelope_the_gate_admits(keys: dict[str, tuple[Path, str]]) -> None:
    conn = FakeConn(200, json.dumps({'status': 2, 'output': 'refused: x'}).encode())
    assert https_send(_table(keys), {'verb': 'hello'}, connect=lambda _h, _p: conn, now=lambda: NOW) == (
        2,
        'refused: x',
    )
    ((method, path, body),) = conn.sent
    assert (method, path) == ('POST', '/dev-lab/consent')
    sent = json.loads(body)
    assert json.loads(sent['line']) == {'verb': 'hello'}
    assert _gate(keys, Clock()).verified(sent, PEER) == (keys['declared'][1], LINE)


def test_https_send_names_its_doors(keys: dict[str, tuple[Path, str]], tmp_path: Path) -> None:
    status, said = https_send(_table(keys), {}, connect=lambda _h, _p: FakeConn(403, b'forbidden'))
    assert (status, 'outside the forge allowlist' in said) == (2, True)

    def down(_h: str, _p: int) -> FakeConn:
        unreachable = 'no route'
        raise OSError(unreachable)

    assert https_send(_table(keys), {}, connect=down)[0] == httpsdoor.UNREACHABLE
    assert https_send({'https': 'http://g.example/dev-lab/consent'}, {})[0] == 2  # plain http is never sent
    status, said = https_send({'https': 'https://g.example/dev-lab/consent', 'identity': str(tmp_path / 'none')}, {})
    assert (status, 'bringup' in said) == (2, True)


def test_a_pin_mismatch_refuses_before_anything_is_sent(
    keys: dict[str, tuple[Path, str]], monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    monkeypatch.setattr(httpsclient, 'spki_pin', lambda der: f'sha256/{der.decode()}')
    table = _table(keys) | {'https_pin': 'sha256/declared'}
    conn = FakeConn(200, json.dumps({'status': 0, 'output': 'ok'}).encode(), der=b'rotated')
    assert https_send(table, {}, connect=lambda _h, _p: conn)[0] == httpsdoor.UNREACHABLE
    assert conn.sent == []
    good = FakeConn(200, json.dumps({'status': 0, 'output': 'ok'}).encode(), der=b'declared')
    assert https_send(table, {}, connect=lambda _h, _p: good) == (0, 'ok')  # PLANTED CONTROL: the pinned key


def test_endpoint_send_follows_the_declared_reach(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(door, 'https_send', lambda _table, _request: (0, 'https'))
    monkeypatch.setattr(door, 'ssh_send', lambda _table, _request: (0, 'ssh'))
    both = {'https': 'https://g/dev-lab/consent', 'endpoint': 'c@h'}
    assert endpoint_send(both, {}, via=['https']) == (0, 'https')
    assert endpoint_send(both, {}, via=['ssh']) == (0, 'ssh')
    assert endpoint_send(both, {}, via=['https', 'ssh']) == (0, 'https')
    assert endpoint_send({'endpoint': 'c@h'}, {}, via=['https', 'ssh']) == (0, 'ssh')
    status, said = endpoint_send({'endpoint': 'c@h'}, {}, via=['https'])
    assert (status, 'forge_reach' in said) == (2, True)
    assert reach({}) == ('ssh',)  # undeclared is ssh
    assert reach({'devhost': {'forge_reach': ['https']}}) == ('https',)


@pytest.mark.parametrize('declared', ['["https"]', '["https", "ssh"]', '["ssh"]'])
def test_forge_reach_is_a_host_fact_checked_by_name(declared: str) -> None:
    assert devschema._shape(tomllib.loads(f'forge_reach = {declared}'), '[dev]') == []


@pytest.mark.parametrize('declared', ['[]', '["smtp"]', '["https", "https"]', '"https"'])
def test_a_forge_reach_that_names_no_transport_is_refused(declared: str) -> None:
    assert any('forge_reach' in line for line in devschema._shape(tomllib.loads(f'forge_reach = {declared}'), '[dev]'))
    assert 'forge_reach' in devschema.HOST_ONLY


# --- Caddy, config and install: the door sits behind the allowlist, fail closed ---------------------------------------

CADDYFILE = (
    'g.example {\n\t@campus remote_ip 192.0.2.0/24\n\thandle @campus {\n\t\treverse_proxy 127.0.0.1:3000\n\t}\n'
    '\trespond 403\n}\nopen.example {\n\trespond 200\n}\n'
)
ALLOW = ('203.0.113.0/24',)


def test_a_door_route_refuses_outside_the_allowlist_before_it_proxies() -> None:
    text = doors_routed(CADDYFILE, [Door('g.example', '/dev-lab/consent', 8792)], allow=ALLOW)
    route = text[text.index('handle /dev-lab/consent') :]
    assert route.index('not remote_ip 203.0.113.0/24') < route.index('respond @dev_lab_door_outside 403')
    assert route.index('respond @dev_lab_door_outside 403') < route.index('reverse_proxy 127.0.0.1:8792')
    assert 'header_up X-Dev-Lab-Peer {remote_host}' in route
    assert doors_routed(text, [Door('g.example', '/dev-lab/consent', 8792)], allow=ALLOW) == text  # idempotent
    assert doors_routed(text, [], allow=ALLOW) == CADDYFILE  # undeclared: the route is removed


def test_a_door_in_a_site_the_allowlist_does_not_govern_is_refused() -> None:
    with pytest.raises(ValueError, match='not an allowlisted site'):
        doors_routed(CADDYFILE, [Door('open.example', '/dev-lab/consent', 8792)], allow=ALLOW)
    with pytest.raises(ValueError, match='not a site'):
        doors_routed(CADDYFILE, [Door('absent.example', '/dev-lab/consent', 8792)], allow=ALLOW)


def _ops(tmp_path: Path, body: str) -> Path:
    path = tmp_path / 'ops.toml'
    path.write_text(f'[ops]\nhome = "/h"\npython = "/p"\n{body}', encoding='utf-8')
    return path


CONSENT = '[ops.consent]\naccount = "consent"\ntotp = "/t"\nkey = "/k"\nstate = "/s"\nhttps_port = 8792\n'
CADDY = '[ops.caddy]\nallow = ["203.0.113.0/24"]\nsites = ["g.example"]\n'


def test_config_accepts_https_port_only_behind_the_allowlist(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r'needs \[ops.caddy\]'):
        load(_ops(tmp_path, CONSENT + 'https_site = "g.example"\n'), structure_only=True)
    with pytest.raises(ValueError, match='not an allowlisted'):
        load(_ops(tmp_path, CONSENT + 'https_site = "open.example"\n' + CADDY), structure_only=True)
    with pytest.raises(ValueError, match='without https_site'):
        load(_ops(tmp_path, CONSENT + CADDY), structure_only=True)
    found = load(_ops(tmp_path, CONSENT + 'https_site = "g.example"\n' + CADDY), structure_only=True)
    assert found.consent is not None
    assert found.consent.https_port == 8792  # PLANTED CONTROL: inside the allowlisted site it loads


def test_install_renders_the_relay_on_the_ssh_paths_own_serve_and_keys(tmp_path: Path) -> None:
    found = load(_ops(tmp_path, CONSENT + 'https_site = "g.example"\n' + CADDY), structure_only=True)
    rendered = install.files(found)
    unit = rendered['etc/systemd/system/dev-lab-ops-consent-https.service']
    sudoers = rendered['etc/sudoers.d/dev-lab-ops-consent']
    serve = sudoers.split('NOPASSWD: ', 1)[1].strip()
    assert 'User=consent\n' in unit
    exec_start = next(line for line in unit.splitlines() if line.startswith('ExecStart='))
    assert f'--port 8792 --role consent --keys {keys_file("consent")} ' in exec_start  # the ssh key set, one file
    assert exec_start.endswith(f'-- sudo -n {serve}'), 'the relay runs the ForceCommand serve line, verbatim'
    assert sudoers.count('NOPASSWD') == 1, 'the relay sudoes the ForceCommand line, no second grant'
    assert install.https_doors(found) == [Door('g.example', '/dev-lab/consent', 8792)]
    assert any('dev-lab-ops-consent-https.service' in step for step in install._https_steps(found))
    without = load(_ops(tmp_path, CONSENT.replace('https_port = 8792\n', '') + CADDY), structure_only=True)
    assert install._https_steps(without) == []
    assert not any(path.endswith('-https.service') for path in install.files(without))
