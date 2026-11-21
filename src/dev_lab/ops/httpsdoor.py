"""THE HTTPS DOOR: the consent issuer and break-glass server reached over HTTPS, beside their ssh ForceCommand.

User directive 2026-11-21: every workstation opens break-glass by itself once it has the code; ssh needed a host key
distributed and a client key authorized per workstation -- a G dependency each time. Ruling the same day: HTTPS with
TOTP-only authorization, behind forge-a1's Caddy ``remote_ip`` allowlist.

THE SHAPE. ssh stays selectable (``keep-valuable-options``); this door changes only the TRANSPORT:

* :func:`relay` is the unit (``python -m dev_lab.ops.httpsdoor``), run as the role's restricted account on
  ``127.0.0.1:<https_port>`` only. Each POST body is the SAME one JSON line the ForceCommand takes; the relay runs
  the SAME serve verb through its one sudoers line (``sudo -n ... serve --https``) with the caller's address in
  :data:`PEER_ENV`, and answers ``{"status": n, "output": "..."}``. It holds no secret and judges nothing.
* Caddy reaches it at the role's :data:`PATHS` entry inside the allowlisted site
  (:func:`dev_lab.ops.caddy.doors_routed`):
  a caller outside ``[ops.caddy] allow`` gets 403 before the relay is reached, and the relay sees the peer Caddy saw.
* ``serve --https`` authorizes WITHOUT a client key: a code, a signed credential, or a read (the per-verb table is
  in ``docs-src/dev/topology.md``). Code-taking and credential-taking requests pass the per-peer :class:`Throttle`.
* :func:`https_send` is the client (system trust store; ``https_pin`` optionally pins the server key's SPKI) and
  :func:`endpoint_send` picks it when the endpoint table declares ``https``, ssh otherwise.

Server identity is TLS: Caddy's public certificate, checked against the system trust store -- nothing to distribute.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import os
import ssl
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from dev_lab.ops.statelock import exclusive

__all__ = [
    'BODY_MAX',
    'PATHS',
    'PEER_ENV',
    'HttpsDoor',
    'Throttle',
    'alerting',
    'https_send',
    'main',
    'peer',
    'relay',
    'spki_pin',
]

#: The variable the relay names the caller's address in; the role's sudoers line keeps it.
PEER_ENV: Final = 'DEV_LAB_HTTPS_PEER'
#: The URL path each role is served at, inside the allowlisted Caddy site.
PATHS: Final = {'consent': '/dev-lab/consent', 'breakglass': '/dev-lab/breakglass'}
#: The largest request body the relay reads: a plan of max_grants credentials fits many times over.
BODY_MAX: Final = 256 * 1024
#: How long one request may run (a break-glass merge talks to a forge), the ssh transport's own bound.
TIMEOUT_S: Final = 180.0
#: The largest TCP port.
_PORT_MAX: Final = 65535
#: The exit status a transport failure reports (ssh's own), so callers treat both transports alike.
UNREACHABLE: Final = 255


@dataclass(frozen=True, kw_only=True)
class HttpsDoor:
    """A role's HTTPS door (mixed into ``[ops.consent]`` and ``[ops.breakglass]``); ``https_port = 0`` renders none.

    ``https_port`` is the relay's port on 127.0.0.1; ``https_site`` the ``[ops.caddy]`` site that routes
    :data:`PATHS` to it (it must be an allowlisted one). A peer may make ``https_attempts`` guarded requests per
    ``https_window_minutes``; the one past that locks the peer out for ``https_lock_minutes`` and alerts.
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
            msg = 'https_attempts, https_window_minutes and https_lock_minutes must be positive (rate limit + lockout)'
            raise ValueError(msg)


