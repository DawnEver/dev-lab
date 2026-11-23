"""``devhost enrol``: give THIS machine every forge credential it declares; the user's one code is the only input.

Two calls, one plan (user ruling 2026-11-20, "you must be able to do it yourself"):

1. ``devhost enrol --forge-config <forge host file>`` applies the declared store helper wherever git reads another
   (no consent: it is the machine's own declaration), then, for each declared login missing from the store, writes
   ONE consent plan whose grants are one ``ops.forge.token`` mint per login -- the token named after this machine --
   and its steps file (:mod:`dev_lab.dev.planrun`), and prints the digest to ask the user's code for. Nothing missing:
   nothing is written and it says so.
2. ``devhost enrol --forge-config F --plan <plan> --code <the user's code>`` opens the plan with that code
   (``sshhold open --plan``), runs its steps (``planrun run``), places each minted token through
   :func:`dev_lab.dev.devcredential.place` (verified by the forge answering as the login), DELETES the minted file
   whether the placement passed or not, and re-reads the drift.

Every fact is read, none restated: the logins from ``[dev] forges`` of the machine file, the mintable logins and
sites from the forge host file (:func:`.credstore.read_forge`), the remote python and config from that file's
``[ops.access]`` sudo line for ``forge *``, the ssh destination from its ``[ops.access] account`` at the host of the
family's ``[consent] endpoint`` (override with ``--dest``). The token's scope defaults to :data:`SCOPE` (what a
workstation agent needs to push and open pull requests); ``--scope`` keeps every other choice. ``--rotate`` mints
over a token the forge already holds under this machine's name (a store that lost it; a plain mint is refused).

The token is never printed, logged or hashed here: planrun keeps it owner-only under the consent state
(``outputs/<login>-<name>.token``), this door reads it once into :func:`~dev_lab.dev.devcredential.place` and
removes the file.
"""

from __future__ import annotations

import argparse
import json
import shlex
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev import devcredential, forgecredential
from dev_lab.dev.credstore import CredentialRefused, DeclaredForge, read_forge
from dev_lab.dev.planrunsteps import stdout_path
from dev_lab.dev.venvpath import running_interpreter
from dev_lab.ops.consent.plan import digest
from dev_lab.ops.forgerequests import TokenRequest

__all__ = [
    'SCOPE',
    'EnrolRefused',
    'Enrolment',
    'OpsDoor',
    'add_enrol',
    'complete',
    'load_enrolment',
    'missing',
    'ops_door',
    'prepare',
    'run',
]

#: What a workstation agent's token needs: push, open and comment on pull requests, read its own user.
SCOPE: Final = 'write:repository,write:issue,read:user'
#: The consent action of one minted token.
_ACTION: Final = 'ops.forge.token'
#: ``<python> -m dev_lab.ops --config <file> forge *``: the words of the forge host's ops sudo line.
_SUDO_WORDS: Final = 7


class EnrolRefused(ValueError):
    """A declaration this door needs is absent or contradicts another: what, never a token."""


@dataclass(frozen=True)
class OpsDoor:
    """How the forge host runs its ops verbs: ``<python> -m dev_lab.ops --config <config> forge ...`` as *account*."""

    account: str
    python: str
    config: str


@dataclass(frozen=True)
class Enrolment:
    """One machine's plan: where it was written, its digest, and the (login, token name) pairs it mints."""

    plan: Path
    steps: Path
    digest: str
    mints: tuple[tuple[str, str], ...]


def ops_door(forge_config: Path) -> OpsDoor:
    """The forge host's ``[ops.access]`` account and the python/config of its ``forge *`` sudo line.

    Raises:
        EnrolRefused: no ``[ops.access]`` account, or no command line ending ``dev_lab.ops --config C forge *``.

    """
    try:
        access = tomllib.loads(forge_config.read_text(encoding='utf-8')).get('ops', {}).get('access', {})
    except (OSError, tomllib.TOMLDecodeError) as failed:
        msg = f'the forge host file {forge_config} could not be read: {failed}'
        raise EnrolRefused(msg) from failed
    account = str(access.get('account') or '')
    for line in access.get('commands', []):
        words = shlex.split(str(line))
        if (
            account
            and len(words) == _SUDO_WORDS
            and words[1:4] == ['-m', 'dev_lab.ops', '--config']
            and words[5:] == ['forge', '*']
        ):
            return OpsDoor(account, words[0], words[4])
    msg = (f'{forge_config} declares no [ops.access] account with a "<python> -m dev_lab.ops --config <file> forge *" '
           'command: the forge host cannot mint for this machine')  # fmt: skip
    raise EnrolRefused(msg)


def missing(dev: Mapping[str, Any], forge: DeclaredForge, *, store: Path | None = None) -> list[str]:
    """The logins this machine declares for one of *forge*'s sites that the store holds no line for."""
    lines = forgecredential.store_lines(forgecredential.STORE if store is None else store)
    found: list[str] = []
    for host, logins in sorted(dev.get('forges', {}).items()):
        if host not in forge.sites:
            continue
        held = forgecredential.stored_logins(host, lines)
        found += [login for login in logins if login not in held and login not in found]
    return found


