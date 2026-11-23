"""THE HTTPS DOOR: the consent issuer and break-glass server reached over HTTPS, beside their ssh ForceCommand.

A workstation whose network lets it out only on 443 (port 22 blocked, 2026-11-23) cannot reach the ``consent@`` /
``breakglass@`` ssh logins. This door changes the TRANSPORT and nothing else: one protocol, two transports.

* AUTHENTICATION IS THE SAME KEY. The client signs each request with its own ssh client key
  (``ssh-keygen -Y sign``, :func:`ssh_sign`) -- the key its host file declares as ``[dev] client_keys``, which the
  forge derives into the role account's authorized-keys file (:mod:`dev_lab.ops.clientkeys`). The relay admits a
  request only when its key is IN THAT FILE (the one sshd reads), its signature verifies (:func:`ssh_verify`, the
  namespace binds the role), and its nonce and time are fresh (:class:`Gate`). No new secret exists.
* THE GRANT PATH IS THE SSH PATH. An admitted request runs the SAME serve command through the SAME sudoers line the
  ForceCommand uses, with ``SSH_USER_AUTH`` naming a record of the verified key in sshd's own format
  (:data:`dev_lab.ops.sshkey.ENV`). The role cannot tell the transports apart: its codes, lockouts, audit and
  recorded key fingerprint are the ssh path's, unchanged.
* :func:`relay` is the unit (``python -m dev_lab.ops.httpsdoor``), run as the role's restricted account on
  ``127.0.0.1:<https_port>`` only; Caddy routes the role's :data:`PATHS` entry of an allowlisted site to it
  (:func:`dev_lab.ops.caddy.doors_routed`). Failed admissions are throttled per peer and logged (no bodies).
* :func:`https_send` is the client (system trust store; ``https_pin`` optionally pins the server's SPKI).
  :func:`dev_lab.ops.consent.door.endpoint_send` picks it or ssh from the machine's declared ``forge_reach``.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import os
import secrets
import shutil
import ssl
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from lab_commons.log import emit

from dev_lab.ops.sshkey import ENV as AUTH_ENV

__all__ = [
    'BODY_MAX',
    'ENVELOPE',
    'PATHS',
    'SKEW_S',
    'Gate',
    'HttpsDoor',
    'Refused',
    'envelope',
    'https_send',
    'main',
    'relay',
    'signed_message',
    'spki_pin',
    'ssh_sign',
    'ssh_verify',
]

#: The URL path each role is served at, inside the allowlisted Caddy site.
PATHS: Final = {'consent': '/dev-lab/consent', 'breakglass': '/dev-lab/breakglass'}
#: The fields of one request envelope: the serve line, who signed it, when, a one-time nonce, the signature.
ENVELOPE: Final = ('line', 'key', 'time', 'nonce', 'sig')
#: The largest request body the relay reads: a plan of max_grants credentials fits many times over.
BODY_MAX: Final = 256 * 1024
#: How far a request's signed time may be from the relay's clock, either way.
SKEW_S: Final = 120.0
#: How long one request may run (a break-glass merge talks to a forge), the ssh transport's own bound.
TIMEOUT_S: Final = 180.0
#: The exit status a transport failure reports (ssh's own), so callers treat both transports alike.
UNREACHABLE: Final = 255
#: The exit status of a refusal (the serve verbs' own).
REFUSED: Final = 2
_PORT_MAX: Final = 65535
_NONCE_BYTES: Final = 16
#: OpenSSH's key tool (>= 8.1 for ``-Y``), resolved once: the signer and the verifier.
_KEYGEN: Final = shutil.which('ssh-keygen') or 'ssh-keygen'


def namespace(role: str) -> str:
    """The ``ssh-keygen -Y`` namespace of *role*'s door: a consent signature never opens break-glass."""
    return f'dev-lab-{role}'


