"""PLANRUN PREFLIGHT: every door of a plan checked on its hosts BEFORE the code is spent; nothing is run or redeemed.

Split out of :mod:`dev_lab.dev.planrun` (the run and the CLI); what is checked is that module's docstring.
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

from dev_lab.dev import devhost, forgesecrets, sshholdwire
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgework import client_for
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
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.consent.plan import STALE_CLIENT, Plan, stale_client
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
    'and its plan.json; digest D: `python -m dev_lab.ops.consent plan <plan.json>`), then ask the user for the one '
    'code: `python -m dev_lab.dev.sshhold open --hours H --plan <plan.json> --digest <D>` opens every plan host, '
    'and preflight re-runs through the held sessions'
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


@dataclass(frozen=True)
class Readers:
    """What a subject derived HERE reads: a repo's declaration, a config source's files, and that source's URL."""

    declared: Declared = declared_at
    text: SourceReader = text_at
    config_source: Callable[[], str] = devhost.config_source


def config_subject(host: str, read: SourceReader, source: str, ref: str = 'main') -> str:
    """The :data:`CONFIG_ACTION` subject of *host*'s reviewed file (``hosts/<host>.toml`` in *source*), derived here."""
    return configdoor.local_subject(source, devhost.host_file(host), read, ref)


def _derivable(step: Step) -> bool:
    return bool(step.forge or step.config_host)


def _local_subject(step: Step, readers: Readers) -> tuple[str, str]:
    """``(subject, where it was read)`` of a :func:`_derivable` step."""
    if step.config_host:
        source = readers.config_source()
        return config_subject(step.config_host, readers.text, source), source
    repo, ref = protect_target(step.argv)
    read = partial(readers.declared, step.forge, repo)
    return forgeprotection.local_subject(repo, ref, step.forge, read), step.forge


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


def _host_check(plan: Plan, steps: Steps, index: int, remote: Remote, readers: Readers) -> tuple[str, bool]:
    """``(verdict, blocked)`` of host step *index*: its door, else an earlier config step on its host, then subject."""
    grant, step = plan.grants[index], steps.steps[index]
    if missing := _no_stdin(step):
        return f'BLOCKED -- {missing}', True
    placeholder = f'{REMOTE_DIR}/preflight.json'
    said, status = remote.run(ops_command(step, [*step.argv, '--credential', placeholder], sudo='sudo -n -l'))
    here = [i for i in range(index) if not steps.steps[i].local and steps.steps[i].dest == step.dest]
    after = next((i + 1 for i in reversed(here) if plan.grants[i]['action'] == CONFIG_ACTION), None)
    if status:
        if after:
            return f'after step {after} (its door is installed by that config apply)', False
        return f'BLOCKED -- no sudo door for `{shlex.join(step.argv)}` ({last_line(said)})', True
    if step.forge:
        return _derived_here(grant['subject'], step, readers)
    return _asked_of_host(grant['subject'], step, remote, after)


def _asked_of_host(granted: str, step: Step, remote: Remote, after: int | None) -> tuple[str, bool]:
    """``(verdict, blocked)`` of the subject *step*'s host derives (its verb's ``--subject``) against *granted*."""
    said, status = remote.run(ops_command(step, [*step.argv, '--subject']), step_stdin(step))
    derived = last_line(said)
    if not status and derived != granted and after:
        return f'after step {after} (subject derived once step {after} applied)', False
    if status or derived != granted:
        why = (f'the host could not derive the subject ({derived})' if status else
               f'the host derives subject {derived[:12]}, the plan grants {granted[:12]}')  # fmt: skip
        return f'BLOCKED -- {why}', True
    return 'green', False


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
    stale = stale_client(plan)
    lines = [f'plan: BLOCKED -- {stale} unknown to this client: {STALE_CLIENT}'] if stale else []
    blocked = bool(stale)
    hosts = {step.dest: step for step in reversed(steps.steps) if not step.local}
    unreached: set[str] = set()
    for dest in dict.fromkeys(step.dest for step in steps.steps if not step.local):  # each host once, in order
        fault, reached = host_ready(hosts[dest], remotes(dest))
        if not reached:
            unreached.add(dest)
            lines.append(f'host {dest}: UNREACHABLE ({fault}) -- derivable subjects are checked here, its doors at run')
            continue
        lines.append(f'host {dest}: {"BLOCKED -- " + fault if fault else "ready"}')
        blocked = blocked or fault is not None
    for index, grant in enumerate(plan.grants):
        step = steps.steps[index]
        name = f'step {index + 1} {grant["action"]}'
        if step.local:
            table = LOCAL_VERBS[grant['action']][1]
            endpoint = machine(table).get('endpoint')
            fault = not endpoint
            verdict = (f'BLOCKED -- the machine file has no [{table}] endpoint' if fault else
                       f'green (here: forge {shlex.join(step.argv)} via {endpoint})')  # fmt: skip
        elif step.dest in unreached:
            verdict, fault = (
                _derived_here(grant['subject'], step, readers) if _derivable(step) else
                ("BLOCKED -- its host is unreachable and its subject is the host's to derive", True)
            )  # fmt: skip
            verdict = f'{verdict} on {step.dest} (unreachable: its door is checked at run)'
        else:
            verdict, fault = _host_check(plan, steps, index, remotes(step.dest), readers)
            verdict = f'{verdict} on {step.dest}'
        if grant['action'] in stale:
            verdict, fault = f'BLOCKED -- unknown to this client: {STALE_CLIENT}', True
        lines.append(f'{name}: {verdict}')
        blocked = blocked or fault
    lines.append('preflight: BLOCKED (fix the named blocker before asking for a code)' if blocked else
                 'preflight: green (ask the user for the code)')  # fmt: skip
    return not blocked, lines
