"""``python -m dev_lab.dev.hpcaccount deploy-fleet [--account <user>]... [--dry-run]`` -- deploy every declared account.

THE FLEET IS THE MACHINE FILE'S ``[[hpc.grant]]`` TABLES (:func:`lab_commons.hpc.grants.load_grants`), the one
source the forge's submits read too; nothing here lists an account. Each ``--account`` named must be in the
fleet -- anything else is refused before any ssh.

WHERE AN ACCOUNT SERVES IS ITS OWN DECLARATION, never this machine's guess: its machine file's ``[deploy]``
``host`` and ``root`` (:mod:`dev_lab.dev.hpcaccount.spec`, the table its cron line was written from). Login hosts
share the home, so one read through any of the grant's hosts (:func:`lab_commons.hpc.cluster.runner_for`)
answers (:func:`declared_target`), with its ``role`` (:mod:`dev_lab.dev.hpcaccount.spec`: only a verification account
serves), printed per account. An account with no ``[deploy]``, or whose host is not one of its grant's
login hosts, is refused by name and the others still deploy (exit 2).

THE ROLE IS THE WORKSTATION'S (user rulings 2026-11-09): each grant's ``role`` and the ``[hpc.roles]`` table
(:mod:`dev_lab.dev.hpcaccount.division`) are passed to the account's deploy, which refuses when its own ``[deploy]
role`` differs, naming both. A grant role the table does not name is refused here, before any ssh.

Then it starts ONE detached ``ssh -o BatchMode=yes <user>@<declared host>`` that runs that account's own
``python -m dev_lab.dev.hpcaccount deploy`` in ``~/<root>/dev-lab`` -- after the kit's own tick has
refreshed that checkout (:func:`refresh_kit`), so a fix to the deploy reaches an account that never ticks --
and writes everything it prints to one log
per account (``~/.cache/dev-lab/<yy>/<mm>/<dd>/deploy-fleet/<user>.log``). The deploy is safe to repeat.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import IO, Any, Final

from lab_commons import home as _home
from lab_commons.config import CONFIG_ENV
from lab_commons.hpc.cluster import Runner, runner_for
from lab_commons.hpc.grants import Grant
from lab_commons.log import emit

from dev_lab.dev.datedlog import dated_log
from dev_lab.dev.hpcaccount.division import DEFAULT_ROLES, Division, division_of, reached_machine
from dev_lab.dev.hpcaccount.spec import DEFAULT_ROOT, KIT
from dev_lab.dev.machinehome import default_layout
from dev_lab.dev.remote import detached, ssh_argv
from dev_lab.dev.venvpath import venv_interpreter

__all__ = ['KIND', 'Target', 'declared_target', 'deploy_fleet', 'in_checkout', 'main', 'refresh_kit', 'remote_argv']

#: The dated-log kind every account's log is written under.
KIND: Final = 'deploy-fleet'
_BASE: Final = '.cache/dev-lab'


_MACHINE_HOME, _CONFIG_UNDER_HOME = default_layout()

#: The account's machine file as ITS python resolves it (:func:`lab_commons.config.config_path`): the override, else
#: the machine home's file. Prints ``# <path>`` first, so a refusal names the file it looked in.
_MACHINE_FILE: Final = f'"${{{CONFIG_ENV}:-${{{_home.HOME_ENV}:-$HOME/{_MACHINE_HOME}}}/{_CONFIG_UNDER_HOME}}}"'
_READ_DEPLOY: Final = f'f={_MACHINE_FILE}; echo "# $f"; ' + 'sed -n \'/^\\[deploy\\]/,/^\\[/p\' "$f" 2>/dev/null; true'

#: Starts one detached process: ``(argv, log) -> None``.
Launch = Callable[[Sequence[str], IO[Any]], object]


@dataclass(frozen=True)
class Target:
    """Where one account deploys: its declared login host, checkout root and role (``''``: undeclared)."""

    host: str
    root: str
    role: str = ''


def declared_target(grant: Grant, shell: Runner) -> Target | str:
    """*grant*'s declared ``[deploy]`` host and root, read through *shell*; else why it cannot be deployed.

    The host may name a grant login host in full or by its first DNS label (``login01``); a label resolves
    to the ONE full host it names, and a label two login hosts share is refused rather than the first kept.
    """
    out = shell(_READ_DEPLOY, None).splitlines()
    looked = next((line[2:] for line in out if line.startswith('# ')), 'its machine file')
    lines = [line for line in out if not line.startswith('#')]
    table = '\n'.join(lines[:1] + [line for line in lines[1:] if not line.startswith('[')])
    deploy = tomllib.loads(table).get('deploy', {}) if table.strip() else {}
    host = deploy.get('host', '')
    if not host:
        return f'{grant.user}: refused -- no [deploy] host in {looked}; deploy it once by hand'
    named = [login for login in grant.hosts if host in {login, login.split('.', 1)[0]}]
    if not named:
        return f'{grant.user}: refused -- its [deploy] host {host} is not a login host of its grant {list(grant.hosts)}'
    if len(named) > 1:
        return f'{grant.user}: refused -- its [deploy] host {host} is ambiguous: it names {named}; declare one in full'
    root = deploy.get('root', DEFAULT_ROOT)
    if grant.root and root != grant.root:
        return (
            f'{grant.user}: refused -- its [deploy] root {root} is not the root its cluster declares {grant.root} '
            '(the family declaration is the source: redeploy with --root naming it)'
        )
    return Target(named[0], root, deploy.get('role', ''))


def in_checkout(target: Target, argv: Sequence[str]) -> str:
    """The shell line that runs ``python <argv>`` in *target*'s declared dev-lab checkout, with its venv."""
    python = venv_interpreter(os_name='posix')  # every cluster login host is POSIX
    return f'cd {PurePosixPath("~", target.root, KIT)} && {python} {shlex.join(argv)}'


