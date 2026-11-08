"""THE CLIENT AND VERIFIER SIDE: ``grant`` (the user's), :func:`redeem` (every irreversible action's), the public key.

A client holds no secret. The machine file's ``[consent]`` table names the issuer's ``endpoint``
(``<account>@<host>``, its ssh ForceCommand the issuer's serve verb), an optional ssh ``identity``, and the issuer's
``public_key`` (:func:`dev_lab.ops.consent.credential.public_text`); a key shipped in the package
(``issuer.pub`` beside this module) is the fallback.

:func:`grant` takes the TOTP code the USER gave -- the agent passes it as ``code`` or on stdin, a terminal is
prompted without echo (user ruling 2026-11-08) -- and writes the credential to
:func:`dev_lab.dev.consentguard.state_dir` ``/<id>.json``, which only the grant writes (CONSENT-CODE-FROM-THE-USER).
The code is sent once and never echoed, logged or kept.

:func:`redeem` is the gate of an IRREVERSIBLE action (a spend, a merge, a wave): the signature and expiry verify
offline, then the use is registered online with the issuer; an issuer that cannot be reached REFUSES, never admits.
"""

from __future__ import annotations

import getpass
import json
import sys
import time
from collections.abc import Callable, Mapping
from importlib import resources
from pathlib import Path
from typing import Any, Final

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from lab_commons.config import section

from dev_lab.dev.consentguard import state_dir
from dev_lab.dev.forgebreakglass import Send, ssh_send
from dev_lab.ops.consent.credential import ConsentRefused, Credential, public_key_from, verify
from dev_lab.ops.consent.issuer import requested
from dev_lab.ops.totp import write_private

__all__ = ['TABLE', 'Register', 'grant', 'public_key', 'redeem', 'remote_register']

#: The machine-file table.
TABLE: Final = 'consent'
_DIGITS: Final = 6
_PROMPT: Final = 'Authenticator code (not echoed): '
_PACKAGED: Final = 'issuer.pub'
#: The serve verb's exit status for a refusal (as every ops door's).
_REFUSED: Final = 2

#: Registers one use of a credential with the issuer: ``(credential, amount)``; raises :class:`ConsentRefused`.
Register = Callable[[Mapping[str, Any], int], object]


def public_key(table: Mapping[str, Any] | None = None) -> Ed25519PublicKey:
    """The issuer's public key: ``[consent] public_key``, else the packaged ``issuer.pub``; refused when neither."""
    found = section(TABLE) if table is None else table
    text = str(found.get('public_key') or '')
    if not text:
        packaged = resources.files(__package__).joinpath(_PACKAGED)
        text = packaged.read_text(encoding='utf-8') if packaged.is_file() else ''
    if not text.strip():
        msg = f'no consent public key: set [{TABLE}] public_key in the machine file, or ship {_PACKAGED}'
        raise ConsentRefused(msg)
    return public_key_from(text)


def redeem(
    credential: Mapping[str, Any], *, action: str, key: Ed25519PublicKey, register: Register, now: float,
    amount: int = 1,
) -> Credential:  # fmt: skip
    """*credential* for one IRREVERSIBLE use of *action*: verified offline, then registered with the issuer.

    Raises:
        ConsentRefused: it does not verify, names another action, the issuer refused the use, or the issuer could
            not be reached (fail closed).

    """
    found = verify(dict(credential), key, now=now)
    if found.action != action:
        msg = f'the credential consents to {found.action}, not {action}'
        raise ConsentRefused(msg)
    try:
        register(credential, amount)
    except ConsentRefused:
        raise
    except Exception as unreachable:
        msg = f'the consent issuer could not register the use ({type(unreachable).__name__}): refused, never admitted'
        raise ConsentRefused(msg) from unreachable
    return found


def remote_register(table: Mapping[str, Any] | None = None, *, send: Send = ssh_send) -> Register:
    """A :data:`Register` over ssh to ``[consent] endpoint``; exit 2 is the issuer's refusal, anything else raises."""
    found = section(TABLE) if table is None else table
    if not found.get('endpoint'):
        msg = f'the machine file has no [{TABLE}] endpoint = "<account>@<host>"'
        raise ConsentRefused(msg)

    def register(credential: Mapping[str, Any], amount: int) -> object:
        status, said = send(found, {'verb': 'register', 'credential': dict(credential), 'amount': amount})
        if status == _REFUSED:
            raise ConsentRefused(said)
        if status != 0:
            msg = f'the consent issuer answered {status}: {said}'
            raise ConnectionError(msg)
        return said

    return register


def grant(
    request_file: Path,
    *,
    table: Mapping[str, Any] | None = None,
    code: str | None = None,
    tty: bool | None = None,
    ask: Callable[[str], str] = getpass.getpass,
    read: Callable[[], str] = sys.stdin.readline,
    send: Send = ssh_send,
    home: Path | None = None,
    now: Callable[[], float] = time.time,
) -> Path:
    """Ask the issuer for the credential *request_file* describes; the file it was written to.

    Raises:
        ConsentRefused: the code is not six digits, the request is malformed, or the issuer refused.

    """
    found = section(TABLE) if table is None else table
    if not found.get('endpoint'):
        msg = f'the machine file has no [{TABLE}] endpoint = "<account>@<host>"'
        raise ConsentRefused(msg)
    key = public_key(found)
    request = json.loads(request_file.read_text(encoding='utf-8'))
    requested(request)  # refused here, before the user spends a code
    given = code if code is not None else ask(_PROMPT) if (sys.stdin.isatty() if tty is None else tty) else read()
    given = given.strip()
    if not (len(given) == _DIGITS and given.isdigit()):
        msg = f'the Authenticator code must be six digits (got {len(given)} characters)'
        raise ConsentRefused(msg)
    status, said = send(found, {'verb': 'issue', 'request': request, 'code': given})
    if status != 0:
        raise ConsentRefused(said)
    credential = json.loads(said)
    issued = verify(credential, key, now=now())
    target = state_dir(home) / f'{issued.id}.json'
    write_private(target, json.dumps(credential, indent=1, sort_keys=True) + '\n')
    return target