@dataclass(frozen=True, kw_only=True)
class HttpsDoor:
    """A role's HTTPS door (mixed into ``[ops.consent]`` and ``[ops.breakglass]``); ``https_port = 0`` renders none.

    ``https_port`` is the relay's port on 127.0.0.1; ``https_site`` the ``[ops.caddy]`` site that routes
    :data:`PATHS` to it (it must be an allowlisted one). A peer may fail ``https_attempts`` admissions per
    ``https_window_minutes``; the one past that locks it out for ``https_lock_minutes``.
    """

    https_port: int = 0
    https_site: str = ''
    https_attempts: int = 5
    https_window_minutes: float = 15.0
    https_lock_minutes: float = 60.0

    def __post_init__(self) -> None:
        """Refuse a door that lies: a port outside 1..65535, no site, or a throttle that admits without bound."""
        if not self.https_port:
            return
        if (
            isinstance(self.https_port, bool)
            or not isinstance(self.https_port, int)
            or not 0 < self.https_port <= _PORT_MAX
        ):
            msg = f'https_port {self.https_port!r} is not a TCP port'
            raise ValueError(msg)
        if not self.https_site:
            msg = 'https_port is declared without https_site (the allowlisted [ops.caddy] site that routes it)'
            raise ValueError(msg)
        if not (self.https_attempts >= 1 and self.https_window_minutes > 0 and self.https_lock_minutes > 0):
            msg = 'https_attempts, https_window_minutes and https_lock_minutes must be positive (the failure throttle)'
            raise ValueError(msg)


# --- signing (both ends) --------------------------------------------------------------------------------------------


def signed_message(role: str, when: int, nonce: str, line: str) -> bytes:
    """What a request's signature covers: the role's path, the time, the nonce and the exact serve line."""
    return f'{PATHS[role]}\n{when}\n{nonce}\n{line}'.encode()


#: Signs ``(message, namespace)`` with this machine's client key; returns the armored ssh signature.
type Sign = Callable[[bytes, str], str]
#: ``(public key line, message, signature, namespace)`` -> whether the signature is that key's over that message.
type Verify = Callable[[str, bytes, str, str], bool]


def ssh_sign(identity: str) -> Sign:
    """A :data:`Sign` by ``ssh-keygen -Y sign`` with the private key *identity* (an agent holding it also works)."""

    def sign(message: bytes, ns: str) -> str:
        done = subprocess.run([_KEYGEN, '-q', '-Y', 'sign', '-f', identity, '-n', ns], input=message,
                              capture_output=True, check=False, timeout=60)  # fmt: skip
        if done.returncode or b'BEGIN SSH SIGNATURE' not in done.stdout:
            said = done.stderr.decode('utf-8', 'replace').strip()
            msg = f'ssh-keygen -Y sign with {identity} failed: {said or "no signature"}'
            raise Refused(msg)
        return done.stdout.decode()

    return sign


def _key_words(line: str) -> tuple[str, str]:
    parts = line.split()
    return (parts[0], parts[1]) if len(parts) >= 2 else ('', '')  # noqa: PLR2004 -- type, blob


def ssh_verify(key: str, message: bytes, sig: str, ns: str) -> bool:
    """Whether *sig* is *key*'s signature over *message* in *ns*, by ``ssh-keygen -Y verify`` against *key* alone."""
    kind, blob = _key_words(key)
    if not kind:
        return False
    with tempfile.TemporaryDirectory(prefix='dev-lab-door-') as scratch:
        allowed, signature = Path(scratch) / 'allowed', Path(scratch) / 'sig'
        allowed.write_text(f'door namespaces="{ns}" {kind} {blob}\n', encoding='utf-8')
        signature.write_text(sig, encoding='utf-8')
        argv = [_KEYGEN, '-Y', 'verify', '-f', str(allowed), '-I', 'door', '-n', ns, '-s', str(signature)]
        done = subprocess.run(argv, input=message, capture_output=True, check=False, timeout=60)
    return done.returncode == 0


def fingerprint(key: str) -> str:
    """The ``SHA256:`` fingerprint of a public key line (``ssh-keygen -l``'s form); ``''`` when it is not one."""
    try:
        raw = base64.b64decode(_key_words(key)[1], validate=True)
    except ValueError:
        return ''
    return 'SHA256:' + base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip('=') if raw else ''


def envelope(role: str, line: str, key: str, sign: Sign, *, now: float, nonce: str = '') -> dict[str, Any]:
    """The signed request carrying serve *line* for *role*, signed by the client *key* through *sign*."""
    when, once = int(now), nonce or secrets.token_hex(_NONCE_BYTES)
    return {'line': line, 'key': key, 'time': when, 'nonce': once,
            'sig': sign(signed_message(role, when, once, line), namespace(role))}  # fmt: skip


# --- the relay's admission ------------------------------------------------------------------------------------------


class Refused(Exception):
    """A request the door does not admit; the message names the cause and its door, never a body."""


