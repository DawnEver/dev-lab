"""A PLAN'S STEPS ON ITS HOSTS: check every door BEFORE the code is spent, then run the granted steps in order.

A code is never wasted (incidents 2026-11-11: a code spent, then the host refused -- no consent key, a sudo door
installed only by a later ``config apply``, an issuer it could not reach; and a hand-written wrapper deleted an
UNSPENT credential). Two verbs, one steps file; ``<dest>`` is the plan's host and every step's default::

    python -m dev_lab.dev.planrun preflight <dest> --plan <plan.json> --steps <steps.json>
    python -m dev_lab.dev.planrun run <dest> --plan <plan.json> --digest <D> --steps <steps.json>   # after the code

The STEPS FILE says what each grant of the plan runs, in the plan's order (one step per grant). A HOST step runs an
ops verb on ``dest`` (default ``<dest>``; ``config``/``python`` default the file's); a LOCAL step redeems its grant
here, through the client verb of :data:`LOCAL_VERBS` (a ``breakglass.wave`` opens a wave:
``python -m dev_lab.dev.forge breakglass open --credential <id>``)::

    {"config": "/etc/dev-lab/supervise.toml", "python": "/usr/bin/python3",
     "steps": [{"argv": ["config", "apply", "--from", "/srv/plan/candidate.toml"]},
               {"argv": ["config", "apply", "--from", "/srv/plan/judge.toml"], "dest": "ops@judge",
                "config": "/etc/dev-lab/judge.toml"},
               {"argv": ["secret", "place", "--path", "/etc/x"], "stdin": "/srv/plan/x.secret"},
               {"local": true}]}

each host step running ``sudo -n <python> -m dev_lab.ops --config <config> <argv...> --credential <file>`` on its
host (``stdin`` a file ON THAT HOST, so a secret never rides a command line or the hold's audit).

:func:`preflight` spends no code. Per host it asks ``consent ready`` (the verifier key resolves, a use can register);
per host step, that the ops verb is a sudo door (``sudo -n -l``) and that the subject the host derives (the verb's
``--subject``) equals the grant's; per local step, that the machine file names the client's endpoint. A door a host
gains only from an earlier ``ops.config`` step ON THAT HOST (``config apply`` installs sudoers) is ``after step N``,
never a failure. A remote is the held session when one is open, else key-only ssh (:mod:`.planremote`).

:func:`run_plan` runs the GRANTED plan's steps in order: it carries each host step's credential (found in
:func:`dev_lab.dev.consentguard.state_dir` by its action and subject) to its host under umask 077, runs the verb,
removes the host's copy; a local step hands the client the credential's id. Then it asks the issuer whether the use
was REGISTERED. A local credential is deleted only when the issuer says it was spent -- never on a bare exit status,
never when the issuer cannot be asked. It stops at the first refusal and keeps every unspent credential; a step done
is recorded per plan digest, so a second run resumes where the first stopped.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import lab_commons.launch as _door
from lab_commons.config import section
from lab_commons.log import emit

from dev_lab.dev import sshhold
from dev_lab.dev.consentguard import state_dir
from dev_lab.dev.planremote import Remote, remote_for
from dev_lab.ops.consent.client import spent_ids
from dev_lab.ops.consent.credential import SKEW_S, ConsentRefused
from dev_lab.ops.consent.plan import Plan, parsed
from dev_lab.ops.consent.plan import load as load_plan
from dev_lab.ops.totp import write_private

__all__ = [
    'CONFIG_ACTION',
    'LOCAL_VERBS',
    'REMOTE_DIR',
    'Step',
    'Steps',
    'load_steps',
    'main',
    'ops_command',
    'preflight',
    'run_local',
    'run_plan',
]

#: Which of these credential ids the issuer's ledger records a use of; raises when it cannot say.
type Spent = Callable[[list[str]], set[str]]
#: A host's remote, by its dest.
type Remotes = Callable[[str], Remote]
#: Runs a local client verb (``forge`` argv words); ``(merged output, exit status)``.
type Local = Callable[[Sequence[str]], tuple[str, int]]

#: The action whose step changes the host's config -- and so may install the sudo doors of the steps after it.
CONFIG_ACTION: Final = 'ops.config'
#: Where a carried credential lives on the host, relative to the session account's home (umask 077).
REMOTE_DIR: Final = '.dev-lab/consent'
#: A grant redeemed HERE rather than on a host: action -> (its ``forge`` client verb, the machine-file table naming
#: that client's endpoint). The step adds ``--credential <id>``.
LOCAL_VERBS: Final[Mapping[str, tuple[tuple[str, ...], str]]] = {
    'breakglass.wave': (('breakglass', 'open'), 'breakglass'),
}
_LOCAL_S: Final = 600.0


@dataclass(frozen=True)
class Step:
    """One grant's step: ops *argv* on *dest* (with that host's *config* and *python*), or a *local* client verb."""

    argv: tuple[str, ...]
    dest: str = ''
    config: str = ''
    python: str = ''
    stdin: str | None = None
    local: bool = False


@dataclass(frozen=True)
class Steps:
    """A steps file, every default resolved: one :class:`Step` per grant, in the plan's order."""

    steps: tuple[Step, ...]