class Throttle:
    """Per-peer rate limit and lockout of guarded HTTPS requests, persisted in ``<state>/https/throttle.json``.

    :meth:`check` refuses a locked peer; :meth:`strike` records one guarded attempt and, when it is the
    ``attempts + 1``-th inside the window, locks the peer, calls *on_lock* once (the alert) and refuses.
    """

    def __init__(
        self, state: Path, door: HttpsDoor, *, now: Callable[[], float], on_lock: Callable[[str, float], None],
        refused: type[Exception],
    ) -> None:  # fmt: skip
        """Throttle under *state* by *door*'s bounds; *refused* is the role's refusal type."""
        self.dir, self.door, self.now, self.on_lock, self.refused = state / 'https', door, now, on_lock, refused

    def _load(self) -> dict[str, dict[str, Any]]:
        path = self.dir / 'throttle.json'
        return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}

    def _save(self, table: dict[str, dict[str, Any]]) -> None:
        partial = self.dir / 'throttle.partial'
        partial.write_text(json.dumps(table, sort_keys=True), encoding='utf-8')
        partial.replace(self.dir / 'throttle.json')

    def _locked(self, peer: str, until: float) -> Exception:
        return self.refused(
            f'too many attempts from {peer}: refused for {(until - self.now()) / 60:.0f} more minute(s) '
            '(rate limit of the HTTPS door; the user was alerted)'
        )

    def check(self, peer: str) -> None:
        """Refuse *peer* while it is locked out."""
        self.dir.mkdir(parents=True, exist_ok=True)
        with exclusive(self.dir):
            until = float(self._load().get(peer, {}).get('until', 0.0))
        if self.now() < until:
            raise self._locked(peer, until)

    def strike(self, peer: str) -> None:
        """Count one guarded attempt of *peer*; lock, alert and refuse past the window's allowance."""
        self.dir.mkdir(parents=True, exist_ok=True)
        now, window = self.now(), self.door.https_window_minutes * 60
        with exclusive(self.dir):
            table = self._load()
            row = table.get(peer, {})
            if now < float(row.get('until', 0.0)):
                raise self._locked(peer, float(row['until']))
            seen = [at for at in row.get('at', []) if now - at < window] + [now]
            locked = len(seen) > self.door.https_attempts
            until = now + self.door.https_lock_minutes * 60 if locked else 0.0
            table[peer] = {'at': [] if locked else seen, 'until': until}
            self._save(table)
        if locked:
            self.on_lock(peer, until)
            raise self._locked(peer, until)


def alerting(
    door: HttpsDoor, state: Path, *, alert: Callable[[str, str], object], refused: type[Exception]
) -> Throttle:
    """*door*'s :class:`Throttle` under *state*; a lockout raises ONE alert ``(title, detail)`` when it begins."""

    def locked(who: str, until: float) -> None:
        when = datetime.fromtimestamp(until, UTC).isoformat(timespec='seconds')
        alert('HTTPS door LOCKED a peer', f'{who} passed {door.https_attempts} guarded request(s) per '
              f'{door.https_window_minutes:g} min; every request from it is refused until {when}')  # fmt: skip

    return Throttle(state, door, now=time.time, on_lock=locked, refused=refused)


def peer() -> str:
    """The caller's address the relay passed (``''`` over ssh)."""
    return os.environ.get(PEER_ENV, '')


# --- the relay (the unit) -------------------------------------------------------------------------------------------

#: Runs one request line for a peer: ``(line, peer)`` -> ``(exit status, output)``.
type Run = Callable[[str, str], tuple[int, str]]


def sudo_run(serve: Sequence[str]) -> Run:
    """The relay's one action: *serve* (``sudo -n <ops> ... serve --https``) with the line on stdin."""

    def run(line: str, who: str) -> tuple[int, str]:
        env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), PEER_ENV: who}
        try:
            done = subprocess.run(
                list(serve), input=line.encode(), capture_output=True, check=False, timeout=TIMEOUT_S, env=env
            )
        except subprocess.TimeoutExpired:
            return 1, f'the {serve[-2] if len(serve) > 1 else "serve"} verb ran past {TIMEOUT_S:.0f} s'
        return done.returncode, (done.stdout + done.stderr).decode('utf-8', 'replace')

    return run