@dataclass
class Gate:
    """Admits a signed envelope for *role* or raises :class:`Refused`: declared key, valid signature, fresh nonce.

    *keys* reads the role account's authorized-keys file -- the ssh transport's key set, re-read per request so an
    install takes effect without a restart. A nonce is remembered for the skew window; a request signed before the
    relay *started* is refused, so a restart opens no replay. Failures count against the peer (*door*'s bounds).
    """

    role: str
    keys: Callable[[], Sequence[str]]
    door: HttpsDoor
    now: Callable[[], float] = time.time
    verify: Verify = ssh_verify
    started: float = field(default=0.0)
    _seen: dict[str, float] = field(default_factory=dict)
    _fails: dict[str, list[float]] = field(default_factory=dict)
    _locked: dict[str, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        """Start the clock the replay window is bounded by."""
        self.started = self.started or self.now()

    def admit(self, body: object, peer: str) -> str:
        """The verified key line of *body* from *peer*; a failure strikes the peer and raises :class:`Refused`."""
        with self._lock:
            now = self.now()
            if now < self._locked.get(peer, 0.0):
                msg = (f'too many refused requests from {peer}: locked for {(self._locked[peer] - now) / 60:.0f} more '
                       'minute(s); fix the cause each refusal named, then wait')  # fmt: skip
                raise Refused(msg)
            try:
                return self._admitted(body, now)
            except Refused:
                self._strike(peer, now)
                raise

    def _strike(self, peer: str, now: float) -> None:
        window = self.door.https_window_minutes * 60
        seen = [at for at in self._fails.get(peer, []) if now - at < window] + [now]
        if len(seen) > self.door.https_attempts:
            self._locked[peer], seen = now + self.door.https_lock_minutes * 60, []
            emit(f'[httpsdoor] {self.role}: locked peer {peer}', err=True)
        self._fails[peer] = seen

    def _admitted(self, body: object, now: float) -> str:
        if not isinstance(body, dict) or set(body) != set(ENVELOPE):
            msg = f'a request is one JSON envelope of exactly {list(ENVELOPE)}: update dev-lab on the client'
            raise Refused(msg)
        line, key, when, nonce, sig = (body[name] for name in ENVELOPE)
        if not (isinstance(line, str) and isinstance(key, str) and isinstance(nonce, str) and isinstance(sig, str)
                and isinstance(when, int) and not isinstance(when, bool) and nonce):  # fmt: skip
            msg = 'the envelope fields are line/key/nonce/sig strings and an integer time'
            raise Refused(msg)
        declared = {_key_words(listed) for listed in self.keys()}
        print_ = fingerprint(key) or 'an unparsable key'
        if _key_words(key) not in declared or not _key_words(key)[0]:
            msg = (
                f"key {print_} is not declared for {self.role} on this forge: declare it as the machine's "
                '[dev] client_keys in its hosts-config host file, then apply ops.config and install on the forge'
            )
            raise Refused(msg)
        if not self.verify(key, signed_message(self.role, when, nonce, line), sig, namespace(self.role)):
            msg = (
                f'the signature does not verify for key {print_} over this request: it was altered, or signed by '
                "another key than the one it names (check this machine's [consent] identity)"
            )
            raise Refused(msg)
        if abs(now - when) > SKEW_S or when < self.started - SKEW_S / 2:
            msg = (
                f"the request was signed at {when}, outside {SKEW_S:.0f} s of the door's clock {now:.0f} (or before "
                "it started): a replay is refused; send a fresh request, and check this machine's clock if it repeats"
            )
            raise Refused(msg)
        self._seen = {once: at for once, at in self._seen.items() if now - at <= 2 * SKEW_S}
        if nonce in self._seen:
            msg = 'this nonce was already used: a replay is refused; every send signs a fresh request'
            raise Refused(msg)
        self._seen[nonce] = now
        return key


def keys_file(path: Path) -> Callable[[], list[str]]:
    """Reads the public key lines of an authorized-keys file (``[]`` when absent: nothing is admitted)."""

    def read() -> list[str]:
        try:
            text = path.read_text(encoding='utf-8')
        except OSError:
            return []
        return [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#')]

    return read


# --- the relay (the unit) -------------------------------------------------------------------------------------------

#: Runs one admitted serve line as *key*: ``(line, key)`` -> ``(exit status, output)``.
type Run = Callable[[str, str], tuple[int, str]]


def sudo_run(serve: Sequence[str]) -> Run:
    """The relay's one action: *serve* (the ForceCommand's own ``sudo -n ... serve``), line on stdin, key recorded.

    The key is written as sshd's ``ExposeAuthInfo`` record and named in :data:`~dev_lab.ops.sshkey.ENV`, which the
    role's sudoers line already keeps -- so the serve verb records the same fingerprint the ssh path does.
    """

    def run(line: str, key: str) -> tuple[int, str]:
        kind, blob = _key_words(key)
        with tempfile.TemporaryDirectory(prefix='dev-lab-door-') as scratch:
            record = Path(scratch) / 'auth'
            record.write_text(f'publickey {kind} {blob}\n', encoding='utf-8')
            record.chmod(0o644)  # root reads it through sudo; the directory is the account's own
            Path(scratch).chmod(0o711)
            env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), AUTH_ENV: str(record)}
            try:
                done = subprocess.run(list(serve), input=line.encode(), capture_output=True, check=False,
                                      timeout=TIMEOUT_S, env=env)  # fmt: skip
            except subprocess.TimeoutExpired:
                return 1, f'the serve verb ran past {TIMEOUT_S:.0f} s'
        return done.returncode, (done.stdout + done.stderr).decode('utf-8', 'replace')

    return run


