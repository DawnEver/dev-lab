"""A PLAN'S STEPS ON ITS HOSTS: check every door BEFORE the code is spent, then run the granted steps in order.

A code is never wasted (incidents 2026-11-11: a code spent, then the host refused -- no consent key, a sudo door
installed only by a later ``config apply``, an issuer it could not reach; and a hand-written wrapper deleted an
UNSPENT credential). Two verbs, one steps file; each step runs on the host its GRANT names (the plan's, signed by
its digest -- topology.md 5.1)::

    python -m dev_lab.dev.planrun preflight --plan <plan.json> --steps <steps.json>
    python -m dev_lab.dev.planrun run --plan <plan.json> --digest <D> --steps <steps.json>   # after the code
    python -m dev_lab.dev.planrun subject --forge <host> --repo <owner/name> [--ref R]   # an ops.forge.protect grant
    python -m dev_lab.dev.planrun subject --config <host name> [--ref R]                # an ops.config grant

The STEPS FILE says what each grant of the plan runs, in the plan's order (one step per grant). A HOST step runs an
ops verb on its grant's ``host`` (``config``/``python`` default the file's); a LOCAL step redeems its grant
here, through the client verb of :data:`LOCAL_VERBS` (a ``breakglass.wave`` opens a wave:
``python -m dev_lab.dev.forge breakglass open --credential <id>``)::

    {"config": "/etc/dev-lab/supervise.toml", "python": "/usr/bin/python3",
     "steps": [{"argv": ["config", "apply", "--from", "/srv/plan/candidate.toml"]},
               {"argv": ["config", "apply", "--from", "/srv/plan/judge.toml"], "config": "/etc/dev-lab/judge.toml"},
               {"argv": ["secret", "place", "--path", "/etc/x"], "stdin_local": "secrets/x.secret"},
               {"local": true}]}

each host step running ``sudo -n <python> -m dev_lab.ops --config <config> <argv...> --credential <file>`` on its
host. ``stdin_local`` is a file HERE, on the operator's machine: its bytes are streamed through the session into the
verb's stdin (:meth:`.planremote.Remote.run`), so a secret is never staged on the host's disk -- where the agent's
login could read it (ruling 2026-11-04: after lockdown no one reads a bot token on a host) -- nor rides a command
line or the hold's audit (a sha256 prefix only). ``stdin_task`` (instead: exactly one of the two) is a task's key
bundle from THIS machine's forge-secrets store (:func:`.forgesecrets.stored_bundle`), streamed the same way -- no
file is written anywhere, and the bytes are never printed. ``stdout_local`` (a relative name, no ``..``) is the
mirror for a step whose OUTPUT is the secret (a ``forge token mint``): the output is written owner-only under THIS
machine's private state (:func:`stdout_path`, beside the credentials of :func:`.consentguard.state_dir`, never a
checkout), and the run shows only ``wrote <path> (sha256 <12 hex>, <n> bytes)``; on a failure it shows the exit
status and that the output was withheld, and writes nothing.

:func:`preflight` spends no code. Per host it asks ``consent ready`` WITHOUT sudo
(it reads only the config and the public key, so no sudoers row: the verifier key resolves, a use can register);
per host step, that its ``stdin_local`` file exists here or its ``stdin_task`` bundle is stored here (never its
content shown), that the ops verb is a sudo door (``sudo -n -l``) and that the subject the host derives (the verb's
``--subject``) equals the grant's; per local step, that the machine file names the client's endpoint. A door a host
gains only from an earlier ``ops.config`` step ON THAT HOST (``config apply`` installs sudoers) is ``after step N``,
never a failure; so is a subject that differs after such a step (the apply changes the live config the subject is
derived from), and :func:`run_plan` checks it for real at that point. An ``ops.forge.protect`` step naming its
public ``forge`` host (``{"argv": ["forge", "protect", "apply", "--repo", R, "--ref"?, F], "forge": "<host>"}``) has
its subject derived HERE (:func:`dev_lab.ops.forgeprotection.local_subject`: the repo's declaration read from that
forge at the ref, rendered as the host renders it), so building the plan needs no session; ``planrun subject``
prints it. So does an ``ops.config`` step naming its host's declaration (``{"argv": ["config", "apply"],
"config_host": "<name>"}``): :func:`dev_lab.ops.configdoor.local_subject` reads ``hosts/<name>.toml`` (and the family
file it declares) from the config source -- the ``origin`` of the clone the machine file's ``[devhost]`` names
(:func:`.devhost.config_source`) -- through the forge client, and digests exactly what the host's fetch reads. A host
that does not answer (no held session for a second-factor account) is UNREACHABLE: its derivable steps are checked
here and its doors at run (``run`` asks every host first); any other step on it is blocked. A host that answers is
still asked for the subject. A remote is the held session when one is open, else key-only ssh (:mod:`.planremote`).

:func:`run_plan` runs the GRANTED plan's steps in order: it carries each host step's credential (found in
:func:`dev_lab.dev.consentguard.state_dir` by its action and subject) to its host under umask 077, runs the verb,
removes the host's copy; a local step hands the client the credential's id. Then it asks the issuer whether the use
was REGISTERED. A local credential is deleted only when the issuer says it was spent -- never on a bare exit status,
never when the issuer cannot be asked. Before any step it asks every host a pending step runs on to
answer; one that does not (its session dropped mid-open, the host down) stops the run with NO step run on any host,
so no grant on another host is spent. It stops at the first refusal and keeps every unspent credential; a step done
is recorded per GRANT -- ``runs/<plan digest>-<issued ms>.json``, the grant being the newest live credentials' issue
time -- so a second run on the same grant resumes where the first stopped, and a fresh grant of the same plan (a
re-mint) starts a new run rather than reading the old one's steps as "done earlier" (user ruling 2026-11-13).
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from lab_commons.log import emit

from dev_lab.dev import sshholdwire, walls
from dev_lab.dev.consentguard import state_dir
from dev_lab.dev.planremote import remote_for
from dev_lab.dev.planrunpreflight import RULE, UNREAD, Readers, config_subject, preflight
from dev_lab.dev.planrunsteps import (
    CONFIG_ACTION,
    REMOTE_DIR,
    Local,
    Remotes,
    Step,
    Steps,
    load_steps,
    ops_command,
    run_local,
    shown_output,
    step_stdin,
)
from dev_lab.ops import forgeprotection
from dev_lab.ops.consent.client import spent_ids
from dev_lab.ops.consent.credential import SKEW_S, ConsentRefused
from dev_lab.ops.consent.plan import Plan, parsed
from dev_lab.ops.consent.plan import load as load_plan
from dev_lab.ops.totp import write_private

__all__ = ['main', 'run_plan']

#: Which of these credential ids the issuer's ledger records a use of; raises when it cannot say.
type Spent = Callable[[list[str]], set[str]]


def _local(plan: Plan, index: int, home: Path | None, now: float) -> Path | None:
    """The newest unexpired local credential for grant *index*: matched by its action, subject and signed plan digest.

    A credential issued from another plan is never this plan's, whatever grant it names: its ``plan`` is signed.
    """
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
            and data.get('plan') == plan.digest
            and isinstance(data.get('expires'), int | float)
            and now <= data['expires'] + SKEW_S
        ):
            found.append((data.get('issued', 0), path))
    return max(found)[1] if found else None


def _grant(plan: Plan, home: Path | None, now: float) -> float | None:
    """The grant this run redeems: the newest issue time among *plan*'s live local credentials; ``None``: none live."""
    held = [_local(plan, index, home, now) for index in range(len(plan.grants))]
    issued = [json.loads(path.read_text(encoding='utf-8')).get('issued', 0) for path in held if path is not None]
    return max(issued) if issued else None