def _handler(path: str, run: Run) -> type[BaseHTTPRequestHandler]:
    class Door(BaseHTTPRequestHandler):
        server_version = 'dev-lab-door'
        sys_version = ''

        def _answer(self, code: int, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            self._answer(405, {'status': 2, 'output': f'POST one JSON line to {path}'})

        def do_POST(self) -> None:
            if self.path != path:
                self._answer(404, {'status': 2, 'output': f'this door serves {path} only'})
                return
            size = int(self.headers.get('Content-Length') or 0)
            if not 0 < size <= BODY_MAX:
                self._answer(413, {'status': 2, 'output': f'a request is one JSON line of 1..{BODY_MAX} bytes'})
                return
            line = self.rfile.read(size).decode('utf-8', 'replace')
            if '\n' in line.rstrip('\n'):
                self._answer(400, {'status': 2, 'output': 'a request is ONE JSON line'})
                return
            # Caddy sets this header to the address it saw (header_up ... {remote_host}); the relay listens on
            # 127.0.0.1 only, so Caddy is the one caller that can set it.
            who = self.headers.get('X-Dev-Lab-Peer') or self.client_address[0]
            status, output = run(line.rstrip('\n') + '\n', who)
            self._answer(200, {'status': status, 'output': output})

        def log_message(self, *_args: object) -> None:
            return  # the role audits every request itself; the relay logs no bodies (codes, credentials)

    return Door


def relay(port: int, path: str, run: Run, *, serve_forever: bool = True) -> ThreadingHTTPServer:
    """Serve *path* on ``127.0.0.1:port`` -- never another interface -- running each request through *run*."""
    server = ThreadingHTTPServer(('127.0.0.1', port), _handler(path, run))
    if serve_forever:
        server.serve_forever()
    return server


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m dev_lab.ops.httpsdoor --port N --role consent|breakglass -- <serve argv>``: the relay unit."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.ops.httpsdoor', description=__doc__.splitlines()[0])
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--role', choices=sorted(PATHS), required=True)
    parser.add_argument('serve', nargs=argparse.REMAINDER, help='-- then the sudo serve command line')
    args = parser.parse_args(argv)
    serve = [word for word in args.serve if word != '--'] if args.serve[:1] == ['--'] else args.serve
    if not serve:
        parser.error('give the serve command after --')
    relay(args.port, PATHS[args.role], sudo_run(serve))
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


def https_send(table: Mapping[str, Any], request: dict[str, Any], *, connect: Connect = _connect) -> tuple[int, str]:
    """POST *request* as one JSON line to *table*'s ``https`` URL; ``(exit status, output)`` as the ssh door answers.

    A transport failure is :data:`UNREACHABLE` with its cause and door; a pin mismatch refuses before anything is sent.
    """
    url = str(table['https'])
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname:
        return 2, f'the endpoint https = {url!r} is not an https:// URL: fix the [consent]/[breakglass] table'
    body = (json.dumps(request) + '\n').encode()
    try:
        conn = connect(parts.hostname, parts.port or 443)
        conn.connect()
        if pin := str(table.get('https_pin') or ''):
            der = conn.sock.getpeercert(binary_form=True) if conn.sock is not None else None
            if not der or spki_pin(der) != pin:
                conn.close()
                return UNREACHABLE, (
                    f'{parts.hostname} presented a key whose pin is not https_pin {pin}: refusing to send; '
                    'if the server key was rotated, update https_pin in the family table'
                )
        conn.request('POST', parts.path or '/', body=body, headers={'Content-Type': 'application/json'})
        answer = conn.getresponse()
        raw = answer.read()
    except (OSError, http.client.HTTPException) as failed:
        return UNREACHABLE, (
            f'{url} could not be reached ({type(failed).__name__}: {failed}); check the network, or that this '
            'address is inside the forge allowlist ([ops.caddy] allow), or use the ssh endpoint'
        )
    try:
        said = json.loads(raw)
    except ValueError:
        said = None
    if answer.status == 403:  # noqa: PLR2004 -- Caddy's allowlist refusal
        return 2, f'{url} refused this address (HTTP 403): it is outside the forge allowlist [ops.caddy] allow'
    if not isinstance(said, dict) or not isinstance(said.get('status'), int):
        return UNREACHABLE, f'{url} answered HTTP {answer.status} without a door answer: {raw[:200]!r}'
    return said['status'], str(said.get('output', ''))


if __name__ == '__main__':
    raise SystemExit(main())
