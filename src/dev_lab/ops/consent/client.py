"""THE CLIENT AND VERIFIER SIDE: ``grant`` (the user's), :func:`redeem` (every irreversible action's), the public key.

A client holds no secret. The machine file's ``[consent]`` table names the issuer's ``endpoint``
(``<account>@<host>``, its ssh ForceCommand the issuer's serve verb), an optional ssh ``identity``, and the issuer's
``public_key`` (:func:`dev_lab.ops.consent.credential.public_text`); a key shipped in the package
(``issuer.pub`` beside this module) is the fallback.

:func:`grant` takes the cluster code the USER gave -- the agent passes it as ``code`` or on stdin, a terminal is
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
from dev_lab.ops.consent.plan import load as load_plan
from dev_lab.ops.consent.plan import request as plan_request
from dev_lab.ops.totp import write_private

__all__ = [
    'TABLE',
    'Register',
    'given_code',
    'grant',
    'grant_plan',
    'public_key',
    'recover',
    'redeem',
    'remote_register',
    'spent_ids',
]

#: The machine-file table.
TABLE: Final = 'consent'
_DIGITS: Final = 6
_PROMPT: Final = 'Cluster code (not echoed): '
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
    credential: Mapping[str, Any], *, action: str, subject: str | None, key: Ed25519PublicKey, register: Register,
    now: float, amount: int = 1,
) -> Credential:  # fmt: skip
    """*credential* for one IRREVERSIBLE use of *action* on *subject*: verified offline, then registered.

    *subject* is the digest the caller derived from the request it is about to carry out; ``None`` only for an
    action whose subject is a free label (a wave). It is compared BEFORE the use is registered, so a credential
    shown to the wrong request is refused without being spent.

    Raises:
        ConsentRefused: it does not verify, names another action or subject, the issuer refused the use, or the
            issuer could not be reached (fail closed).

    """
    found = verify(dict(credential), key, now=now)
    if found.action != action:
        msg = f'the credential consents to {found.action}, not {action}'
        raise ConsentRefused(msg)
    if subject is not None and found.subject != subject:
        msg = (f'the {action} credential consents to another request (subject {found.subject[:12]}, this request '
               f'{subject[:12]}): refused before its use was registered')  # fmt: skip
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
    found = _endpoint(table)

    def register(credential: Mapping[str, Any], amount: int) -> object:
        status, said = send(found, {'verb': 'register', 'credential': dict(credential), 'amount': amount})
        if status == _REFUSED:
            raise ConsentRefused(said)
        if status != 0:
            msg = f'the consent issuer answered {status}: {said}'
            raise ConnectionError(msg)
        return said

    return register


def spent_ids(ids: list[str], table: Mapping[str, Any] | None = None, *, send: Send = ssh_send) -> set[str]:
    """Which of *ids* the issuer's ledger says were used; raises when it cannot say (the caller then keeps them)."""
    status, said = send(_endpoint(table), {'verb': 'spent', 'ids': list(ids)})
    answers = [found for line in said.splitlines() if isinstance(found := _json_line(line), list)]
    if status != 0 or len(answers) != 1:
        msg = f'the consent issuer could not say which credentials were spent ({status}): {said[:300]!r}'
        raise ConsentRefused(msg)
    return {ident for ident in answers[0] if ident in ids}


def given_code(
    code: str | None, *, tty: bool | None = None, ask: Callable[[str], str] = getpass.getpass,
    read: Callable[[], str] = sys.stdin.readline,
) -> str:  # fmt: skip
    """The code the USER gave: *code* when passed, else a no-echo prompt on a terminal, else one stdin line.

    The one intake of a user's code (CONSENT-CODE-FROM-THE-USER): a grant here, and ``sshhold open``.
    """
    given = code if code is not None else ask(_PROMPT) if (sys.stdin.isatty() if tty is None else tty) else read()
    return given.strip()


def _six_digits(code: str) -> str:
    if not (len(code) == _DIGITS and code.isdigit()):
        msg = f'the cluster code must be six digits (got {len(code)} characters)'
        raise ConsentRefused(msg)
    return code


def _endpoint(table: Mapping[str, Any] | None) -> Mapping[str, Any]:
    found = section(TABLE) if table is None else table
    if not found.get('endpoint'):
        msg = f'the machine file has no [{TABLE}] endpoint = "<account>@<host>"'
        raise ConsentRefused(msg)
    return found


def _json_line(line: str) -> object:
    try:
        return json.loads(line)
    except ValueError:
        return None


