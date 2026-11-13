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
import hashlib
import json
import shlex
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Final

import lab_commons.launch as _door
from lab_commons.config import section
from lab_commons.log import emit

from dev_lab.dev import devhost, forgesecrets, sshhold
from dev_lab.dev.consentguard import state_dir
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.planremote import Remote, remote_for
from dev_lab.dev.reviewgate import DeclarationUnread, file_at, manifest_at
from dev_lab.ops import configdoor, forgeprotection
from dev_lab.ops.consent.client import spent_ids
from dev_lab.ops.consent.credential import SKEW_S, ConsentRefused
from dev_lab.ops.consent.plan import STALE_CLIENT, Plan, parsed, stale_client
from dev_lab.ops.consent.plan import load as load_plan
from dev_lab.ops.giteaadmin import ForgeRefused
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
#: ``(forge host, owner/name, ref)`` -> the repo's ``pyproject.toml`` text at the ref, read here.
type Declared = Callable[[str, str, str], str]
#: ``(source url, path, ref)`` -> that file's text at the ref, read here (:data:`.configdoor.SourceReader`).
type SourceReader = configdoor.SourceReader
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
    stdin_local: str | None = None
    stdin_task: str | None = None
    stdout_local: str | None = None
    local: bool = False
    forge: str = ''
    config_host: str = ''


@dataclass(frozen=True)
class Steps:
    """A steps file, every default resolved: one :class:`Step` per grant, in the plan's order."""

    steps: tuple[Step, ...]


_HOST_KEYS: Final = {'argv', 'stdin_local', 'stdin_task', 'stdout_local', 'config', 'python', 'forge', 'config_host'}
#: ssh's exit status when it could not reach the host at all (no session, no route, refused authentication).
_SSH_UNREACHED: Final = 255


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
        msg = (f'{name} is {{"argv": [ops verb words...], "stdin_local"? | "stdin_task"?, "config"?, '
               '"stdout_local"?, "python"?: "<str>"} or {"local": true}')  # fmt: skip
        raise ConsentRefused(msg)
    if {'stdin_local', 'stdin_task'} <= set(step):
        msg = f'{name} names both stdin_local and stdin_task: exactly one source feeds its stdin'
        raise ConsentRefused(msg)
    if 'stdout_local' in step and not _relative(step['stdout_local']):
        msg = f'{name} stdout_local is {step["stdout_local"]!r}: a relative name under the private state, no ..'
        raise ConsentRefused(msg)
    if action in LOCAL_VERBS:
        msg = f'{name} grants {action}, which is redeemed here: {{"local": true}}'
        raise ConsentRefused(msg)
    if 'forge' in step and action != forgeprotection.ACTION:
        msg = f'{name} names forge, which only an {forgeprotection.ACTION} step derives its subject from'
        raise ConsentRefused(msg)
    if 'config_host' in step and (action != CONFIG_ACTION or '--from' in argv):
        msg = (f'{name} names config_host, which only an {CONFIG_ACTION} step reading its reviewed source (no --from) '
               'derives its subject from')  # fmt: skip
        raise ConsentRefused(msg)
    if '--credential' in argv or '--subject' in argv:
        msg = f'{name} names --credential or --subject itself: the runner adds them'
        raise ConsentRefused(msg)
    return Step(
        tuple(argv), dest, step.get('config', str(data['config'])),
        step.get('python', str(data['python'])), step.get('stdin_local'), step.get('stdin_task'),
        step.get('stdout_local'), forge=step.get('forge', ''), config_host=step.get('config_host', ''),
    )  # fmt: skip


def _relative(name: str) -> bool:
    """*name* is a non-empty relative path on every platform, with no ``..`` part."""
    pure = PureWindowsPath(name)
    return bool(name) and not (pure.drive or pure.root or PurePosixPath(name).is_absolute()) and '..' not in pure.parts


def stdout_path(name: str, home: Path | None = None) -> Path:
    """Where a ``stdout_local`` *name* is kept: ``outputs/<name>`` under :func:`.consentguard.state_dir`."""
    return state_dir(home) / 'outputs' / name


def _shown(step: Step, said: str, status: int, home: Path | None) -> str:
    """What the run prints of *step*'s output: its last line, or -- for ``stdout_local`` -- where it was kept."""
    if step.stdout_local is None:
        return _last_line(said)
    if status:
        return 'output withheld (stdout_local)'
    path, data = stdout_path(step.stdout_local, home), said.encode('utf-8')
    write_private(path, said)
    return f'wrote {path} (sha256 {hashlib.sha256(data).hexdigest()[:12]}, {len(data)} bytes)'


def load_steps(path: Path, plan: Plan) -> Steps:
    """The steps file at *path* for *plan*, each step on its grant's host; :class:`ConsentRefused` names the fault."""
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or set(data) != {'config', 'python', 'steps'}:
        msg = 'a steps file is a JSON object with exactly config, python and steps'
        raise ConsentRefused(msg)
    steps = data['steps']
    if not isinstance(steps, list) or len(steps) != len(plan.grants):
        listed = len(steps) if isinstance(steps, list) else 'no'
        msg = f'the steps file lists {listed} steps; the plan grants {len(plan.grants)}: one step per grant, in order'
        raise ConsentRefused(msg)
    grants = plan.grants
    return Steps(tuple(_step(i, step, grants[i]['action'], data, grants[i]['host']) for i, step in enumerate(steps)))


