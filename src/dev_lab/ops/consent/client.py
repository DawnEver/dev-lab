"""THE CLIENT AND VERIFIER SIDE: ``grant`` (the user's), :func:`redeem` (every irreversible action's), the public key.

A client holds no secret. The machine file's ``[consent]`` table names the issuer's ``endpoint``
(``<account>@<host>``, its ssh ForceCommand the issuer's serve verb), an optional ssh ``identity``, and the issuer's
``public_key`` (:func:`dev_lab.ops.consent.credential.public_text`); a key shipped in the package
(``issuer.pub`` beside this module) is the fallback.

:func:`grant` takes the cluster code the USER gave -- the agent passes it as ``code`` or on stdin, a terminal is
asked through :func:`dev_lab.dev.ask.code`, shown as typed (user ruling D94, 2026-11-20) -- and writes the credential to
:func:`dev_lab.dev.consentguard.state_dir` ``/<id>.json``, which only the grant writes (CONSENT-CODE-FROM-THE-USER).
The code is sent once and never logged or kept.

:func:`preflight` proves, with NO code, that a lone request's grant can succeed -- endpoint and key declared, the
issuer reached over ssh (:func:`.door.reached`), the version handshake, the subject still current (:data:`SUBJECTS`),
and any check the calling verb adds -- and writes its receipt (:func:`.door.record_receipt`). :func:`grant` refuses
a code given in advance without a receipt inside the backstop before any network call, then runs the same proof
again ITSELF and uses the code only if it is green now; a code typed at its prompt is asked only after the same
preflight ran inline.

:func:`redeem` is the gate of an IRREVERSIBLE action (a spend, a merge, a wave): the signature and expiry verify
offline, then the use is registered online with the issuer; an issuer that cannot be reached REFUSES, never admits.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from importlib import resources
from pathlib import Path
from typing import Any, Final

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from lab_commons.config import section

from dev_lab.dev.ask import AskRefused
from dev_lab.dev.ask import code as asked_code
from dev_lab.dev.consentguard import state_dir
from dev_lab.dev.native_session import session_of
from dev_lab.dev.taskbinding import task_id
from dev_lab.ops.consent.credential import ConsentRefused, Credential, public_key_from, verify
from dev_lab.ops.consent.door import Send, handshake, offer, reached, record_receipt, require_receipt, ssh_send
from dev_lab.ops.consent.issuer import requested
from dev_lab.ops.consent.plan import load as load_plan
from dev_lab.ops.consent.plan import request as plan_request
from dev_lab.ops.totp import write_private

__all__ = [
    'SUBJECTS',
    'TABLE',
    'Check',
    'Register',
    'given_code',
    'grant',
    'grant_plan',
    'preflight',
    'public_key',
    'recover',
    'redeem',
    'remote_register',
    'spent_ids',
    'verify_held',
]

#: The machine-file table.
TABLE: Final = 'consent'
_DIGITS: Final = 6
_PACKAGED: Final = 'issuer.pub'
#: The serve verb's exit status for a refusal (as every ops door's).
_REFUSED: Final = 2

#: An action-specific precondition a verb adds to its preflight; raises :class:`ConsentRefused` naming its door.
Check = Callable[[], None]


def _session_current(subject: str) -> str:
    current = session_of()
    if current == subject:
        return ''
    return (f'the request names session {subject}, this session is {current or "(none)"}: write it again '
            '(`python -m dev_lab.dev.hpcaccount.session request`)')  # fmt: skip


def _task_current(subject: str) -> str:
    slug = subject.split('@', 1)[0]
    try:
        current = task_id(Path.cwd(), slug)
    except (ValueError, OSError, subprocess.CalledProcessError) as gone:
        return f'the request names task {subject}, which is not open here ({gone}): open it, then write the request'
    if current == subject:
        return ''
    return (f'the request names task {subject}, the open task is {current}: write it again '
            f'(`python -m dev_lab.dev.hpcaccount.session request --task {slug}`)')  # fmt: skip


#: Per action, whether a request's subject is still CURRENT: ``''`` when it is, else why and how to write it again.
SUBJECTS: Final[Mapping[str, Callable[[str], str]]] = {
    'session.integrator': _session_current,
    'task.integrator': _task_current,
}

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


def verify_held(
    credential_id: str, *, action: str, subject: str, key: Ed25519PublicKey | None = None,
    register: Register | None = None, now: float | None = None,
) -> Credential:  # fmt: skip
    """Spend the HELD credential *credential_id* (``state_dir()/<id>.json``) on one use of *action* on *subject*.

    The one door a consumer outside this package verifies a granted consent through (an entry point names it): the
    file is read from the consent state the user's ``grant`` wrote, then :func:`redeem`ed -- verified offline against
    the machine's issuer key, compared on action and subject BEFORE the use is registered, and registered once.

    Raises:
        ConsentRefused: no such held credential (naming the grant door), or anything :func:`redeem` refuses.

    """
    path = state_dir() / f'{credential_id}.json'
    try:
        credential = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as missing:
        msg = (f'no held {action} credential {credential_id!r} at {path} ({type(missing).__name__}): ask the user for '
               f'a code and run `python -m dev_lab.ops.consent grant <request.json> --code <code>` for action '
               f'{action} and subject {subject[:12]}..., then pass the granted id')  # fmt: skip
        raise ConsentRefused(msg) from missing
    return redeem(
        credential, action=action, subject=subject, key=public_key() if key is None else key,
        register=remote_register() if register is None else register, now=time.time() if now is None else now,
    )  # fmt: skip


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
    code: str | None, *, tty: bool | None = None, ask: Callable[[str], str] = input,
    read: Callable[[], str] = sys.stdin.readline, what: str = 'this consent',
) -> str:  # fmt: skip
    """The code the USER gave, checked as six digits BEFORE it is sent (:func:`dev_lab.dev.ask.code`).

    *code* when passed (the code the user gave an agent), else asked SHOWN AS TYPED at a terminal (D94), else one
    stdin line. The one intake of a user's code (CONSENT-CODE-FROM-THE-USER): a grant here, and ``sshhold open``.

    Raises:
        ConsentRefused: not six digits (control characters from a Windows paste, a short copy): nothing is sent.

    """
    on_tty = sys.stdin.isatty() if tty is None else tty
    given = code if code is not None or on_tty else read()
    try:
        return asked_code(given, what=what, ask=ask)
    except AskRefused as refused:
        msg = f'the cluster code {refused}; nothing was sent -- ask the user for a fresh code'
        raise ConsentRefused(msg) from refused


def _six_digits(code: str) -> str:
    return given_code(code)


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
    within: Counter[tuple[str, str]] | None = None, plan: str | None = None,
) -> list[Path]:  # fmt: skip
    """Send *payload* to the issuer; each credential it answered, verified and written private, by path.

    *within*, when given, counts the ``(action, subject)`` pairs an answer may hold: each at most as often as the
    plan grants it (one pair on two hosts is two grants).
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
    seen: Counter[tuple[str, str]] = Counter()
    for credential in answered if isinstance(answered, list) else [answered]:
        issued = verify(credential, key, now=now)
        pair = (issued.action, issued.subject)
        if within is not None and seen[pair] >= within[pair]:
            msg = f'the issuer answered a credential the plan does not grant once: {pair[0]} {pair[1][:12]}'
            raise ConsentRefused(msg)
        if issued.plan != plan:
            msg = f'the issuer answered a credential of plan {issued.plan}, not of {plan}: {pair[0]} {pair[1][:12]}'
            raise ConsentRefused(msg)
        seen[pair] += 1
        target = state_dir(home) / f'{issued.id}.json'
        write_private(target, json.dumps(credential, indent=1, sort_keys=True) + '\n')
        written.append(target)
    return written