def _progress(plan: Plan, grant: float, home: Path | None) -> Path:
    """The run record of ONE grant of *plan*: a re-mint is a new grant, hence a new record."""
    return state_dir(home) / 'runs' / f'{plan.digest}-{round(grant * 1000)}.json'


def _done(record: Path | None) -> set[int]:
    return set(json.loads(record.read_text(encoding='utf-8'))['done']) if record and record.is_file() else set()


def _newest_record(plan: Plan, home: Path | None) -> Path | None:
    """With no live credential, the newest run record of *plan*: what a resume reports as done."""
    found = sorted((state_dir(home) / 'runs').glob(f'{plan.digest}-*.json'), key=lambda path: path.stat().st_mtime)
    return found[-1] if found else None


def _redeem(step: Step, ident: str, text: str, remotes: Remotes, local: Local) -> tuple[str, int]:
    """Run *step* with its credential: the id to a local client, else a carried copy removed afterwards."""
    if step.local:
        return local([*step.argv, '--credential', ident])
    remote = remotes(step.dest)
    carried = f'{REMOTE_DIR}/{ident}.json'
    remote.put(carried, text)
    try:
        return remote.run(ops_command(step, [*step.argv, '--credential', carried]), step_stdin(step))
    finally:
        remote.run(f'rm -f {shlex.quote(carried)}')


