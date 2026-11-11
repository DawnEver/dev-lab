"""A PLAN'S STEPS ON ITS HOST: check every door BEFORE the code is spent, then run the granted steps in order.

A code is never wasted (incidents 2026-11-11: a code spent, then the host refused -- no consent key, a sudo door
installed only by a later ``config apply``, an issuer it could not reach; and a hand-written wrapper deleted an
UNSPENT credential). Two verbs, one steps file::

    python -m dev_lab.dev.planrun preflight <dest> --plan <plan.json> --steps <steps.json>
    python -m dev_lab.dev.planrun run <dest> --plan <plan.json> --digest <D> --steps <steps.json>

The STEPS FILE says what each grant of the plan runs on the host, in the plan's order (one step per grant)::

    {"config": "/etc/dev-lab/supervise.toml", "python": "/usr/bin/python3",
     "steps": [{"argv": ["config", "apply", "--from", "/srv/plan/candidate.toml"]},
               {"argv": ["secret", "place", "--path", "/etc/x"], "stdin": "/srv/plan/x.secret"}]}

each step running ``sudo -n <python> -m dev_lab.ops --config <config> <argv...> --credential <file>`` (``stdin`` a
file ON THE HOST, so a secret never rides a command line or the hold's audit).

:func:`preflight` spends no code. Per host it asks ``consent ready`` (the verifier key resolves, a use can register);
per step, that the ops verb is a sudo door (``sudo -n -l``) and that the subject the host derives (the verb's
``--subject``) equals the grant's. A door a host gains only from an earlier ``ops.config`` step (``config apply``
installs sudoers) is ``after step N``, never a failure. The remote is the held session (:mod:`.sshhold`) when one
is open, else plain key-only ssh.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev import remote as ssh_remote
from dev_lab.dev import sshhold
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.consent.plan import Plan, parsed

__all__ = [
    'CONFIG_ACTION',
    'REMOTE_DIR',
    'HeldRemote',
    'Remote',
    'SshRemote',
    'Steps',
    'load_steps',
    'main',
    'ops_command',
    'preflight',
    'remote_for',
]

#: The action whose step changes the host's config -- and so may install the sudo doors of the steps after it.
CONFIG_ACTION: Final = 'ops.config'
#: Where a carried credential lives on the host, relative to the session account's home (umask 077).
REMOTE_DIR: Final = '.dev-lab/consent'
_TIMEOUT_S: Final = 600.0


class Remote(Protocol):
    """A host a plan runs on: one shell command at a time, and one private file put."""

    def run(self, command: str) -> tuple[str, int]:
        """``(merged output, exit status)`` of *command* (a POSIX shell line)."""
        ...

    def put(self, path: str, text: str) -> None:
        """Write *text* at *path* under umask 077; its content never reaches an argv or an audit."""
        ...


@dataclass(frozen=True)
class HeldRemote:
    """The held session of *dest* (:mod:`.sshhold`): no new authentication, no code."""

    dest: str

    def run(self, command: str) -> tuple[str, int]:
        """Run *command* on the held connection."""
        return sshhold.run_command(self.dest, command)

    def put(self, path: str, text: str) -> None:
        """Write *text* through the held channel; audited as a path and a sha256 prefix."""
        sshhold.put_private(self.dest, path, text)


@dataclass(frozen=True)
class SshRemote:
    """Plain key-only ssh to *dest* (never prompts): for a host whose account needs no second factor."""

    dest: str

    def _ssh(self, command: str, data: str | None) -> tuple[str, int]:
        argv = ssh_remote.ssh_argv(self.dest, command, batch=True)
        done = _door.run(argv, input=data, capture_output=True, text=True, check=False, timeout=_TIMEOUT_S)
        return done.stdout + done.stderr, done.returncode

    def run(self, command: str) -> tuple[str, int]:
        """Run *command* over a fresh key-only connection."""
        return self._ssh(command, None)

    def put(self, path: str, text: str) -> None:
        """Write *text* at *path*: the content on ssh's stdin, never its argv."""
        output, status = self._ssh(_put_command(path), text)
        if status:
            msg = f'{self.dest}: could not write {path} ({status}): {output.strip()}'
            raise sshhold.HoldRefused(msg)


def _put_command(path: str) -> str:
    quoted = shlex.quote(path)
    return f'umask 077 && mkdir -p "$(dirname {quoted})" && cat > {quoted}'


def remote_for(dest: str) -> Remote:
    """*dest*'s held session when one is recorded, else plain key-only ssh."""
    return HeldRemote(dest) if sshhold.read_session(dest) is not None else SshRemote(dest)


@dataclass(frozen=True)
class Steps:
    """A steps file: the host's ops config and python, and per grant its ops argv and an optional stdin file."""

    config: str
    python: str
    argv: tuple[tuple[str, ...], ...]
    stdin: tuple[str | None, ...]