def preflight(
    request: Mapping[str, Any],
    *,
    table: Mapping[str, Any] | None = None,
    send: Send = ssh_send,
    checks: Iterable[Check] = (),
    subjects: Mapping[str, Callable[[str], str]] = SUBJECTS,
    home: Path | None = None,
    now: float | None = None,
) -> Path:
    """Prove *request*'s grant can succeed, with no code; the receipt written (:func:`.door.record_receipt`).

    Raises:
        ConsentRefused: no endpoint or key, a malformed request, the issuer unreachable (named by its transport) or
            skewed, a subject no longer current, or a failed *checks* -- each naming its door; no receipt is written.

    """
    found = _endpoint(table)
    _proved(request, found, send, subjects)
    for check in checks:
        check()
    return record_receipt(request, home=home, now=now)


def _proved(
    request: Mapping[str, Any], found: Mapping[str, Any], send: Send, subjects: Mapping[str, Callable[[str], str]]
) -> None:
    """The no-code proof every lone request shares: key, shape, a current subject, the issuer reached and agreeing."""
    public_key(found)
    requested(dict(request))
    if (current := subjects.get(str(request['action']))) and (stale := current(str(request['subject']))):
        msg = f'no code asked: {stale}'
        raise ConsentRefused(msg)
    handshake(found, send=reached(send), actions=[request['action']])