def _fix_helpers(
    dev: Mapping[str, Any],
    forge: DeclaredForge,
    helpers_for: Callable[[str], list[str]],
    store_for: Callable[[str], None],
    store: Path | None,
) -> list[str]:
    """Switch each declared host to the store once it holds every declared login -- never before (cut-off forge)."""
    said = []
    lines = forgecredential.store_lines(forgecredential.STORE if store is None else store)
    for host in sorted(dev.get('forges', {})):
        if (
            host in forge.sites
            and dev.get('helpers', {}).get(host) == 'store'
            and not forgecredential.unstored(dev, host, lines)
            and helpers_for(host) != (forgecredential.STORE_ONLY)
        ):
            store_for(host)
            said.append(f'{host}: git now reads only the store (declared [dev] helpers.{host} = "store")')
    return said


def prepare(
    *,
    dev: Mapping[str, Any],
    machine: str,
    forge: DeclaredForge,
    door: OpsDoor,
    dest_host: str,
    out: Path,
    scope: str = SCOPE,
    rotate: bool = False,
    store: Path | None = None,
    helpers_for: Callable[[str], list[str]] = forgecredential.helpers,
    store_for: Callable[[str], None] = forgecredential.use_store,
) -> tuple[list[str], Enrolment | None]:
    """Fix the declared helpers, then write the plan minting every missing login; ``(what it did, the plan)``.

    Raises:
        EnrolRefused: a missing login the forge host does not declare (it cannot be minted), or no machine name.

    """
    said = _fix_helpers(dev, forge, helpers_for, store_for, store)
    logins = missing(dev, forge, store=store)
    if not logins:
        return [*said, 'every declared forge login of this machine is stored: nothing to mint'], None
    if not machine:
        msg = 'the machine file names no [devhost] host: render it first (devhost render --host NAME --write)'
        raise EnrolRefused(msg)
    if undeclared := [login for login in logins if login not in forge.accounts]:
        msg = f'{undeclared} not in {forge.path} [ops.forge.accounts]: cannot be minted -- declare it there first'
        raise EnrolRefused(msg)
    dest = f'{door.account}@{dest_host}'
    rotating = ['--rotate'] if rotate else []
    mints = tuple((login, machine) for login in logins)
    plan = {
        'hosts': [dest],
        'grants': [
            {'host': dest, 'action': _ACTION, 'subject': TokenRequest(login, name, scope, rotate=rotate).subject()}
            for login, name in mints
        ],
    }
    steps = {
        'config': door.config,
        'python': door.python,
        'steps': [
            {'argv': ['forge', 'token', 'mint', '--login', login, '--name', name, '--scope', scope, *rotating]}
            for login, name in mints
        ],
    }
    out.mkdir(parents=True, exist_ok=True)
    plan_path, steps_path = out / f'enrol-{machine}.plan.json', out / f'enrol-{machine}.steps.json'
    plan_path.write_text(json.dumps(plan, indent=1) + '\n', encoding='utf-8')
    steps_path.write_text(json.dumps(steps, indent=1) + '\n', encoding='utf-8')
    return said, Enrolment(plan_path, steps_path, digest(plan), mints)


#: Runs one argv here; returns its exit status (output goes to the terminal; it never carries a token).
type Runner = Callable[[Sequence[str]], int]


def complete(
    enrolment: Enrolment,
    *,
    code: str,
    dev: Mapping[str, Any],
    forge: DeclaredForge,
    python: str,
    run: Runner,
    say: Callable[[str], None],
    home: Path | None = None,
    place: Callable[..., int] = devcredential.place,
) -> int:
    """Open the plan with *code*, mint, place each token, delete each minted file; 0 only when all were placed."""
    plan, steps, shown = str(enrolment.plan), str(enrolment.steps), enrolment.digest
    hold = [python, '-m', 'dev_lab.dev.sshhold', 'open', '--hours', '1', '--plan', plan, '--digest', shown]
    if run([*hold, '--code', code]):
        say('enrol: refused -- the plan did not open with that code (sshhold open); no token was minted')
        return 2
    status = run([python, '-m', 'dev_lab.dev.planrun', 'run', '--plan', plan, '--digest', shown, '--steps', steps])
    failed = 0
    for login, name in enrolment.mints:
        minted = stdout_path(f'{login}-{name}.token', home)
        if not minted.is_file():
            say(f'enrol: {login}: no minted token at {minted} (planrun exit {status}) -- nothing placed')
            failed += 1
            continue
        token = ''
        try:
            token = minted.read_text(encoding='utf-8').strip()
            failed += bool(place(login=login, token=token, url='', forge=forge, dev=dev, say=say))
        finally:
            minted.unlink(missing_ok=True)
            token = ''
    return 2 if failed or status else 0


