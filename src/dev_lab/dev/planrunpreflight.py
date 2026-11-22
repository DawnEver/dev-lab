"""PLANRUN PREFLIGHT: every door of a plan checked on its hosts BEFORE the code is spent; nothing is run or redeemed.

Split out of :mod:`dev_lab.dev.planrun` (the run and the CLI); what is checked is that module's docstring. A
subject derivable HERE is derived here even when its door waits on an earlier config step (incident 2026-11-16: such
a step was skipped as ``after step N``, its subject never derived, and the granted plan's code was wasted). A green
preflight is recorded for the plan's digest (:func:`offered`): the one consent door offers a plan for a code only then.

A subject only an UNREACHED host can derive (no hold open, and it admits no login without a code) is read through the
issuer's read-only ``subject`` verb (:func:`dev_lab.ops.consent.door.subject_read`) -- no code (user ruling
2026-11-16: a plan takes exactly ONE code, spent once preflight is green; never a first code to open a hold).

GREEN SAYS WHAT IT CHECKED (incident 2026-11-22: ``green`` over an UNREACHABLE host, then the run stopped on a
refusal a reached preflight would have shown, and the code was spent). The last line is ``green, every door
checked`` or ``green, but N step(s) are unchecked: <what>`` -- the code buys the hold first and those are checked at
run. A refusal the host can name with no code (its read form's :data:`~dev_lab.ops.consent.actions.STANDING` line:
a token name already held) BLOCKS, unless an earlier step of the plan on that host may clear it (:func:`_stands`).
"""

from __future__ import annotations

import argparse
import re
import shlex
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Final

from lab_commons.config import section

from dev_lab.dev import devhost, devsource, forgesecrets, sshholdwire
from dev_lab.dev import remote as ssh_remote
from dev_lab.dev.forgeclient import client_for
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.planremote import Remote
from dev_lab.dev.planrunsteps import (
    CONFIG_ACTION,
    LOCAL_VERBS,
    REMOTE_DIR,
    Remotes,
    Step,
    Steps,
    last_line,
    ops_command,
    step_stdin,
)
from dev_lab.dev.reviewgate import DeclarationUnread, file_at, manifest_at
from dev_lab.ops import configdoor, forgeprotection
from dev_lab.ops.consent.actions import read_answer
from dev_lab.ops.consent.client import TABLE
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.consent.door import PREFLIGHT_FRESH_S, Send, handshake, record_preflight, ssh_send, subject_read
from dev_lab.ops.consent.plan import Plan, not_registered, unregistered
from dev_lab.ops.forgerequests import ACCOUNT_ACTION, REVOKE_ACTION
from dev_lab.ops.giteaadmin import ForgeRefused

__all__ = [
    'HOLD_NEEDED',
    'RULE',
    'UNREAD',
    'Declared',
    'Readers',
    'SourceReader',
    'config_subject',
    'declared_at',
    'host_ready',
    'issuer_subject',
    'listed_at',
    'offered',
    'preflight',
    'protect_target',
    'text_at',
]

#: ``(forge host, owner/name, ref)`` -> the repo's ``pyproject.toml`` text at the ref, read here.
type Declared = Callable[[str, str, str], str]


#: ``(source url, path, ref)`` -> that file's text at the ref, read here (:data:`.configdoor.SourceReader`).
type SourceReader = configdoor.SourceReader


#: A preflight that names a blocker refuses the code's request: a wall of this session (``walls``).
RULE: Final = 'PREFLIGHT-BEFORE-THE-CODE'


#: ssh's exit status when it could not reach the host at all (no session, no route, refused authentication).
_SSH_UNREACHED: Final = 255


#: An ssh login the host refused without a code: key-only ssh reached no hold (2026-11-13: an agent read the bare
#: ``Permission denied (keyboard-interactive)`` and could not tell it was a hold to open, not a host to fix).
_NO_HOLD: Final = re.compile(r'Permission denied \((?:[\w-]+,)*(?:keyboard-interactive|password)')