def grant_slice(grant: Grant) -> dict[str, Any]:
    """*grant* as the ``[hpc]`` slice its account's own machine file holds: its cluster, its grant, its role reached."""
    account: dict[str, Any] = {'billed': grant.billed}
    if grant.budget is not None:
        account['budget'] = {'core_hours': grant.budget.core_hours, 'since': grant.budget.since}
    cluster: dict[str, Any] = {'hosts': list(grant.hosts), 'slurm_accounts': {grant.slurm_account: account}}
    optional = {
        'partitions': list(grant.partitions), 'qos': dict(grant.qos), 'setup': list(grant.setup),
        'architecture': grant.architecture, 'root': grant.root,
    }  # fmt: skip
    cluster.update({key: value for key, value in optional.items() if value})
    row = {'user': grant.user, 'cluster': grant.cluster_name, 'slurm_account': grant.slurm_account, 'role': grant.role}
    row.update({key: value for key, value in (('owner', grant.owner), ('priority', grant.priority)) if value})
    return {'reach': [grant.role], 'clusters': {grant.cluster_name: cluster}, 'grant': [row]}


def remote_argv(grant: Grant, target: Target, division: Division | None = None) -> list[str]:
    """The ssh argv that runs *grant*'s own deploy on its DECLARED host, never prompting (:mod:`dev_lab.dev.remote`).

    The deploy is passed its declared ``[hpc]`` slice (:func:`grant_slice`); with *division*, also the role and its
    table.
    """
    deploy = ['-m', 'dev_lab.dev.hpcaccount', 'deploy', '--grant-table', json.dumps(grant_slice(grant), sort_keys=True)]
    if division is not None and (role := division.role_of(grant.user)):
        deploy += ['--fleet-role', role, '--role-table', json.dumps(dict(division.roles[role]), sort_keys=True)]
    command = f'{refresh_kit(grant, target)} ; {in_checkout(target, deploy)}'
    return ssh_argv(f'{grant.user}@{target.host}', command, batch=True)


