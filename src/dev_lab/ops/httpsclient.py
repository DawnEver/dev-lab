"""THE HTTPS DOOR'S CLIENT: one request to the consent issuer or break-glass server, signed by this machine's key.

:func:`https_send` answers ``(exit status, output)`` exactly as the ssh transport does, so
:func:`dev_lab.ops.consent.door.endpoint_send` can pick either by the machine's ``forge_reach``. The server's
identity is TLS (system trust store; ``https_pin`` optionally pins its SPKI); the caller's is the signature
(:mod:`dev_lab.ops.httpsdoor`).
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import ssl
import time
from collections.abc import Callable, Mapping
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from dev_lab.ops.httpsdoor import PATHS, REFUSED, TIMEOUT_S, UNREACHABLE, Refused, Sign, envelope, ssh_sign

__all__ = ['Unpinned', 'https_send', 'identity_of', 'spki_pin']


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


def _signed_body(table: Mapping[str, Any], role: str, request: dict[str, Any], sign: Sign | None, now: float) -> str:
    """The signed envelope of *request*, as JSON; raises :class:`Refused` naming the door when it cannot be signed."""
    identity = identity_of(table)
    try:
        key = identity.with_name(identity.name + '.pub').read_text(encoding='utf-8').strip()
    except OSError as missing:
        msg = (f'no ssh client key at {identity} (+ .pub) to sign with: run `python -m dev_lab.dev.devhost bringup '
               '--check` (its client-key wall names the door), or set [consent] identity')  # fmt: skip
        raise Refused(msg) from missing
    return json.dumps(envelope(role, json.dumps(request), key, sign or ssh_sign(str(identity)), now=now))


class Unpinned(Exception):
    """The server presented a key other than the declared ``https_pin``."""


def _pinned(conn: http.client.HTTPSConnection, pin: str, host: str) -> None:
    """Refuse a server whose key is not *pin* (no pin: any key the trust store accepts) before anything is sent."""
    der = conn.sock.getpeercert(binary_form=True) if conn.sock is not None else None
    if pin and (not der or spki_pin(der) != pin):
        conn.close()
        msg = (f'{host} presented a key whose pin is not https_pin {pin}: refusing to send; if the server key was '
               'rotated, update https_pin in the family table')  # fmt: skip
        raise Unpinned(msg)


def _answered(url: str, status: int, raw: bytes) -> tuple[int, str]:
    """The door's own answer in *raw*, or what an answer without one means."""
    try:
        said = json.loads(raw)
    except ValueError:
        said = None
    if isinstance(said, dict) and isinstance(said.get('status'), int):
        return said['status'], str(said.get('output', ''))
    if status == HTTPStatus.FORBIDDEN:  # Caddy's own allowlist refusal carries no door answer
        return REFUSED, f'{url} refused this address (HTTP 403): it is outside the forge allowlist [ops.caddy] allow'
    return UNREACHABLE, f'{url} answered HTTP {status} without a door answer: {raw[:200]!r}'


def https_send(
    table: Mapping[str, Any], request: dict[str, Any], *, connect: Connect = _connect, sign: Sign | None = None,
    now: Callable[[], float] = time.time,
) -> tuple[int, str]:  # fmt: skip
    """POST *request*, signed by this machine's client key, to *table*'s ``https`` URL; answers as the ssh door does.

    A transport failure is :data:`~dev_lab.ops.httpsdoor.UNREACHABLE` with its cause and door; a pin mismatch
    refuses before anything is sent.
    """
    url = str(table['https'])
    parts, role = urlsplit(url), _role_of(url)
    if parts.scheme != 'https' or not parts.hostname or not role:
        return REFUSED, (f'the endpoint https = {url!r} is not https://<forge>{PATHS["consent"]} or '
                         f'{PATHS["breakglass"]}: fix the family [consent]/[breakglass] table')  # fmt: skip
    try:
        body = _signed_body(table, role, request, sign, now())
    except Refused as refused:
        return REFUSED, str(refused)
    try:
        conn = connect(parts.hostname, parts.port or 443)
        conn.connect()
        _pinned(conn, str(table.get('https_pin') or ''), parts.hostname)
        conn.request('POST', parts.path, body=body.encode(), headers={'Content-Type': 'application/json'})
        answer = conn.getresponse()
        return _answered(url, answer.status, answer.read())
    except Unpinned as unpinned:
        return UNREACHABLE, str(unpinned)
    except (OSError, http.client.HTTPException) as failed:
        return UNREACHABLE, (f'{url} could not be reached ({type(failed).__name__}: {failed}); check the network, or '
                             'that this address is inside the forge allowlist ([ops.caddy] allow)')  # fmt: skip