#: What a refused login means, and the exit: the plan first, then ONE code opens every host's hold.
HOLD_NEEDED: Final = (
    'no open ssh hold on this host, and it admits no login without a code. Build the plan first (the steps file '
    'and its plan.json; digest D: `python -m dev_lab.ops.consent plan <plan.json>`). A plan is offered for a code '
    "only after a green preflight; a step's subject only this host derives is read through the issuer's read-only "
    '`subject` verb, no code. Once green, `python -m dev_lab.dev.sshhold open --hours H --plan <plan.json> --digest '
    '<D>` takes the ONE code, opening every plan host not already held'
)


def host_ready(step: Step, remote: Remote) -> tuple[str | None, bool]:
    """``(blocker, reached)``: ``None`` when *step*'s host can verify and register a use; asked unprivileged.

    *reached* is false when the host did not answer at all (no held session, ssh could not connect).
    """
    try:
        said, status = remote.run(
            shlex.join([step.python, '-m', 'dev_lab.ops', '--config', step.config, 'consent', 'ready'])
        )
    except (sshholdwire.HoldRefused, OSError) as gone:
        return str(gone), False
    if status == _SSH_UNREACHED:
        last = last_line(said) or f'ssh exited {status}'
        return (f'{last} -- {HOLD_NEEDED}' if _NO_HOLD.search(said) else last), False
    return ((last_line(said) or f'consent ready exited {status}') if status else None), True


def _no_stdin(step: Step) -> str | None:
    """Why *step*'s stdin source is not here (its content never read into a message); ``None`` when it is."""
    if step.stdin_local is not None and not Path(step.stdin_local).is_file():
        return f'no stdin_local file here: {step.stdin_local}'
    if step.stdin_task is not None and not forgesecrets.stored_bundle(step.stdin_task):
        return f'no stored bundle for task {step.stdin_task} here: `forge secrets store --task {step.stdin_task}`'
    return None


def declared_at(forge: str, repo: str, ref: str) -> str:
    """*repo*'s ``pyproject.toml`` at *ref* on *forge*, read here through the forge client (never a working tree)."""
    return manifest_at(client_for(Path.cwd(), url=f'https://{forge}/{repo}.git'), ref)


def listed_at(source: str, where: str, ref: str) -> list[str]:
    """The file names directly in directory *where* at *ref* of the forge repo at *source*, read here."""
    client = client_for(Path.cwd(), url=source)
    try:
        answer: Any = client.call('GET', f'{client.repo}/contents/{where}?ref={ref}')
    except ForgeCallFailed as failed:
        msg = f'{where}/ at {ref} cannot be listed: {failed}'
        raise DeclarationUnread(msg) from failed
    if not isinstance(answer, list):
        msg = f'{where} at {ref} is not a directory'
        raise DeclarationUnread(msg)
    return [str(entry['name']) for entry in answer if isinstance(entry, dict) and entry.get('type') == 'file']


def text_at(source: str, path: str, ref: str) -> str:
    """*path* at *ref* of the forge repo at *source* (an https clone URL), read here through the forge client."""
    return file_at(client_for(Path.cwd(), url=source), path, ref)


def protect_target(argv: Sequence[str]) -> tuple[str, str]:
    """``(repo, ref)`` a ``forge protect apply`` argv names; the ref defaults as the host's parser does."""
    if '--repo' not in argv:
        msg = f'`{shlex.join(argv)}` names no --repo'
        raise ConsentRefused(msg)
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--repo')
    parser.add_argument('--ref', default=forgeprotection.DEFAULT_REF)
    found, _ = parser.parse_known_args(list(argv))
    return found.repo, found.ref


#: ``(dest, action, argv)`` -> ``(subject, standing refusal)`` *dest* answers for that step, read without a code.
type IssuerSubject = Callable[[str, str, list[str]], tuple[str, str | None]]


def issuer_subject(dest: str, action: str, argv: list[str]) -> tuple[str, str | None]:
    """*dest*'s subject (and standing refusal) for *action* as *argv*, through the issuer's read-only ``subject``."""
    return subject_read(section(TABLE), dest, action, argv, send=ssh_send)


@dataclass(frozen=True)
class Readers:
    """What a subject derived without a code reads (a declaration, a config source, the issuer's ``subject`` verb).

    The issuer's read-only ``subject`` verb answers for a subject only an unreached host derives.
    """

    declared: Declared = declared_at
    text: SourceReader = text_at
    listed: configdoor.SourceLister = listed_at
    config_source: Callable[[], str] = devsource.config_source
    issued: IssuerSubject = issuer_subject