def refresh_kit(grant: Grant, target: Target) -> str:
    """The shell line that brings *target*'s kit to its declared tip BEFORE the deploy runs, and records the sha.

    A dead account cannot heal itself: its kit moves only on its own cron tick, which never runs, so a fix to
    ``deploy`` would never reach it. The step is the kit's OWN tick (:mod:`dev_lab.dev.hpcaccount.tick`, the one
    writer of the host checkout), never a second refresh; in the grant's ``setup`` environment, as the cron line
    runs it (:func:`dev_lab.dev.hpcaccount.spec.tick_command`). The deploy follows whatever the tick exits: a
    research kit refreshes, then refuses to serve.
    """
    kit = PurePosixPath('~', target.root, KIT)
    recorded = f'echo "[deploy-fleet] kit at $(git -C {kit} rev-parse HEAD)"'
    tick = f'{in_checkout(target, ["-m", "dev_lab.dev.hpcaccount", "tick", KIT])} ; {recorded}'
    return f'bash -lc {shlex.quote("; ".join([*grant.setup, tick]))}' if grant.setup else tick


def _serving_twice(grants: Sequence[Grant], accounts: Sequence[str], division: Division | None) -> list[str]:
    """The accounts this run DEPLOYS that serve and hold more than one grant -- two grants there are two tick hosts.

    A research account's several grants are several allocations (no tick), and an account outside *accounts* is not
    deployed by this run, so neither is refused. A role no table names counts as serving: the guard stays on.
    """
    roles = division.roles if division is not None else DEFAULT_ROLES
    selected = set(accounts) or {grant.user for grant in grants}
    users = [grant.user for grant in grants if grant.user in selected]

    def serves(user: str) -> bool:
        return any(bool(roles.get(grant.role, {}).get('serves', True)) for grant in grants if grant.user == user)

    return sorted({user for user in users if users.count(user) > 1 and serves(user)})


def deploy_fleet(
    grants: Sequence[Grant],
    accounts: Sequence[str],
    *,
    home: Path,
    dry_run: bool,
    say: Callable[[str], None],
    connect: Callable[[Grant], Runner] = runner_for,
    launch: Launch = detached,
    division: Division | None = None,
) -> int:
    """Start each account's deploy on its declared host; 2 when any account was refused."""
    if twice := _serving_twice(grants, accounts, division):
        say(
            f'deploy-fleet: refused -- {twice} serve under more than one [[hpc.grant]]: a serving account ticks from '
            f'ONE login host. Keep one grant per serving account in the machine file, or deploy the others alone '
            f'(--account <user>)'
        )
        return 2
    fleet: dict[str, Grant] = {}
    for grant in grants:  # a non-serving account's further grants are allocations, not hosts: its first one deploys
        fleet.setdefault(grant.user, grant)
    if unknown := sorted(set(accounts) - set(fleet)):
        say(f'deploy-fleet: refused -- {unknown} not in the declared fleet {sorted(fleet)}')
        return 2
    if not fleet:
        say('deploy-fleet: refused -- the machine file declares no [[hpc.grant]]')
        return 2
    refused = 0
    for user in accounts or sorted(fleet):
        grant = fleet[user]
        if division is not None and (why := division.refusal(user)):
            say(f'{why}; refused')
            refused += 1
            continue
        try:
            target = declared_target(grant, connect(grant))
        except (RuntimeError, OSError, tomllib.TOMLDecodeError) as failed:
            target = f'{user}: refused -- its [deploy] could not be read: {failed}'
        if isinstance(target, str):
            say(target)
            refused += 1
            continue
        argv = remote_argv(grant, target, division)
        path = dated_log(home, f'{user}.log', base=_BASE, kind=KIND)
        role = (division.role_of(user) if division else '') or target.role or 'role undeclared'
        say(f'{user} ({role}): {"would start" if dry_run else "started"} {shlex.join(argv)}  log {path}')
        if not dry_run:
            with path.open('a', encoding='utf-8') as log:
                launch(argv, log)
    return 2 if refused else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``deploy-fleet`` and start it."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.hpcaccount deploy-fleet', description=__doc__.splitlines()[0])
    parser.add_argument('--account', action='append', default=[], help='one account of the fleet (repeatable)')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        machine = reached_machine(args.account)
    except (PermissionError, LookupError, ValueError) as refused:
        emit(f'deploy-fleet: refused -- {refused}')
        return 2
    return deploy_fleet(
        machine.grants, args.account, home=Path.home(), dry_run=args.dry_run, say=emit, division=division_of(machine)
    )
