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
``python -m dev_lab.dev.hpcaccount deploy`` in ``~/<root>/dev-lab`` and writes everything it prints to one log
per account (``~/.cache/dev-lab/<yy>/<mm>/<dd>/deploy-fleet/<user>.log``). The deploy is safe to repeat.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import IO, Any, Final

from lab_commons import home as _home
from lab_commons.config import CONFIG_ENV, section
from lab_commons.hpc.cluster import Runner, runner_for
from lab_commons.hpc.grants import Grant, load_grants
from lab_commons.log import emit

from dev_lab.dev.datedlog import dated_log
from dev_lab.dev.hpcaccount.division import Division, split_hpc
from dev_lab.dev.hpcaccount.spec import DEFAULT_ROOT, KIT
from dev_lab.dev.remote import detached, ssh_argv
from dev_lab.dev.venvpath import venv_interpreter

__all__ = ['KIND', 'Target', 'declared_target', 'deploy_fleet', 'main', 'remote_argv']

#: The dated-log kind every account's log is written under.
KIND: Final = 'deploy-fleet'
_BASE: Final = '.cache/dev-lab'


def _default_layout() -> tuple[str, str]:
    """The machine home under ``$HOME`` and the machine file under it, as lab-commons lays them out unset."""
    saved = {name: os.environ.pop(name) for name in (_home.HOME_ENV, CONFIG_ENV) if name in os.environ}
    try:
        machine_home = _home.home().relative_to(Path.home())
        under = _home.config_path().relative_to(_home.home())
    finally:
        os.environ.update(saved)
    return PurePosixPath(*machine_home.parts).as_posix(), PurePosixPath(*under.parts).as_posix()


_MACHINE_HOME, _CONFIG_UNDER_HOME = _default_layout()

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
    return Target(named[0], deploy.get('root', DEFAULT_ROOT), deploy.get('role', ''))


def remote_argv(user: str, target: Target, division: Division | None = None) -> list[str]:
    """The ssh argv that runs *user*'s own deploy on its DECLARED host, never prompting (:mod:`dev_lab.dev.remote`).

    With *division*, the deploy is passed the workstation's role for *user* and that role's table.
    """
    python = venv_interpreter(os_name='posix')  # every cluster login host is POSIX
    command = f'cd {PurePosixPath("~", target.root, KIT)} && {python} -m dev_lab.dev.hpcaccount deploy'
    if division is not None and (role := division.role_of(user)):
        table = json.dumps(dict(division.roles[role]), sort_keys=True)
        command += f' --fleet-role {shlex.quote(role)} --role-table {shlex.quote(table)}'
    return ssh_argv(f'{user}@{target.host}', command, batch=True)


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
    users = [grant.user for grant in grants]
    if twice := sorted({user for user in users if users.count(user) > 1}):
        say(f'deploy-fleet: refused -- {twice} hold more than one [[hpc.grant]]; one account, one deploy host')
        return 2
    fleet = {grant.user: grant for grant in grants}
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
        argv = remote_argv(user, target, division)
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
    table, division = split_hpc(section('hpc'))
    grants = load_grants(table).grants
    return deploy_fleet(grants, args.account, home=Path.home(), dry_run=args.dry_run, say=emit, division=division)