def config_subject(
    host: str, read: SourceReader, source: str, ref: str = 'main', *, listed: configdoor.SourceLister = listed_at
) -> str:
    """The :data:`CONFIG_ACTION` subject of *host*'s reviewed file (``hosts/<host>.toml`` in *source*), derived here."""
    return configdoor.local_subject(source, devhost.host_file(host), read, ref, listed=listed)


def _derivable(step: Step) -> bool:
    return bool(step.forge or step.config_host)


def _local_subject(step: Step, readers: Readers) -> tuple[str, str]:
    """``(subject, where it was read)`` of a :func:`_derivable` step."""
    if step.config_host:
        source = readers.config_source()
        return config_subject(step.config_host, readers.text, source, listed=readers.listed), source
    repo, ref = protect_target(step.argv)
    read = partial(readers.declared, step.forge, repo)
    return forgeprotection.local_subject(repo, ref, step.forge, read), step.forge


#: The last line of a blocked preflight.
_BLOCKED: Final = 'preflight: BLOCKED (fix the named blocker before asking for a code)'


#: What a local derivation may refuse with; each names what it could not read.
UNREAD: Final = (ForgeRefused, DeclarationUnread, ForgeCallFailed, ConsentRefused, ValueError)


def _derived_here(granted: str, step: Step, readers: Readers) -> tuple[str, bool]:
    """``(verdict, blocked)`` of a step whose subject is derived HERE rather than asked of its host."""
    try:
        derived, where = _local_subject(step, readers)
    except UNREAD as unread:
        return f'BLOCKED -- the subject cannot be derived here ({unread})', True
    if derived != granted:
        return f'BLOCKED -- derived here {derived[:12]} from {where}, the plan grants {granted[:12]}', True
    return 'green (subject derived here)', False


def _unsettled(plan: Plan, steps: Steps, index: int, readers: Readers) -> str | None:
    """A blocker when an unreached host's config step assumes its live ``[ops.config]`` already declares the family.

    That holds when no earlier step on that host grants the subject a host without the family derives.

    Such a host fetches the host file alone (:func:`configdoor.unsettled_subject`), so the plan would stop at run,
    after its code is spent. The door is the two-step plan: a ``config apply`` with no ``config_host`` granting that
    subject first (it installs the family declaration), then this step.
    """
    step = steps.steps[index]
    try:
        first = configdoor.unsettled_subject(readers.config_source(), devhost.host_file(step.config_host), readers.text)
    except (*UNREAD, configdoor.ConfigRefused) as unread:
        return f'BLOCKED -- the subject a host without the family derives cannot be read here ({unread})'
    if first is None or first == plan.grants[index]['subject']:
        return None
    earlier = [
        plan.grants[i]['subject'] for i in range(index)
        if steps.steps[i].dest == step.dest and plan.grants[i]['action'] == CONFIG_ACTION
    ]  # fmt: skip
    if first in earlier:
        return None
    return (
        f'BLOCKED -- the candidate declares an [ops.config] family; a host whose live table does not yet declares it '
        f'derives {first[:12]}, not {plan.grants[index]["subject"][:12]}: plan two config applies on {step.dest} -- '
        f'first one with no config_host granting {first[:12]}, then this one -- or hold a session so the host is read'
    )


#: The actions whose earlier step on a host may clear a later step's standing refusal: a login made, a name revoked.
_CLEARING: Final = frozenset({ACCOUNT_ACTION, REVOKE_ACTION})


#: ``(verdict, blocked, what stays unchecked until the run -- '' when nothing)`` of one host step.
type Checked = tuple[str, bool, str]