_HOST_KEYS: Final = {'argv', 'stdin', 'dest', 'config', 'python'}


def _step(index: int, step: object, action: str, data: dict[str, Any], dest: str) -> Step:
    name = f'step {index + 1}'
    if isinstance(step, dict) and step.get('local') is True and set(step) == {'local'}:
        if action not in LOCAL_VERBS:
            msg = f'{name} is local, but {action} is redeemed on a host; local steps: {sorted(LOCAL_VERBS)}'
            raise ConsentRefused(msg)
        return Step(LOCAL_VERBS[action][0], local=True)
    argv = step.get('argv') if isinstance(step, dict) else None
    if not (isinstance(argv, list) and argv and all(isinstance(word, str) for word in argv)) or (
        set(step) - _HOST_KEYS or not all(isinstance(step.get(key, ''), str) for key in _HOST_KEYS - {'argv'})
    ):
        msg = (f'{name} is {{"argv": [ops verb words...], "stdin"?, "dest"?, "config"?, "python"?: "<str>"}} '
               'or {"local": true}')  # fmt: skip
        raise ConsentRefused(msg)
    if action in LOCAL_VERBS:
        msg = f'{name} grants {action}, which is redeemed here: {{"local": true}}'
        raise ConsentRefused(msg)
    if '--credential' in argv or '--subject' in argv:
        msg = f'{name} names --credential or --subject itself: the runner adds them'
        raise ConsentRefused(msg)
    return Step(
        tuple(argv), step.get('dest', dest), step.get('config', str(data['config'])),
        step.get('python', str(data['python'])), step.get('stdin'),
    )  # fmt: skip


def load_steps(path: Path, plan: Plan, dest: str) -> Steps:
    """The steps file at *path* for *plan*, *dest* the default host; :class:`ConsentRefused` names the fault."""
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or set(data) != {'config', 'python', 'steps'}:
        msg = 'a steps file is a JSON object with exactly config, python and steps'
        raise ConsentRefused(msg)
    steps = data['steps']
    if not isinstance(steps, list) or len(steps) != len(plan.grants):
        listed = len(steps) if isinstance(steps, list) else 'no'
        msg = f'the steps file lists {listed} steps; the plan grants {len(plan.grants)}: one step per grant, in order'
        raise ConsentRefused(msg)
    return Steps(tuple(_step(i, step, plan.grants[i]['action'], data, dest) for i, step in enumerate(steps)))


def ops_command(step: Step, words: Sequence[str], *, sudo: str = 'sudo -n') -> str:
    """The shell line running ``dev_lab.ops`` *words* on *step*'s host under *sudo* (``sudo -n -l`` asks the door)."""
    argv = [step.python, '-m', 'dev_lab.ops', '--config', step.config, *words]
    return f'{sudo} {shlex.join(argv)}'