def _unreachable(steps: Steps, done: set[int], remotes: Remotes) -> list[str]:
    """One line per host a pending host step runs on that does not answer ``true``; empty when every one does."""
    pending = dict.fromkeys(step.dest for i, step in enumerate(steps.steps) if not step.local and i not in done)
    down = []
    for dest in pending:
        try:
            _, status = remotes(dest).run('true')
        except (sshholdwire.HoldRefused, OSError) as gone:
            down.append(f'host {dest}: UNREACHABLE -- {gone}')
            continue
        if status:
            down.append(f'host {dest}: UNREACHABLE -- `true` exited {status}')
    return down


def run_plan(
    plan: Plan, steps: Steps, remotes: Remotes, *, spent: Spent, local: Local = run_local, home: Path | None = None,
    now: Callable[[], float] = time.time,
) -> tuple[bool, list[str]]:  # fmt: skip
    """``(finished, lines)``: the plan's steps run in order, each where it runs; see the module docstring."""
    lines: list[str] = []
    grant = _grant(plan, home, now())
    record = _newest_record(plan, home) if grant is None else _progress(plan, grant, home)
    done = _done(record)
    if down := _unreachable(steps, done, remotes):
        return False, [
            *down,
            (
                'plan: STOPPED before any step -- no credential spent on any host; re-open the named '
                'host(s) and run again (it resumes where it stopped)'
            ),
        ]
    for index, grant in enumerate(plan.grants):
        step = steps.steps[index]
        name = f'step {index + 1} {grant["action"]} {"here" if step.local else "on " + step.dest}'
        if index in done:
            lines.append(f'{name}: done earlier (run record {record}; a new grant of this plan starts a new run)')
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
            shown = shown_output(step, said, status, home)
            lines.append(f'{name}: STOPPED -- refused (exit {status}): {shown}; credential {kept}')
            return False, lines
        done.add(index)
        write_private(record, json.dumps({'done': sorted(done)}) + '\n')
        lines.append(f'{name}: ran ({shown_output(step, said, status, home)}); credential {kept}')
    return True, [*lines, 'plan: every step ran']


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.planrun', description=__doc__.split('\n')[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    checking = verbs.add_parser('preflight', help='check every door of a plan on its hosts; spends no code')
    running = verbs.add_parser('run', help="run a granted plan's steps in order; resumes where it stopped")
    for verb in (checking, running):
        verb.add_argument('--plan', type=Path, required=True)
        verb.add_argument('--steps', type=Path, required=True)
    running.add_argument('--digest', required=True, help="the plan's digest, as shown to the user")
    deriving = verbs.add_parser(
        'subject', help=f'print the {forgeprotection.ACTION} or {CONFIG_ACTION} subject, derived here'
    )
    which = deriving.add_mutually_exclusive_group(required=True)
    which.add_argument('--forge', help=f'{forgeprotection.ACTION}: the public forge host whose declaration row applies')
    which.add_argument('--config', help=f'{CONFIG_ACTION}: the host whose reviewed file is hosts/<name>.toml')
    deriving.add_argument('--repo', help=f'{forgeprotection.ACTION}: owner/name')
    deriving.add_argument('--ref', help=f'protect: default {forgeprotection.DEFAULT_REF}; config: default main')
    return parser


def _subject(args: argparse.Namespace, readers: Readers) -> str:
    if args.config:
        return config_subject(args.config, readers.text, readers.config_source(), args.ref or 'main')
    if not args.repo:
        msg = '--forge needs --repo owner/name'
        raise ConsentRefused(msg)
    read = lambda at: readers.declared(args.forge, args.repo, at)  # noqa: E731
    return forgeprotection.local_subject(args.repo, args.ref or forgeprotection.DEFAULT_REF, args.forge, read)


def main(argv: Sequence[str] | None = None, *, readers: Readers | None = None) -> int:
    """The CLI; 0 green / every step ran / a subject printed, 2 a named blocker, a stop or a refusal."""
    args = _parser().parse_args(argv)
    if args.verb == 'subject':
        try:
            emit(_subject(args, readers or Readers()))
        except UNREAD as refused:
            emit(f'planrun: refused: {refused}', err=True)
            return 2
        return 0
    try:
        plan = parsed(json.loads(args.plan.read_text(encoding='utf-8')))
        if args.verb == 'run':
            load_plan(args.plan, args.digest)  # the plan the user was shown, or none
        steps = load_steps(args.steps, plan)
        if args.verb == 'run':
            green, lines = run_plan(plan, steps, remote_for, spent=spent_ids)
        else:
            green, lines = preflight(plan, steps, remote_for)
            if not green:
                walls.refused_text(Path.cwd(), '\n'.join(lines), reason='preflight', rule=RULE)
    except (ConsentRefused, sshholdwire.HoldRefused, OSError, ValueError) as refused:
        emit(f'planrun: refused: {refused}', err=True)
        return 2
    emit('\n'.join(lines))
    return 0 if green else 2


if __name__ == '__main__':
    sys.exit(main())