def _handler(path: str, gate: Gate, run: Run) -> type[BaseHTTPRequestHandler]:
    class Door(BaseHTTPRequestHandler):
        server_version = 'dev-lab-door'
        sys_version = ''

        def _answer(self, code: int, status: int, output: str) -> None:
            data = json.dumps({'status': status, 'output': output}).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            self._answer(405, REFUSED, f'POST one signed JSON envelope to {path}')

        def do_POST(self) -> None:
            if self.path != path:
                self._answer(404, REFUSED, f'this door serves {path} only')
                return
            size = int(self.headers.get('Content-Length') or 0)
            if not 0 < size <= BODY_MAX:
                self._answer(413, REFUSED, f'a request is one JSON envelope of 1..{BODY_MAX} bytes')
                return
            raw = self.rfile.read(size)
            # Caddy sets this header to the address it saw; the relay listens on 127.0.0.1 only, so Caddy is the
            # one caller that can set it.
            who = self.headers.get('X-Dev-Lab-Peer') or self.client_address[0]
            try:
                try:
                    body = json.loads(raw)
                except ValueError:
                    body = None
                key = gate.admit(body, who)
            except Refused as refused:
                emit(f'[httpsdoor] {gate.role}: refused {who}: {refused}', err=True)
                self._answer(403, REFUSED, f'refused: {refused}')
                return
            line = str(body['line'])  # type: ignore[index] -- admitted, so an envelope
            if '\n' in line.rstrip('\n'):
                self._answer(400, REFUSED, 'a request carries ONE serve line')
                return
            emit(f'[httpsdoor] {gate.role}: {who} as {fingerprint(key)}', err=True)
            status, output = run(line.rstrip('\n') + '\n', key)
            self._answer(200, status, output)

        def log_message(self, *_args: object) -> None:
            return  # the role audits every request itself; the relay logs no bodies (codes, credentials)

    return Door


def relay(port: int, gate: Gate, run: Run, *, serve_forever: bool = True) -> ThreadingHTTPServer:
    """Serve *gate*'s role on ``127.0.0.1:port`` -- never another interface -- running each admitted line by *run*."""
    server = ThreadingHTTPServer(('127.0.0.1', port), _handler(PATHS[gate.role], gate, run))
    if serve_forever:
        server.serve_forever()
    return server


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m dev_lab.ops.httpsdoor --port N --role R --keys FILE [--attempts ...] -- <serve argv>``."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.ops.httpsdoor', description=__doc__.splitlines()[0])
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--role', choices=sorted(PATHS), required=True)
    parser.add_argument('--keys', required=True, help="the role account's authorized-keys file (the ssh key set)")
    parser.add_argument('--attempts', type=int, default=HttpsDoor.https_attempts)
    parser.add_argument('--window-minutes', type=float, default=HttpsDoor.https_window_minutes)
    parser.add_argument('--lock-minutes', type=float, default=HttpsDoor.https_lock_minutes)
    parser.add_argument('serve', nargs=argparse.REMAINDER, help='-- then the sudo serve command line')
    args = parser.parse_args(argv)
    serve = args.serve[1:] if args.serve[:1] == ['--'] else args.serve
    if not serve:
        parser.error('give the serve command after --')
    door = HttpsDoor(https_port=args.port, https_site='-', https_attempts=args.attempts,
                     https_window_minutes=args.window_minutes, https_lock_minutes=args.lock_minutes)  # fmt: skip
    relay(args.port, Gate(args.role, keys_file(Path(args.keys)), door), sudo_run(serve))
    return 0