def load_enrolment(plan: Path, steps: Path) -> Enrolment:
    """The enrolment a written plan and steps file describe (the mints read back from the steps)."""
    body = json.loads(plan.read_text(encoding='utf-8'))
    mints = []
    for step in json.loads(steps.read_text(encoding='utf-8')).get('steps', []):
        argv = step.get('argv', [])
        mints.append((argv[argv.index('--login') + 1], argv[argv.index('--name') + 1]))
    return Enrolment(plan, steps, digest(body), tuple(mints))


def add_enrol(verbs: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``enrol`` verb on *verbs* (the ``devhost`` subparsers)."""
    enrolling = verbs.add_parser('enrol', help='mint and place every forge login this machine declares and lacks')
    enrolling.add_argument('--forge-config', type=Path, default=None, help='the forge host file (default: found)')
    enrolling.add_argument('--scope', default=SCOPE, help=f'the token scope (default {SCOPE})')
    enrolling.add_argument(
        '--rotate', action='store_true',
        help="replace the token the forge already holds under this machine's name (the store lost it)",
    )  # fmt: skip
    enrolling.add_argument('--dest', default='', help='the forge host address (default: the [consent] endpoint host)')
    enrolling.add_argument('--plan', type=Path, default=None, help='the plan the first call wrote, to redeem')
    enrolling.add_argument('--code', default='', help='the one code the user gave for --plan')


def _forge_file(source: Path, given: Path | None, dev: Mapping[str, Any]) -> Path:
    """*given*, else the one host file under *source* whose ``[ops.caddy] sites`` serve a forge *dev* declares."""
    if given is not None:
        return given
    wanted = set(dev.get('forges', {}))
    found = []
    for path in sorted((source / 'hosts').glob('*.toml')):
        try:
            sites = tomllib.loads(path.read_text(encoding='utf-8')).get('ops', {}).get('caddy', {}).get('sites', [])
        except (OSError, tomllib.TOMLDecodeError):
            continue
        if wanted & set(sites):
            found.append(path)
    if len(found) != 1:
        msg = f'{len(found)} host files under {source} serve the forges {sorted(wanted)}: give --forge-config'
        raise EnrolRefused(msg)
    return found[0]


def _refuse(msg: str) -> None:
    raise EnrolRefused(msg)


def _enrol_run(args: argparse.Namespace, own: Mapping[str, Any], dev: Mapping[str, Any]) -> int:
    """The body of :func:`run`; every refusal raises."""
    if not dev:
        _refuse('the machine file is not a render (it records no host and source): devhost render --write')
    source = Path(own['source'])
    forge_file = _forge_file(source, args.forge_config, dev)
    forge = read_forge(forge_file)
    if args.plan is not None:
        if not args.code:
            _refuse('--plan needs --code: the one code the user gave for that plan')
        steps = args.plan.with_name(args.plan.name.replace('.plan.json', '.steps.json'))
        status = complete(
            load_enrolment(args.plan, steps), code=args.code, dev=dev, forge=forge,
            python=running_interpreter(), run=lambda argv: _door.run(list(argv), check=False).returncode, say=emit,
        )  # fmt: skip
        for line in forgecredential.drift(dev):
            emit(line)
        return status
    family = tomllib.loads((source / 'family.toml').read_text(encoding='utf-8'))
    dest = args.dest or str(family.get('consent', {}).get('endpoint') or '').rpartition('@')[2]
    if not dest:
        _refuse('the family declares no [consent] endpoint to reach the forge host by: give --dest HOST')
    said, enrolment = prepare(
        dev=dev, machine=str(own.get('host') or ''), forge=forge, door=ops_door(forge_file),
        dest_host=dest, out=Path('output/logs') / f'{datetime.now(UTC):%y/%m/%d}' / 'consent', scope=args.scope,
        rotate=args.rotate,
    )  # fmt: skip
    for line in said:
        emit(line)
    if enrolment is not None:
        python = running_interpreter()
        emit(f'enrol: plan {enrolment.plan} (digest {enrolment.digest}) mints {[m[0] for m in enrolment.mints]}; '
             f'show it with {python} -m dev_lab.ops.consent plan {enrolment.plan}, ask the user for the one code, '
             f'then: {python} -m dev_lab.dev.devhost enrol --plan {enrolment.plan} --code <the code>')  # fmt: skip
    return 0


def run(args: argparse.Namespace, own: Mapping[str, Any], dev: Mapping[str, Any]) -> int:
    """``devhost enrol``: fix the declared helper, write the mint plan (no ``--plan``), or redeem it with the code.

    *own* is the render's record of this machine (its ``host`` and ``source``); *dev* its effective ``[dev]``.
    """
    try:
        return _enrol_run(args, own, dev)
    except (EnrolRefused, CredentialRefused, OSError, ValueError, tomllib.TOMLDecodeError) as refused:
        emit(f'enrol: refused -- {refused}')
        return 2