def _issued(
    found: Mapping[str, Any], payload: dict[str, Any], *, send: Send, home: Path | None, now: float,
    within: set[tuple[str, str]] | None = None, plan: str | None = None,
) -> list[Path]:  # fmt: skip
    """Send *payload* to the issuer; each credential it answered, verified and written private, by path.

    *within*, when given, is the closed set of ``(action, subject)`` pairs an answer may hold, each at most once.
    Every answer signs *plan*, the digest of the plan asked for (``None``: a lone request), or it is refused.
    """
    key = public_key(found)
    status, said = send(found, payload)
    if status != 0:
        raise ConsentRefused(said)
    # The issuer's host may print notices (an upgrade-on-read warning) around its one JSON answer: the answer is
    # the one line that parses as JSON, never the whole output.
    answers = [parsed for line in said.splitlines() if isinstance(parsed := _json_line(line), (list, dict))]
    if len(answers) != 1:
        msg = f'the issuer answered {len(answers)} JSON lines, not one: {said[:300]!r}'
        raise ConsentRefused(msg)
    answered = answers[0]
    written = []
    seen: set[tuple[str, str]] = set()
    for credential in answered if isinstance(answered, list) else [answered]:
        issued = verify(credential, key, now=now)
        pair = (issued.action, issued.subject)
        if within is not None and (pair not in within or pair in seen):
            msg = f'the issuer answered a credential the plan does not grant once: {pair[0]} {pair[1][:12]}'
            raise ConsentRefused(msg)
        if issued.plan != plan:
            msg = f'the issuer answered a credential of plan {issued.plan}, not of {plan}: {pair[0]} {pair[1][:12]}'
            raise ConsentRefused(msg)
        seen.add(pair)
        target = state_dir(home) / f'{issued.id}.json'
        write_private(target, json.dumps(credential, indent=1, sort_keys=True) + '\n')
        written.append(target)
    return written


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
    found = _endpoint(table)
    public_key(found)  # refused here, before the user spends a code
    request = json.loads(request_file.read_text(encoding='utf-8'))
    requested(request)
    given = _six_digits(given_code(code, tty=tty, ask=ask, read=read))
    return _issued(found, {'verb': 'issue', 'request': request, 'code': given}, send=send, home=home, now=now())[0]


def grant_plan(
    plan_file: Path,
    shown: str,
    code: str,
    host: str,
    *,
    table: Mapping[str, Any] | None = None,
    send: Send = ssh_send,
    home: Path | None = None,
    now: Callable[[], float] = time.time,
) -> list[Path]:
    """One credential per grant of the plan at *plan_file*, the one the user was *shown*, for ONE *code*.

    *host* is a session the code opens; it must be one of the plan's hosts (a code given for one plan's hosts never
    opens another).

    Raises:
        ConsentRefused: the plan is not the one shown or does not name *host*, a grant is malformed, the code is not
            six digits, or the issuer refused.

    """
    found = _endpoint(table)
    public_key(found)
    plan = load_plan(plan_file, shown)
    if host not in plan.hosts:
        msg = f'the plan opens {list(plan.hosts)}, not {host}: a code given for one plan never opens another host'
        raise ConsentRefused(msg)
    for grant_ in plan.grants:
        requested(plan_request(grant_))  # refused here, before the user spends a code
    payload = {'verb': 'issue-plan', 'plan': {'hosts': list(plan.hosts), 'grants': list(plan.grants)},
               'code': _six_digits(code)}  # fmt: skip
    return _issued(found, payload, send=send, home=home, now=now(), plan=plan.digest)


def recover(
    plan_file: Path,
    shown: str,
    *,
    table: Mapping[str, Any] | None = None,
    send: Send = ssh_send,
    home: Path | None = None,
    now: Callable[[], float] = time.time,
) -> list[Path]:
    """Fetch AGAIN the plan's granted, never-used credentials (:meth:`.issuer.Issuer.unspent`); no code is asked.

    Re-delivery, never a grant: the issuer answers the signed credentials it issued for this plan's digest, and each
    is refused here unless it verifies and names a grant of the plan the user was *shown*, at most once.
    """
    found = _endpoint(table)
    plan = load_plan(plan_file, shown)
    within = {(grant_['action'], grant_['subject']) for grant_ in plan.grants}
    payload = {'verb': 'fetch-unspent', 'plan': plan.digest}
    return _issued(found, payload, send=send, home=home, now=now(), within=within, plan=plan.digest)