def load_steps(path: Path, plan: Plan) -> Steps:
    """The steps file at *path* for *plan*: one step per grant, in order; :class:`ConsentRefused` names the fault."""
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or set(data) != {'config', 'python', 'steps'}:
        msg = 'a steps file is a JSON object with exactly config, python and steps'
        raise ConsentRefused(msg)
    steps = data['steps']
    if not isinstance(steps, list) or len(steps) != len(plan.grants):
        listed = len(steps) if isinstance(steps, list) else 'no'
        msg = f'the steps file lists {listed} steps; the plan grants {len(plan.grants)}: one step per grant, in order'
        raise ConsentRefused(msg)
    for index, step in enumerate(steps):
        argv = step.get('argv') if isinstance(step, dict) else None
        if not (isinstance(argv, list) and argv and all(isinstance(word, str) for word in argv)) or (
            set(step) - {'argv', 'stdin'} or not isinstance(step.get('stdin', ''), str)
        ):
            msg = f'step {index + 1} is {{"argv": [ops verb words...], "stdin": "<host file>"?}}'
            raise ConsentRefused(msg)
        if '--credential' in argv or '--subject' in argv:
            msg = f'step {index + 1} names --credential or --subject itself: the runner adds them'
            raise ConsentRefused(msg)
    return Steps(
        str(data['config']), str(data['python']), tuple(tuple(step['argv']) for step in steps),
        tuple(step.get('stdin') for step in steps),
    )  # fmt: skip


def ops_command(steps: Steps, words: Sequence[str], *, sudo: str = 'sudo -n') -> str:
    """The shell line running ``dev_lab.ops`` *words* on the host under *sudo* (``sudo -n -l`` asks for the door)."""
    argv = [steps.python, '-m', 'dev_lab.ops', '--config', steps.config, *words]
    return f'{sudo} {shlex.join(argv)}'


def _with_stdin(command: str, stdin: str | None) -> str:
    return command if stdin is None else f'{command} < {shlex.quote(stdin)}'


def _last_line(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else ''


def preflight(plan: Plan, steps: Steps, remote: Remote) -> tuple[bool, list[str]]:
    """``(green, lines)``: every check of the module docstring, BEFORE a code; the lines name each blocker."""
    lines: list[str] = []
    blocked = False
    ready = ['consent', 'ready']
    said, status = remote.run(ops_command(steps, ready, sudo='sudo -n -l'))
    if status:
        lines.append(f'host: BLOCKED -- no sudo door for `{shlex.join(ready)}` ({_last_line(said)})')
        blocked = True
    else:
        said, status = remote.run(ops_command(steps, ready))
        lines.append(f'host: {"BLOCKED -- " if status else ""}{_last_line(said)}')
        blocked = blocked or bool(status)
    installers = [index for index, grant in enumerate(plan.grants) if grant['action'] == CONFIG_ACTION]
    for index, grant in enumerate(plan.grants):
        name = f'step {index + 1} {grant["action"]}'
        argv, stdin = steps.argv[index], steps.stdin[index]
        placeholder = f'{REMOTE_DIR}/preflight.json'
        said, status = remote.run(ops_command(steps, [*argv, '--credential', placeholder], sudo='sudo -n -l'))
        if status:
            earlier = [step for step in installers if step < index]
            if earlier:
                lines.append(f'{name}: after step {earlier[-1] + 1} (its door is installed by that config apply)')
                continue
            lines.append(f'{name}: BLOCKED -- no sudo door for `{shlex.join(argv)}` ({_last_line(said)})')
            blocked = True
            continue
        said, status = remote.run(_with_stdin(ops_command(steps, [*argv, '--subject']), stdin))
        derived = _last_line(said)
        if status:
            lines.append(f'{name}: BLOCKED -- the host could not derive the subject ({derived})')
            blocked = True
        elif derived != grant['subject']:
            lines.append(f'{name}: BLOCKED -- the host derives subject {derived[:12]}, the plan grants '
                         f'{grant["subject"][:12]}')  # fmt: skip
            blocked = True
        else:
            lines.append(f'{name}: green')
    lines.append('preflight: BLOCKED (fix the named blocker before asking for a code)' if blocked else
                 'preflight: green (ask the user for the code)')  # fmt: skip
    return not blocked, lines


def _plan(path: Path, dest: str) -> Plan:
    plan = parsed(json.loads(path.read_text(encoding='utf-8')))
    if plan.host != dest:
        msg = f'the plan is for {plan.host}, not {dest}'
        raise ConsentRefused(msg)
    return plan


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.planrun', description=__doc__.split('\n')[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    checking = verbs.add_parser('preflight', help='check every door of a plan on its host; spends no code')
    checking.add_argument('dest')
    checking.add_argument('--plan', type=Path, required=True)
    checking.add_argument('--steps', type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """The CLI; 0 green, 2 a named blocker or a refusal."""
    args = _parser().parse_args(argv)
    try:
        plan = _plan(args.plan, args.dest)
        steps = load_steps(args.steps, plan)
        green, lines = preflight(plan, steps, remote_for(args.dest))
    except (ConsentRefused, sshhold.HoldRefused, OSError, ValueError) as refused:
        emit(f'planrun: refused: {refused}', err=True)
        return 2
    emit('\n'.join(lines))
    return 0 if green else 2


if __name__ == '__main__':
    sys.exit(main())