def grant(
    request_file: Path,
    *,
    table: Mapping[str, Any] | None = None,
    code: str | None = None,
    tty: bool | None = None,
    ask: Callable[[str], str] = input,
    read: Callable[[], str] = sys.stdin.readline,
    send: Send = ssh_send,
    home: Path | None = None,
    now: Callable[[], float] = time.time,
    subjects: Mapping[str, Callable[[str], str]] = SUBJECTS,
) -> Path:
    """Ask the issuer for the credential *request_file* describes; the file it was written to.

    THE DOOR PREFLIGHTS ITSELF: whichever way the code arrives, the no-code proof (:func:`_proved`) runs here, right
    before the code is read, and a proof that is not green NOW refuses ``no code used`` (user ruling 2026-11-22: a
    code given 5 min after its preflight was refused on the receipt's age alone, and lost).

    Raises:
        ConsentRefused: a code given in advance has no receipt inside the backstop (:func:`.door.require_receipt`),
            the proof is not green now, the code is not six digits, or the issuer refused.

    """
    found = _endpoint(table)
    public_key(found)  # refused here, before the user spends a code
    request = json.loads(request_file.read_text(encoding='utf-8'))
    requested(request)
    on_tty = sys.stdin.isatty() if tty is None else tty
    if code is not None or not on_tty:  # the code was asked BEFORE this call: a preflight must have preceded the ask
        require_receipt(request, home=home, now=now())  # local: refused before any network call
        try:
            _proved(request, found, send, subjects)
        except ConsentRefused as blocked:
            msg = f'no code used -- the preflight is not green now: {str(blocked).removeprefix("no code asked: ")}'
            raise ConsentRefused(msg) from blocked
        given = _six_digits(given_code(code, tty=on_tty, ask=ask, read=read))
    else:  # the prompt follows a green preflight, run here
        preflight(request, table=found, send=send, home=home, now=now(), subjects=subjects)
        given = _six_digits(given_code(code, tty=on_tty, ask=ask, read=read))
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
        ConsentRefused: the plan is not the one shown or does not name *host*, a grant is malformed, it is not
            offered (:func:`.door.offer`: no green preflight, or a skewed issuer), the code is not six digits, or
            the issuer refused.

    """
    found = _endpoint(table)
    public_key(found)
    plan = load_plan(plan_file, shown)
    if host not in plan.hosts:
        msg = f'the plan opens {list(plan.hosts)}, not {host}: a code given for one plan never opens another host'
        raise ConsentRefused(msg)
    for grant_ in plan.grants:
        requested(plan_request(grant_))  # refused here, before the user spends a code
    offer(plan, found, send=send, home=home, now=now())  # green preflight, and an issuer this client agrees with
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
    within = Counter((grant_['action'], grant_['subject']) for grant_ in plan.grants)
    payload = {'verb': 'fetch-unspent', 'plan': plan.digest}
    return _issued(found, payload, send=send, home=home, now=now(), within=within, plan=plan.digest)
