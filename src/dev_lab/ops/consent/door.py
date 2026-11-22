"""THE ONE CONSENT DOOR: everything that must hold BEFORE the user is asked for a code, and the wire it rides.

Every code intake -- ``consent grant`` (a lone request: break-glass waves, the hpc session role) and a plan's
``sshhold open --plan`` -- passes :func:`handshake`; a plan passes :func:`offer` as well, which ``consent plan``
runs as it shows the plan. A refusal here spends no code: the user is never asked for one that would be wasted.

* :func:`handshake` asks the issuer ``hello`` and compares what both sides must agree on: the credential FIELD SET
  (:data:`~dev_lab.ops.consent.credential.FIELDS`) and the registry actions the request names. A skewed pair is
  refused locally, naming which side is older and its upgrade door (incident 2026-11-16: a code was spent, then the
  client refused every credential with "a credential carries exactly the fields ...").
* :func:`subject_read` asks the issuer ``subject`` -- a READ: the host derives a step's subject with its verb's
  ``--subject`` and nothing else (:func:`read_argv` refuses any other form), so a preflight needs no code to check a
  subject only the host can derive (user ruling 2026-11-16: a plan takes exactly ONE code, spent once preflight is
  green -- never a first code to open a hold for the read).
* :func:`record_preflight` / :func:`offer`: a plan is offered for a code only after ``planrun preflight`` was green
  for its digest -- every host door and every subject (incident 2026-11-16: a plan whose subject could not be
  derived was granted, and its code was wasted).
* THE RECEIPT of a lone request (:func:`record_receipt` / :func:`require_receipt`): its preflight
  (:func:`dev_lab.ops.consent.client.preflight`) was green for its action and subject within
  :data:`RECEIPT_FRESH_S`; a code given in advance (``--code``, stdin) without one is refused before any network
  call, naming :data:`PREFLIGHT_DOOR` (incidents 2026-11-20: an issuer without the handshake, a host key never
  enrolled, a task identity changed after the request was written). :func:`fresh_receipts` is the read a Stop
  hook takes through ``python -m dev_lab.ops.consent receipts``.
* :func:`reached` wraps a :data:`Send` so an ssh transport failure (255) is named by its cause and door -- an unknown
  host key is ``devhost enrol`` -- never read as an old issuer.

:func:`ssh_send` is the one JSON-line transport to an endpoint table (consent issuer, break-glass server); it
lives here so the consent client imports no ``dev_lab.dev`` client module (the former
``ops.consent -> dev.forgebreakglass`` import cycle).
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, Final

from lab_commons.config import section

from dev_lab.dev import remote
from dev_lab.dev.consentguard import state_dir
from dev_lab.ops.consent.actions import ACTIONS, read_answer
from dev_lab.ops.consent.credential import FIELDS, ConsentRefused
from dev_lab.ops.consent.plan import Plan, not_registered, unregistered
from dev_lab.ops.totp import write_private

__all__ = [
    'CLIENT_UPGRADE',
    'ISSUER_UPGRADE',
    'PREFLIGHT_DOOR',
    'PREFLIGHT_FRESH_S',
    'RECEIPT_FRESH_S',
    'SSH_FAILED',
    'Send',
    'fresh_receipts',
    'handshake',
    'hello',
    'offer',
    'reached',
    'read_argv',
    'receipt_path',
    'record_preflight',
    'record_receipt',
    'require_receipt',
    'ssh_send',
    'subject_read',
]

#: ``(endpoint table, request)`` -> ``(exit status, output)``: one JSON line to an endpoint.
Send = Callable[[Mapping[str, Any], dict[str, Any]], tuple[int, str]]

#: The door of a client older than its issuer.
CLIENT_UPGRADE: Final = (
    'local dev-lab is older than the issuer; update it: '
    'pull dev-lab here and run `python -m dev_lab.dev.dep --bootstrap <checkout>`'
)
#: The door of an issuer older than its client.
ISSUER_UPGRADE: Final = (
    "the consent issuer's dev-lab is older than this client: upgrade the issuer host (its `ops upgrade --follow` "
    'timer installs [ops.upgrade] follow), then ask again'
)
#: How long a green preflight offers its plan for a code.
PREFLIGHT_FRESH_S: Final = 3600.0
#: How long a lone request's green preflight admits the code the user gives for it.
RECEIPT_FRESH_S: Final = 300.0
#: The preflight a lone request's code waits for (a verb may expose it as its own ``--preflight``).
PREFLIGHT_DOOR: Final = 'python -m dev_lab.ops.consent preflight <request.json>'
#: ssh's own exit status: the transport failed, the remote command never ran.
SSH_FAILED: Final = 255
_HOST_KEY: Final = 'Host key verification failed'
_RECEIPTS: Final = 'receipts'


def ssh_send(table: Mapping[str, Any], request: dict[str, Any]) -> tuple[int, str]:
    """Send *request* as one JSON line to *table*'s ``endpoint`` over ``ssh -T``; ``(exit status, its output)``.

    The endpoint's host key is checked strictly: against *table*'s ``known_hosts`` file where a host table names
    one, else against the machine file's ``[ssh] host_keys`` declaration (``remote.HOST_KEY_RULE``). A missing or
    placeholder declaration answers status 255 with the named refusal; ssh never runs.
    """
    identity = str(table['identity']) if table.get('identity') else None
    endpoint, line = str(table['endpoint']), json.dumps(request) + '\n'
    if table.get('known_hosts'):
        return remote.piped(endpoint, line, identity=identity, known_hosts=str(table['known_hosts']), timeout_s=180)
    declared = section('ssh').get('host_keys')
    try:
        return remote.declared_piped(
            endpoint, line, identity=identity, timeout_s=180, host_keys=declared if isinstance(declared, dict) else {}
        )
    except remote.HostKeyUndeclared as refused:
        return 255, str(refused)


def reached(send: Send, what: str = 'the consent issuer') -> Send:
    """*send*, refusing an ssh transport failure by its cause and door before any answer is read as the issuer's.

    Raises:
        ConsentRefused: ssh exited 255 -- an unknown host key names ``devhost enrol``, anything else the endpoint.

    """

    def wrapped(table: Mapping[str, Any], request: dict[str, Any]) -> tuple[int, str]:
        status, said = send(table, request)
        if status != SSH_FAILED:
            return status, said
        endpoint = str(table.get('endpoint') or '(no endpoint)')
        last = said.strip().splitlines()[-1] if said.strip() else 'no output'
        if _HOST_KEY in said:
            door = ("this machine does not know the host's key (never enrolled): run `python -m dev_lab.dev.devhost "
                    'enrol` here, then preflight again')  # fmt: skip
        else:
            door = 'it is unreachable over ssh: check the endpoint, its identity and the network, then preflight again'
        msg = f'no code asked: {what} {endpoint} -- {door} ({last})'
        raise ConsentRefused(msg)

    return wrapped


def hello() -> dict[str, list[str]]:
    """What this side speaks: the credential field set and the registry actions (the issuer's ``hello`` answer)."""
    return {'fields': list(FIELDS), 'actions': sorted(ACTIONS)}


#: The argv words a ``subject`` read refuses: each makes the verb act (redeem a credential, follow a ref) or is the
#: read's own flag, which the reader adds itself.
_ACTING: Final = frozenset({'--credential', '--follow', '--subject'})


def read_argv(action: str, argv: object) -> list[str]:
    """The ops argv the issuer's ``subject`` verb runs for *action*: *argv* + ``--subject``, admitted read-only.

    Raises:
        ConsentRefused: *action* admits no host-side read (its registry ``reads``), *argv* is not that verb, or it
            carries an acting flag (:data:`_ACTING`).

    """
    row = ACTIONS.get(action)
    if row is None or not row.reads:
        msg = f'{action} admits no subject read at its host (registry reads); derive it where its content lives'
        raise ConsentRefused(msg)
    words = list(argv) if isinstance(argv, list) and all(isinstance(word, str) for word in argv) else None
    if words is None or tuple(words[: len(row.reads)]) != row.reads:
        msg = f'a {action} subject read runs `{" ".join(row.reads)} ...` only'
        raise ConsentRefused(msg)
    if acting := sorted(_ACTING & set(words)):
        msg = f'a subject read never carries {acting}: it only reads and hashes'
        raise ConsentRefused(msg)
    return [*words, '--subject']


def _host(dest: str) -> str:
    return dest.rsplit('@', 1)[-1]


def subject_read(
    table: Mapping[str, Any], dest: str, action: str, argv: list[str], *, send: Send
) -> tuple[str, str | None]:
    """``(subject, standing refusal)`` *dest* answers for *action* run as *argv*, through the issuer -- no code.

    The refusal is what the host would refuse the request with as it stands (:func:`.actions.read_answer`), else
    ``None``.

    Raises:
        ConsentRefused: the issuer is not *dest*'s host (it reads only its own), or it refused or could not derive.

    """
    read_argv(action, argv)  # refused here first: nothing that could act is ever sent
    endpoint = str(table.get('endpoint') or '')
    if _host(endpoint) != _host(dest):
        msg = f'the issuer ({_host(endpoint) or "none declared"}) reads only its own host, not {_host(dest)}'
        raise ConsentRefused(msg)
    status, said = send(table, {'verb': 'subject', 'action': action, 'argv': argv})
    subject, refusal = read_answer(said)
    if status or not subject:
        msg = f'the issuer could not read the subject ({status}): {subject or "no answer"}'
        raise ConsentRefused(msg)
    return subject, refusal


def _answer(said: str) -> object:
    for line in said.splitlines():
        try:
            return json.loads(line)
        except ValueError:
            continue
    return None


def handshake(table: Mapping[str, Any], *, send: Send, actions: Iterable[str] = ()) -> None:
    """Refuse, before any code, an issuer this client cannot redeem with; *actions* are the ones about to be asked.

    Raises:
        ConsentRefused: the issuer predates ``hello``, its field set differs, or it lacks an asked action -- each
            naming the side to upgrade and its door.

    """
    status, said = send(table, {'verb': 'hello'})
    answer = _answer(said) if status == 0 else None
    if not isinstance(answer, dict) or not isinstance(answer.get('fields'), list):
        msg = f'no code asked: the issuer answered no version handshake ({status}): {ISSUER_UPGRADE}'
        raise ConsentRefused(msg)
    theirs, ours = set(answer['fields']), set(FIELDS)
    if theirs != ours:
        older = CLIENT_UPGRADE if theirs > ours else ISSUER_UPGRADE
        msg = (f'no code asked: the issuer signs fields {sorted(theirs ^ ours)} this client '
               f'{"lacks" if theirs > ours else "requires"}: {older}')  # fmt: skip
        raise ConsentRefused(msg)
    if unknown := sorted(set(actions) - set(answer.get('actions') or [])):
        msg = f'no code asked: the issuer does not know {unknown}: {ISSUER_UPGRADE}'
        raise ConsentRefused(msg)


def _stamp(digest: str, home: Path | None) -> Path:
    return state_dir(home) / 'preflight' / f'{digest}.json'


def record_preflight(plan: Plan, *, home: Path | None = None, now: float | None = None) -> Path:
    """Record that ``planrun preflight`` was green for *plan* -- every door and every subject; the record's path."""
    path = _stamp(plan.digest, home)
    write_private(path, json.dumps({'green': True, 'at': time.time() if now is None else now}) + '\n')
    return path


def offer(
    plan: Plan, table: Mapping[str, Any], *, send: Send, home: Path | None = None, now: float | None = None
) -> None:
    """Refuse to offer *plan* for a code unless this client knows it, preflight was green for it, and the issuer agrees.

    Raises:
        ConsentRefused: the named blocker; no code was asked.

    """
    if stale := unregistered(plan):
        msg = f'no code asked: {not_registered(stale)}'
        raise ConsentRefused(msg)
    path, clock = _stamp(plan.digest, home), time.time() if now is None else now
    at = json.loads(path.read_text(encoding='utf-8')).get('at', 0) if path.is_file() else None
    if at is None or clock - at > PREFLIGHT_FRESH_S:
        why = 'none recorded' if at is None else f'the green one is {clock - at:.0f} s old'
        msg = (f'no code asked: plan {plan.digest[:12]} has no green preflight ({why}): run `python -m dev_lab.dev.'
               'planrun preflight --plan <plan.json> --steps <steps.json>` and fix every blocker')  # fmt: skip
        raise ConsentRefused(msg)
    handshake(table, send=send, actions=[grant['action'] for grant in plan.grants])


def receipt_path(action: str, subject: str, *, home: Path | None = None) -> Path:
    """Where the receipt of *action* on *subject* lives: one file per pair, never the subject in its name."""
    key = hashlib.sha256(f'{action}\n{subject}'.encode()).hexdigest()[:32]
    return state_dir(home) / 'preflight' / _RECEIPTS / f'{key}.json'


def record_receipt(request: Mapping[str, Any], *, home: Path | None = None, now: float | None = None) -> Path:
    """Record that *request*'s preflight was green; the receipt's path."""
    action, subject = str(request['action']), str(request['subject'])
    path = receipt_path(action, subject, home=home)
    stamp = {'action': action, 'subject': subject, 'at': time.time() if now is None else now}
    write_private(path, json.dumps(stamp) + '\n')
    return path


def _age(path: Path, clock: float) -> float | None:
    try:
        return clock - float(json.loads(path.read_text(encoding='utf-8'))['at'])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def require_receipt(request: Mapping[str, Any], *, home: Path | None = None, now: float | None = None) -> None:
    """Refuse a code given in advance for *request* unless its preflight was green within :data:`RECEIPT_FRESH_S`.

    Local only: nothing is sent.

    Raises:
        ConsentRefused: no receipt for this action and subject, or a stale one -- naming :data:`PREFLIGHT_DOOR`.

    """
    action, subject = str(request.get('action')), str(request.get('subject'))
    age = _age(receipt_path(action, subject, home=home), time.time() if now is None else now)
    if age is not None and 0 <= age <= RECEIPT_FRESH_S:
        return
    why = 'none recorded' if age is None else f'the green one is {age:.0f} s old'
    msg = (
        f'no code asked: no fresh preflight for {action} on {subject[:40]!r} ({why}): run `{PREFLIGHT_DOOR}` (or the '
        f"verb's --preflight) BEFORE asking the user for a code, then pass the code within {RECEIPT_FRESH_S:.0f} s"
    )
    raise ConsentRefused(msg)


def fresh_receipts(*, home: Path | None = None, now: float | None = None) -> list[dict[str, Any]]:
    """Every receipt still fresh, oldest first: what a code may be asked for right now."""
    folder, clock = state_dir(home) / 'preflight' / _RECEIPTS, time.time() if now is None else now
    found = []
    for path in sorted(folder.glob('*.json')) if folder.is_dir() else ():
        age = _age(path, clock)
        if age is not None and 0 <= age <= RECEIPT_FRESH_S:
            found.append(json.loads(path.read_text(encoding='utf-8')))
    return sorted(found, key=lambda stamp: stamp['at'])
