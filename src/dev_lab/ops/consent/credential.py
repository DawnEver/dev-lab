"""THE CREDENTIAL: a JSON object whose Ed25519 ``sig`` covers every other field; offline verification.

Fields: ``id`` (UUID), ``action``, ``subject``, ``params`` (the request's parameters) and ``params_hash`` (SHA-256 of
their canonical JSON), ``scope``, ``cap`` (a campaign's, else ``None``), ``issued``, ``expires`` (epoch seconds),
``issuer`` and ``sig``. The signed bytes are the canonical JSON (sorted keys, no whitespace, ASCII) of every field but
``sig``, so changing any field -- or adding or dropping one -- breaks the signature.

:func:`verify` is everything a verifier can check WITHOUT the issuer: the field set, the signature, the params hash,
the registry row (action, scope, cap, lifetime) and the clock, with :data:`SKEW_S` of skew either side. Whether a
single credential was already used, or a campaign is over its cap, only the issuer knows (:mod:`.issuer`).
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from dev_lab.ops.consent.actions import ACTIONS, CAMPAIGN

__all__ = [
    'FIELDS',
    'SKEW_S',
    'ConsentRefused',
    'Credential',
    'canonical',
    'params_hash',
    'public_key_from',
    'public_text',
    'sign',
    'verify',
]

#: Clock skew a verifier tolerates either side, in seconds.
SKEW_S: Final = 120.0
#: Every field a credential carries, ``sig`` last.
FIELDS: Final = (
    'id', 'action', 'subject', 'params', 'params_hash', 'scope', 'cap', 'issued', 'expires', 'issuer', 'sig',
)  # fmt: skip


class ConsentRefused(ValueError):
    """A credential or request was refused; the message says why and never carries a code or a key."""


def canonical(value: object) -> bytes:
    """The one byte spelling of *value*: sorted keys, no whitespace, ASCII."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def params_hash(params: Mapping[str, Any]) -> str:
    """SHA-256 (hex) of *params*' canonical JSON."""
    return hashlib.sha256(canonical(dict(params))).hexdigest()


@dataclass(frozen=True)
class Credential:
    """A verified credential's fields."""

    id: str
    action: str
    subject: str
    params: Mapping[str, Any]
    scope: str
    cap: int | None
    issued: float
    expires: float
    issuer: str


def sign(fields: Mapping[str, Any], key: Ed25519PrivateKey) -> dict[str, Any]:
    """*fields* (every field but ``sig``) with ``sig``: base64 Ed25519 over their canonical JSON."""
    body = {name: fields[name] for name in FIELDS if name != 'sig'}
    return body | {'sig': base64.b64encode(key.sign(canonical(body))).decode()}


def public_text(key: Ed25519PublicKey) -> str:
    """*key* as the one line ``[consent] public_key`` holds: base64 of its 32 raw bytes."""
    return base64.b64encode(key.public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()


def public_key_from(text: str) -> Ed25519PublicKey:
    """The key :func:`public_text` spelled; refused when it is not 32 base64 bytes."""
    try:
        return Ed25519PublicKey.from_public_bytes(base64.b64decode(text.strip(), validate=True))
    except ValueError as bad:
        msg = 'the consent public key is not base64 of 32 raw Ed25519 bytes'
        raise ConsentRefused(msg) from bad


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        msg = f'credential {name} is not a finite number'
        raise ConsentRefused(msg)
    return float(value)


def verify(data: object, key: Ed25519PublicKey, *, now: float) -> Credential:
    """The credential *data* (a parsed JSON object), checked offline; :class:`ConsentRefused` names the first fault."""
    if not isinstance(data, dict) or set(data) != set(FIELDS):
        msg = f'a credential carries exactly the fields {", ".join(FIELDS)}'
        raise ConsentRefused(msg)
    try:
        signature = base64.b64decode(str(data['sig']), validate=True)
        key.verify(signature, canonical({name: data[name] for name in FIELDS if name != 'sig'}))
    except (ValueError, InvalidSignature, TypeError) as bad:
        msg = 'the credential signature does not verify: a field was changed, or another key signed it'
        raise ConsentRefused(msg) from bad
    if not isinstance(data['params'], dict) or params_hash(data['params']) != data['params_hash']:
        msg = 'the credential params do not match their hash'
        raise ConsentRefused(msg)
    row = ACTIONS.get(str(data['action']))
    if row is None or data['scope'] != row.scope:
        msg = f'action {data["action"]!r} in scope {data["scope"]!r} is not in the registry'
        raise ConsentRefused(msg)
    if (row.scope == CAMPAIGN) != isinstance(data['cap'], int) or isinstance(data['cap'], bool):
        msg = 'a campaign credential carries an integer cap, a single one none'
        raise ConsentRefused(msg)
    issued, expires = _number(data['issued'], 'issued'), _number(data['expires'], 'expires')
    if expires - issued > row.max_ttl:
        msg = f'the credential lives {expires - issued:g} s, above {row.name} max_ttl {row.max_ttl:g} s'
        raise ConsentRefused(msg)
    if now > expires + SKEW_S:
        msg = f'the credential expired {now - expires:.0f} s ago'
        raise ConsentRefused(msg)
    if now < issued - SKEW_S:
        msg = 'the credential is issued in the future: a clock is wrong'
        raise ConsentRefused(msg)
    return Credential(
        str(data['id']), row.name, str(data['subject']), dict(data['params']), row.scope, data['cap'], issued,
        expires, str(data['issuer']),
    )  # fmt: skip