def run_local(words: Sequence[str]) -> tuple[str, int]:
    """Run ``python -m dev_lab.dev.forge`` *words* here; ``(merged output, exit status)``."""
    argv = [sys.executable, '-m', 'dev_lab.dev.forge', *words]
    done = _door.run(argv, capture_output=True, text=True, encoding='utf-8', check=False, timeout=_LOCAL_S)
    return done.stdout + done.stderr, done.returncode


def _with_stdin(command: str, stdin: str | None) -> str:
    return command if stdin is None else f'{command} < {shlex.quote(stdin)}'


def _last_line(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else ''


def _ready(step: Step, remote: Remote) -> str | None:
    """``None`` when *step*'s host can verify and register a use, else the blocker."""
    ready = ['consent', 'ready']
    said, status = remote.run(ops_command(step, ready, sudo='sudo -n -l'))
    if status:
        return f'no sudo door for `{shlex.join(ready)}` ({_last_line(said)})'
    said, status = remote.run(ops_command(step, ready))
    return _last_line(said) if status else None


def _host_check(plan: Plan, steps: Steps, index: int, remote: Remote) -> tuple[str, bool]:
    """``(verdict, blocked)`` of host step *index*: its door, else an earlier config step on its host, then subject."""
    grant, step = plan.grants[index], steps.steps[index]
    placeholder = f'{REMOTE_DIR}/preflight.json'
    said, status = remote.run(ops_command(step, [*step.argv, '--credential', placeholder], sudo='sudo -n -l'))
    if status:
        here = [i for i in range(index) if not steps.steps[i].local and steps.steps[i].dest == step.dest]
        installers = [i for i in here if plan.grants[i]['action'] == CONFIG_ACTION]
        if installers:
            return f'after step {installers[-1] + 1} (its door is installed by that config apply)', False
        return f'BLOCKED -- no sudo door for `{shlex.join(step.argv)}` ({_last_line(said)})', True
    said, status = remote.run(_with_stdin(ops_command(step, [*step.argv, '--subject']), step.stdin))
    derived = _last_line(said)
    if status:
        return f'BLOCKED -- the host could not derive the subject ({derived})', True
    if derived != grant['subject']:
        return f'BLOCKED -- the host derives subject {derived[:12]}, the plan grants {grant["subject"][:12]}', True
    return 'green', False


def preflight(
    plan: Plan, steps: Steps, remotes: Remotes, *, machine: Callable[[str], Mapping[str, Any]] = section
) -> tuple[bool, list[str]]:
    """``(green, lines)``: every check of the module docstring, BEFORE a code; the lines name each blocker."""
    lines: list[str] = []
    blocked = False
    hosts = {step.dest: step for step in reversed(steps.steps) if not step.local}
    for dest in dict.fromkeys(step.dest for step in steps.steps if not step.local):  # each host once, in order
        fault = _ready(hosts[dest], remotes(dest))
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
        else:
            verdict, fault = _host_check(plan, steps, index, remotes(step.dest))
            verdict = f'{verdict} on {step.dest}'
        lines.append(f'{name}: {verdict}')
        blocked = blocked or fault
    lines.append('preflight: BLOCKED (fix the named blocker before asking for a code)' if blocked else
                 'preflight: green (ask the user for the code)')  # fmt: skip
    return not blocked, lines


def _local(plan: Plan, index: int, home: Path | None, now: float) -> Path | None:
    """The newest unexpired local credential for grant *index*: matched by its action and subject."""
    grant, found = plan.grants[index], []
    folder = state_dir(home)
    for path in sorted(folder.glob('*.json')) if folder.is_dir() else ():
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if (
            isinstance(data, dict)
            and (data.get('action'), data.get('subject')) == (grant['action'], grant['subject'])
            and isinstance(data.get('expires'), int | float)
            and now <= data['expires'] + SKEW_S
        ):
            found.append((data.get('issued', 0), path))
    return max(found)[1] if found else None


def _progress(plan: Plan, home: Path | None) -> Path:
    return state_dir(home) / 'runs' / f'{plan.digest}.json'


def _done(plan: Plan, home: Path | None) -> set[int]:
    path = _progress(plan, home)
    return set(json.loads(path.read_text(encoding='utf-8'))['done']) if path.is_file() else set()


def _redeem(step: Step, ident: str, text: str, remotes: Remotes, local: Local) -> tuple[str, int]:
    """Run *step* with its credential: the id to a local client, else a carried copy removed afterwards."""
    if step.local:
        return local([*step.argv, '--credential', ident])
    remote = remotes(step.dest)
    carried = f'{REMOTE_DIR}/{ident}.json'
    remote.put(carried, text)
    try:
        return remote.run(_with_stdin(ops_command(step, [*step.argv, '--credential', carried]), step.stdin))
    finally:
        remote.run(f'rm -f {shlex.quote(carried)}')


def run_plan(
    plan: Plan, steps: Steps, remotes: Remotes, *, spent: Spent, local: Local = run_local, home: Path | None = None,
    now: Callable[[], float] = time.time,
) -> tuple[bool, list[str]]:  # fmt: skip
    """``(finished, lines)``: the plan's steps run in order, each where it runs; see the module docstring."""
    lines: list[str] = []
    done = _done(plan, home)
    for index, grant in enumerate(plan.grants):
        step = steps.steps[index]
        name = f'step {index + 1} {grant["action"]} {"here" if step.local else "on " + step.dest}'
        if index in done:
            lines.append(f'{name}: done earlier')
            continue
        held = _local(plan, index, home, now())
        if held is None:
            lines.append(f'{name}: STOPPED -- no unexpired credential for it here; `python -m dev_lab.ops.consent '
                         'recover <plan.json> --digest <D>` fetches one the issuer granted and never registered, '
                         'else the plan needs a new code')  # fmt: skip
            return False, lines
        text = held.read_text(encoding='utf-8')
        ident = str(json.loads(text)['id'])
        said, status = _redeem(step, ident, text, remotes, local)
        try:
            used = ident in spent([ident])
        except (ConsentRefused, OSError) as unknown:
            lines.append(f'{name}: STOPPED -- exit {status}; the issuer could not say whether the credential was '
                         f'spent ({unknown}), so it is kept: {held}')  # fmt: skip
            return False, lines
        if used:
            held.unlink()
        kept = 'spent, deleted' if used else f'NOT spent, kept: {held}'
        if status:
            lines.append(f'{name}: STOPPED -- refused (exit {status}): {_last_line(said)}; credential {kept}')
            return False, lines
        done.add(index)
        write_private(_progress(plan, home), json.dumps({'done': sorted(done)}) + '\n')
        lines.append(f'{name}: ran ({_last_line(said)}); credential {kept}')
    return True, [*lines, 'plan: every step ran']


def _plan(path: Path, dest: str) -> Plan:
    plan = parsed(json.loads(path.read_text(encoding='utf-8')))
    if plan.host != dest:
        msg = f'the plan is for {plan.host}, not {dest}'
        raise ConsentRefused(msg)
    return plan


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.planrun', description=__doc__.split('\n')[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    checking = verbs.add_parser('preflight', help='check every door of a plan on its hosts; spends no code')
    running = verbs.add_parser('run', help="run a granted plan's steps in order; resumes where it stopped")
    for verb in (checking, running):
        verb.add_argument('dest', help="the plan's host, and every step's default")
        verb.add_argument('--plan', type=Path, required=True)
        verb.add_argument('--steps', type=Path, required=True)
    running.add_argument('--digest', required=True, help="the plan's digest, as shown to the user")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """The CLI; 0 green / every step ran, 2 a named blocker, a stop or a refusal."""
    args = _parser().parse_args(argv)
    try:
        plan = _plan(args.plan, args.dest)
        if args.verb == 'run':
            load_plan(args.plan, args.digest)  # the plan the user was shown, or none
        steps = load_steps(args.steps, plan, args.dest)
        if args.verb == 'run':
            green, lines = run_plan(plan, steps, remote_for, spent=spent_ids)
        else:
            green, lines = preflight(plan, steps, remote_for)
    except (ConsentRefused, sshhold.HoldRefused, OSError, ValueError) as refused:
        emit(f'planrun: refused: {refused}', err=True)
        return 2
    emit('\n'.join(lines))
    return 0 if green else 2


if __name__ == '__main__':
    sys.exit(main())