def _stands(refusal: str | None, plan: Plan, steps: Steps, index: int) -> Checked | None:
    """The verdict of step *index* when its host would refuse it AS IT STANDS (*refusal*); ``None`` when it would not.

    Blocked -- the code would be spent on it -- unless an earlier step of the plan on that host may clear it.
    """
    if refusal is None:
        return None
    dest = steps.steps[index].dest
    clears = next(
        (i + 1 for i in reversed(range(index))
         if steps.steps[i].dest == dest and not steps.steps[i].local and plan.grants[i]['action'] in _CLEARING),
        None,
    )  # fmt: skip
    if clears is None:
        return f'BLOCKED -- its host would refuse it as it stands ({refusal}): re-author the plan', True, ''
    return (
        f'green; as it stands its host would refuse it ({refusal})',
        False,
        f'whether step {clears} clears "{refusal}"',
    )


def _read_unreached(plan: Plan, steps: Steps, index: int, readers: Readers) -> Checked:
    """The verdict of a step on an unreached host whose subject only that host derives: read, no code."""
    grant, step = plan.grants[index], steps.steps[index]
    if step.stdin_local is not None or step.stdin_task is not None:
        return 'BLOCKED -- its host is unreachable and its subject hashes stdin that never leaves here', True, ''
    try:
        derived, refusal = readers.issued(step.dest, grant['action'], list(step.argv))
    except (ConsentRefused, OSError) as unread:
        return f"BLOCKED -- its host is unreachable and its subject is the host's to derive ({unread})", True, ''
    if derived != grant['subject']:
        why = f'the host derives subject {derived[:12]}, the plan grants {grant["subject"][:12]} (read)'
        return f'BLOCKED -- {why}', True, ''
    return _stands(refusal, plan, steps, index) or ('green (subject read from the host, no code)', False, '')


def _host_check(plan: Plan, steps: Steps, index: int, remote: Remote, readers: Readers) -> Checked:
    """The verdict of host step *index*: its door, else an earlier config step on its host, then its subject."""
    grant, step = plan.grants[index], steps.steps[index]
    if missing := _no_stdin(step):
        return f'BLOCKED -- {missing}', True, ''
    placeholder = f'{REMOTE_DIR}/preflight.json'
    said, status = remote.run(ops_command(step, [*step.argv, '--credential', placeholder], sudo='sudo -n -l'))
    here = [i for i in range(index) if not steps.steps[i].local and steps.steps[i].dest == step.dest]
    after = next((i + 1 for i in reversed(here) if plan.grants[i]['action'] == CONFIG_ACTION), None)
    if status:
        if after and _derivable(step):
            verdict, blocked = _derived_here(grant['subject'], step, readers)
            return (f'{verdict}; its door after step {after} (installed by that config apply)', blocked,
                    f'its door, installed by step {after}')  # fmt: skip
        if after:
            return (f'after step {after} (its door is installed by that config apply)', False,
                    f'its door and subject, after step {after}')  # fmt: skip
        return f'BLOCKED -- no sudo door for `{shlex.join(step.argv)}` ({last_line(said)})', True, ''
    if step.forge:
        return (*_derived_here(grant['subject'], step, readers), '')
    return _asked_of_host(plan, steps, index, remote, after)


def _asked_of_host(plan: Plan, steps: Steps, index: int, remote: Remote, after: int | None) -> Checked:
    """The verdict of the subject step *index*'s host derives (its verb's ``--subject``) against the grant's."""
    granted, step = plan.grants[index]['subject'], steps.steps[index]
    said, status = remote.run(ops_command(step, [*step.argv, '--subject']), step_stdin(step))
    derived, refusal = read_answer(said)
    if not status and derived != granted and after:
        return (f'after step {after} (subject derived once step {after} applied)', False,
                f'its subject, derived once step {after} applied')  # fmt: skip
    if status or derived != granted:
        why = (f'the host could not derive the subject ({derived})' if status else
               f'the host derives subject {derived[:12]}, the plan grants {granted[:12]}')  # fmt: skip
        return f'BLOCKED -- {why}', True, ''
    return _stands(refusal, plan, steps, index) or ('green', False, '')


#: What no preflight can ask of a host it did not reach, whichever way the step's subject was checked.
_UNREACHED: Final = "unreached: its host's readiness, its sudo door and any refusal its subject read does not report"
_ASK: Final = (f'(ask the user for the code: this green is valid {PREFLIGHT_FRESH_S:.0f} s -- `python -m dev_lab.ops.'
               'consent plan <plan.json>` says with no code if it is; stale, re-run preflight first)')  # fmt: skip