def ops_command(step: Step, words: Sequence[str], *, sudo: str = 'sudo -n') -> str:
    """The shell line running ``dev_lab.ops`` *words* on *step*'s host under *sudo* (``sudo -n -l`` asks the door)."""
    argv = [step.python, '-m', 'dev_lab.ops', '--config', step.config, *words]
    return f'{sudo} {shlex.join(argv)}'


def run_local(words: Sequence[str]) -> tuple[str, int]:
    """Run ``python -m dev_lab.dev.forge`` *words* here; ``(merged output, exit status)``."""
    argv = [sys.executable, '-m', 'dev_lab.dev.forge', *words]
    done = _door.run(argv, capture_output=True, text=True, encoding='utf-8', check=False, timeout=_LOCAL_S)
    return done.stdout + done.stderr, done.returncode


def _stdin(step: Step) -> bytes | None:
    """The bytes of *step*'s ``stdin_local`` file or ``stdin_task`` bundle, read here; ``None`` when it has neither."""
    if step.stdin_task is not None:
        return forgesecrets.stored_bundle(step.stdin_task).encode('utf-8')
    return None if step.stdin_local is None else Path(step.stdin_local).read_bytes()


def _last_line(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else ''


def _ready(step: Step, remote: Remote) -> tuple[str | None, bool]:
    """``(blocker, reached)``: ``None`` when *step*'s host can verify and register a use; asked unprivileged.

    *reached* is false when the host did not answer at all (no held session, ssh could not connect).
    """
    try:
        said, status = remote.run(
            shlex.join([step.python, '-m', 'dev_lab.ops', '--config', step.config, 'consent', 'ready'])
        )
    except (sshhold.HoldRefused, OSError) as gone:
        return str(gone), False
    if status == _SSH_UNREACHED:
        return _last_line(said) or f'ssh exited {status}', False
    return ((_last_line(said) or f'consent ready exited {status}') if status else None), True


def _no_stdin(step: Step) -> str | None:
    """Why *step*'s stdin source is not here (its content never read into a message); ``None`` when it is."""
    if step.stdin_local is not None and not Path(step.stdin_local).is_file():
        return f'no stdin_local file here: {step.stdin_local}'
    if step.stdin_task is not None and not forgesecrets.stored_bundle(step.stdin_task):
        return f'no stored bundle for task {step.stdin_task} here: `forge secrets store --task {step.stdin_task}`'
    return None


def declared_at(forge: str, repo: str, ref: str) -> str:
    """*repo*'s ``pyproject.toml`` at *ref* on *forge*, read here through the forge client (never a working tree)."""
    from dev_lab.dev.forgework import client_for  # noqa: PLC0415 -- the forge client only a local subject needs

    return manifest_at(client_for(Path.cwd(), url=f'https://{forge}/{repo}.git'), ref)


def text_at(source: str, path: str, ref: str) -> str:
    """*path* at *ref* of the forge repo at *source* (an https clone URL), read here through the forge client."""
    from dev_lab.dev.forgework import client_for  # noqa: PLC0415 -- the forge client only a local subject needs

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
    read = lambda at: readers.declared(step.forge, repo, at)  # noqa: E731
    return forgeprotection.local_subject(repo, ref, step.forge, read), step.forge


#: What a local derivation may refuse with; each names what it could not read.
_UNREAD: Final = (ForgeRefused, DeclarationUnread, ForgeCallFailed, ConsentRefused, ValueError)


def _derived_here(granted: str, step: Step, readers: Readers) -> tuple[str, bool]:
    """``(verdict, blocked)`` of a step whose subject is derived HERE rather than asked of its host."""
    try:
        derived, where = _local_subject(step, readers)
    except _UNREAD as unread:
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
        return f'BLOCKED -- no sudo door for `{shlex.join(step.argv)}` ({_last_line(said)})', True
    if step.forge:
        return _derived_here(grant['subject'], step, readers)
    return _asked_of_host(grant['subject'], step, remote, after)


def _asked_of_host(granted: str, step: Step, remote: Remote, after: int | None) -> tuple[str, bool]:
    """``(verdict, blocked)`` of the subject *step*'s host derives (its verb's ``--subject``) against *granted*."""
    said, status = remote.run(ops_command(step, [*step.argv, '--subject']), _stdin(step))
    derived = _last_line(said)
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
        fault, reached = _ready(hosts[dest], remotes(dest))
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
        return remote.run(ops_command(step, [*step.argv, '--credential', carried]), _stdin(step))
    finally:
        remote.run(f'rm -f {shlex.quote(carried)}')


def _unreachable(steps: Steps, done: set[int], remotes: Remotes) -> list[str]:
    """One line per host a pending host step runs on that does not answer ``true``; empty when every one does."""
    pending = dict.fromkeys(step.dest for i, step in enumerate(steps.steps) if not step.local and i not in done)
    down = []
    for dest in pending:
        try:
            _, status = remotes(dest).run('true')
        except (sshhold.HoldRefused, OSError) as gone:
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
            lines.append(
                f'{name}: STOPPED -- refused (exit {status}): {_shown(step, said, status, home)}; credential {kept}'
            )
            return False, lines
        done.add(index)
        write_private(record, json.dumps({'done': sorted(done)}) + '\n')
        lines.append(f'{name}: ran ({_shown(step, said, status, home)}); credential {kept}')
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
        except _UNREAD as refused:
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
    except (ConsentRefused, sshhold.HoldRefused, OSError, ValueError) as refused:
        emit(f'planrun: refused: {refused}', err=True)
        return 2
    emit('\n'.join(lines))
    return 0 if green else 2


if __name__ == '__main__':
    sys.exit(main())
