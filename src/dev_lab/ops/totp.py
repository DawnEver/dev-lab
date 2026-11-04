"""RFC 6238 TOTP: the per-use authorization of a break-glass merge, verified on the host that holds the secret.

THE SECRET NEVER LEAVES THE HOST except once, as the enrolment URI the user scans into an Authenticator app
(:func:`enrol`). A code is accepted at most once: :func:`accept` persists the time-step it matched and refuses any
step at or before it, so a code read off a screen or a log cannot be replayed, even inside its own window. The read
and the write of that step are one critical section only under the role lock its caller holds
(:func:`dev_lab.ops.statelock.exclusive`, taken by every break-glass request).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import os
import secrets
import struct
from pathlib import Path
from typing import Final
from urllib.parse import quote

__all__ = [
    'DIGITS',
    'STEP',
    'WINDOW',
    'TotpRefused',
    'accept',
    'adopt',
    'code_at',
    'enrol',
    'qr',
    'uri',
    'write_private',
]

#: Seconds per time-step (RFC 6238 default; every Authenticator app's).
STEP: Final = 30
#: Digits in a code.
DIGITS: Final = 6
#: Steps of clock skew accepted either side of now.
WINDOW: Final = 1
#: The fewest secret bits an adopted secret may carry (RFC 4226 floor is 128; Authenticator exports reach 80).
_MIN_BITS: Final = 80


class TotpRefused(ValueError):
    """The code was refused; the message says why without echoing the code."""


def _key(secret: str) -> bytes:
    return base64.b32decode(secret.strip().upper() + '=' * (-len(secret.strip()) % 8))


def code_at(secret: str, step: int) -> str:
    """The code *secret* yields at time-step *step* (RFC 4226 dynamic truncation over HMAC-SHA1)."""
    digest = hmac.new(_key(secret), struct.pack('>Q', step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack('>I', digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**DIGITS).zfill(DIGITS)


def _read_secret(path: Path) -> str:
    try:
        secret = path.read_text(encoding='utf-8').strip()
    except FileNotFoundError:
        secret = ''
    if not secret:
        msg = f'no TOTP secret at {path}: enrol first (python -m dev_lab.ops --config <toml> breakglass enrol)'
        raise TotpRefused(msg)
    return secret


def accept(secret_file: Path, state_file: Path, code: str, now: float) -> int:
    """The time-step *code* matches within :data:`WINDOW` of *now*, recorded so it is never accepted again.

    Raises:
        TotpRefused: no secret, a malformed or wrong code, or a step at or before the last accepted one.

    """
    secret = _read_secret(secret_file)
    if not (len(code) == DIGITS and code.isdigit()):
        msg = f'a code is {DIGITS} digits'
        raise TotpRefused(msg)
    current = int(now // STEP)
    matched = [
        s for s in range(current - WINDOW, current + WINDOW + 1) if hmac.compare_digest(code_at(secret, s), code)
    ]
    if not matched:
        msg = 'the code is wrong or outside its 30-second window'
        raise TotpRefused(msg)
    step = max(matched)
    last = int(state_file.read_text(encoding='utf-8').strip() or 0) if state_file.is_file() else 0
    if step <= last:
        msg = 'the code was already used: wait for the next one'
        raise TotpRefused(msg)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    partial = state_file.with_suffix('.partial')
    partial.write_text(str(step), encoding='utf-8')
    partial.replace(state_file)
    return step


def uri(secret: str, *, issuer: str, account: str) -> str:
    """The ``otpauth://`` URI an Authenticator app scans (render it as a QR on the host's own terminal)."""
    label = quote(f'{issuer}:{account}')
    return f'otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={STEP}'


def qr(text: str) -> str:
    """*text* as a QR code drawn in half-block characters, light modules as blocks (a dark terminal's colours).

    Needs the ``dev-lab[ops]`` extra (segno). Shown ONLY on the terminal that enrolled: it carries the secret, so
    it is returned for stdout, never logged.
    """
    import segno  # noqa: PLC0415 -- the ops extra: a consumer importing totp for codes never needs it

    out = io.StringIO()
    segno.make(text, error='m').terminal(out=out, compact=True)
    return out.getvalue()


def enrol(secret_file: Path, *, force: bool = False) -> str:
    """Generate a 160-bit secret into *secret_file* (mode 600) and return it; refuse to replace one unless *force*."""
    if secret_file.is_file() and secret_file.read_text(encoding='utf-8').strip() and not force:
        msg = f'{secret_file} already holds a secret; --force replaces it (the old Authenticator entry stops working)'
        raise TotpRefused(msg)
    secret = base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=')
    write_private(secret_file, secret + '\n')
    return secret


def adopt(secret_file: Path, secret: str) -> bool:
    """Place an EXISTING secret (one the user's Authenticator already holds) at *secret_file*, mode 600.

    Returns whether it wrote: the same secret already there is a no-op. Never echoes the secret.

    Raises:
        TotpRefused: *secret* is not base32 of at least 80 bits, or *secret_file* holds a different secret.

    """
    secret = secret.strip().upper().rstrip('=')
    try:
        bits = len(_key(secret)) * 8
    except (ValueError, base64.binascii.Error):
        bits = 0
    if bits < _MIN_BITS:
        msg = f'the adopted secret is not base32 of at least {_MIN_BITS} bits'
        raise TotpRefused(msg)
    held = secret_file.read_text(encoding='utf-8').strip().upper() if secret_file.is_file() else ''
    if held == secret:
        return False
    if held:
        msg = f'{secret_file} already holds a different secret; a host has ONE TOTP secret, refusing to replace it'
        raise TotpRefused(msg)
    write_private(secret_file, secret + '\n')
    return True


def write_private(path: Path, text: str) -> None:
    """Write *text* to *path* created mode 600 (and re-narrowed to 600 if it existed), making its parent."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as out:
        out.write(text)
    path.chmod(0o600)