def _last(unchecked: Sequence[str], *, blocked: bool) -> str:
    """The verdict line: blocked, green with every door checked, or green naming each step left to the run."""
    if blocked:
        return _BLOCKED
    if not unchecked:
        return f'preflight: green, every door checked {_ASK}'
    return (f'preflight: green, but {len(unchecked)} step(s) are unchecked: {"; ".join(unchecked)} -- the code buys '
            f'the hold first and these are checked at run, where a refusal stops the plan {_ASK}')  # fmt: skip


def preflight(
    plan: Plan,
    steps: Steps,
    remotes: Remotes,
    *,
    machine: Callable[[str], Mapping[str, Any]] = section,
    readers: Readers | None = None,
) -> tuple[bool, list[str]]:
    """``(green, lines)``: every check of the module docstring, BEFORE a code; the lines name each blocker."""
    readers = readers or Readers()
    stale = unregistered(plan)
    lines = [f'plan: BLOCKED -- {not_registered(stale)}'] if stale else []
    blocked = bool(stale)
    hosts = {step.dest: step for step in reversed(steps.steps) if not step.local}
    unreached: set[str] = set()
    unchecked: list[str] = []
    for dest in dict.fromkeys(step.dest for step in steps.steps if not step.local):  # each host once, in order
        fault, reached = host_ready(hosts[dest], remotes(dest))
        if not reached:
            unreached.add(dest)
            if ssh_remote.HOST_KEY_RULE in str(fault):  # no code opens a host whose key cannot be checked
                blocked = True
                lines.append(f'host {dest}: BLOCKED -- {fault}')
                continue
            lines.append(f'host {dest}: UNREACHABLE ({fault}) -- derivable subjects are checked here, its doors at run')
            continue
        lines.append(f'host {dest}: {"BLOCKED -- " + fault if fault else "ready"}')
        blocked = blocked or fault is not None
    for index, grant in enumerate(plan.grants):
        step = steps.steps[index]
        name = f'step {index + 1} {grant["action"]}'
        if step.local:
            table = LOCAL_VERBS[grant['action']].table
            endpoint = machine(table).get('endpoint')
            fault, later = not endpoint, ''
            verdict = (f'BLOCKED -- the machine file has no [{table}] endpoint' if fault else
                       f'green (here: python -m {shlex.join(step.argv)} via {endpoint})')  # fmt: skip
        elif step.dest in unreached:
            verdict, fault, later = (
                (*_derived_here(grant['subject'], step, readers), '') if _derivable(step) else
                _read_unreached(plan, steps, index, readers)
            )  # fmt: skip
            if not fault and step.config_host and (unsettled := _unsettled(plan, steps, index, readers)):
                verdict, fault = unsettled, True
            verdict = f'{verdict} on {step.dest} (unreachable: its door is checked at run)'
            later = f'{_UNREACHED}; {later}' if later else _UNREACHED
        else:
            verdict, fault, later = _host_check(plan, steps, index, remotes(step.dest), readers)
            verdict = f'{verdict} on {step.dest}'
        if grant['action'] in stale:
            verdict, fault = f'BLOCKED -- {not_registered([grant["action"]])}', True
        lines.append(f'{name}: {verdict}')
        blocked = blocked or fault
        if later and not fault:
            unchecked.append(f'{name} on {step.dest} ({later})')
    lines.append(_last(unchecked, blocked=blocked))
    return not blocked, lines


def offered(
    plan: Plan, found: tuple[bool, list[str]], *, table: Mapping[str, Any] | None = None, send: Send = ssh_send,
    home: Path | None = None,
) -> tuple[bool, list[str]]:  # fmt: skip
    """*found*, a preflight's verdict, completed by the issuer handshake and recorded for its digest when green."""
    green, lines = found
    if not green:
        return found
    try:
        handshake(section(TABLE) if table is None else table, send=send, actions=[g['action'] for g in plan.grants])
    except ConsentRefused as skewed:
        return False, [*lines[:-1], f'issuer: BLOCKED -- {skewed}', _BLOCKED]
    record_preflight(plan, home=home)
    return True, [*lines, f'issuer: agrees; plan {plan.digest[:12]} offered for one code']