# --- the client -----------------------------------------------------------------------------------------------------


def spki_pin(der: bytes) -> str:
    """``sha256/<base64>`` of a DER certificate's SubjectPublicKeyInfo: what ``https_pin`` declares."""
    spki = (
        x509.load_der_x509_certificate(der).public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    )
    return 'sha256/' + base64.b64encode(hashlib.sha256(spki).digest()).decode()


#: Opens a TLS connection to ``(host, port)`` with the system trust store.
type Connect = Callable[[str, int], http.client.HTTPSConnection]


def _connect(host: str, port: int) -> http.client.HTTPSConnection:
    return http.client.HTTPSConnection(host, port, timeout=TIMEOUT_S, context=ssl.create_default_context())


def identity_of(table: Mapping[str, Any]) -> Path:
    """The private client key a request is signed with: *table*'s ``identity``, else ``~/.ssh/id_ed25519``."""
    return Path(str(table.get('identity') or Path.home() / '.ssh' / 'id_ed25519')).expanduser()


def _role_of(url: str) -> str:
    path = urlsplit(url).path.rstrip('/')
    return next((role for role, served in PATHS.items() if path == served), '')


def https_send(  # noqa: PLR0911 -- each refusal answers with its own cause and door
    table: Mapping[str, Any], request: dict[str, Any], *, connect: Connect = _connect, sign: Sign | None = None,
    now: Callable[[], float] = time.time,
) -> tuple[int, str]:  # fmt: skip
    """POST *request*, signed by this machine's client key, to *table*'s ``https`` URL; answers as the ssh door does.

    A transport failure is :data:`UNREACHABLE` with its cause and door; a pin mismatch refuses before anything is sent.
    """
    url = str(table['https'])
    parts, role = urlsplit(url), _role_of(url)
    if parts.scheme != 'https' or not parts.hostname or not role:
        return REFUSED, (f'the endpoint https = {url!r} is not https://<forge>{PATHS["consent"]} or '
                         f'{PATHS["breakglass"]}: fix the family [consent]/[breakglass] table')  # fmt: skip
    identity = identity_of(table)
    public = identity.with_name(identity.name + '.pub')
    try:
        key = public.read_text(encoding='utf-8').strip()
        body = json.dumps(envelope(role, json.dumps(request), key, sign or ssh_sign(str(identity)), now=now()))
    except OSError:
        return REFUSED, (
            f'no ssh client key at {identity} (+ .pub) to sign with: run `python -m dev_lab.dev.devhost bringup '
            '--check` (its client-key wall names the door), or set [consent] identity'
        )
    except Refused as refused:
        return REFUSED, str(refused)
    try:
        conn = connect(parts.hostname, parts.port or 443)
        conn.connect()
        if pin := str(table.get('https_pin') or ''):
            der = conn.sock.getpeercert(binary_form=True) if conn.sock is not None else None
            if not der or spki_pin(der) != pin:
                conn.close()
                return UNREACHABLE, (
                    f'{parts.hostname} presented a key whose pin is not https_pin {pin}: refusing to send; if the '
                    'server key was rotated, update https_pin in the family table'
                )
        conn.request('POST', parts.path, body=body.encode(), headers={'Content-Type': 'application/json'})
        answer = conn.getresponse()
        raw = answer.read()
    except (OSError, http.client.HTTPException) as failed:
        return UNREACHABLE, (f'{url} could not be reached ({type(failed).__name__}: {failed}); check the network, or '
                             'that this address is inside the forge allowlist ([ops.caddy] allow)')  # fmt: skip
    try:
        said = json.loads(raw)
    except ValueError:
        said = None
    if isinstance(said, dict) and isinstance(said.get('status'), int):
        return said['status'], str(said.get('output', ''))
    if answer.status == 403:  # noqa: PLR2004 -- Caddy's own allowlist refusal carries no door answer
        return REFUSED, f'{url} refused this address (HTTP 403): it is outside the forge allowlist [ops.caddy] allow'
    return UNREACHABLE, f'{url} answered HTTP {answer.status} without a door answer: {raw[:200]!r}'


if __name__ == '__main__':
    raise SystemExit(main())
