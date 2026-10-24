"""``python -m dev_lab.dev.hpchost deploy-fleet [--account <user>]... [--dry-run]`` -- deploy every declared account.

THE FLEET IS THE MACHINE FILE'S ``[[hpc.grant]]`` TABLES (:func:`lab_commons.hpc.grants.load_grants`), the one
source the forge's submits read too; nothing here lists an account. Each ``--account`` named must be in the
fleet -- anything else is refused before any ssh.

WHERE AN ACCOUNT SERVES IS ITS OWN DECLARATION, never this machine's guess: its machine file's ``[deploy]``
``host`` and ``root`` (:mod:`dev_lab.dev.hpchost.spec`, the table its cron line was written from). Login hosts
share the home, so one read through any of the grant's hosts (:func:`lab_commons.hpc.cluster.runner_for`)
answers (:func:`declared_target`). An account with no ``[deploy]``, or whose host is not one of its grant's
login hosts, is refused by name and the others still deploy (exit 2).

Then it starts ONE detached ``ssh -o BatchMode=yes <user>@<declared host>`` that runs that account's own
``python -m dev_lab.dev.hpchost deploy`` in ``~/<root>/dev-lab`` and writes everything it prints to one log
per account (``~/.cache/dev-lab/<yy>/<mm>/<dd>/deploy-fleet/<user>.log``). The deploy is safe to repeat.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import IO, Any, Final

import lab_commons.launch as _door
from lab_commons.hpc.cluster import Runner, runner_for
from lab_commons.hpc.grants import Grant, load_grants
from lab_commons.log import emit

from dev_lab.dev.datedlog import dated_log
from dev_lab.dev.hpchost.spec import DEFAULT_ROOT, KIT
from dev_lab.dev.venvpath import venv_interpreter

__all__ = ['KIND', 'Target', 'declared_target', 'deploy_fleet', 'main', 'remote_argv']

#: The dated-log kind every account's log is written under.
KIND: Final = 'deploy-fleet'
_BASE: Final = '.cache/dev-lab'

#: The account's ``[deploy]`` table, read on its cluster: its machine file (``lab_commons.config``'s default).
_READ_DEPLOY: Final = "sed -n '/^\\[deploy\\]/,/^\\[/p' ~/.config/lab-commons/config.toml 2>/dev/null; true"

#: Starts one detached process: ``(argv, log) -> None``.
Launch = Callable[[Sequence[str], IO[Any]], object]


@dataclass(frozen=True)
class Target:
    """Where one account serves: its declared login host and checkout root."""

    host: str
    root: str


def declared_target(grant: Grant, shell: Runner) -> Target | str:
    """*grant*'s declared ``[deploy]`` host and root, read through *shell*; else why it cannot be deployed.

    The host may name a grant login host in full or by its first DNS label (``hpclogin01``).
    """
    lines = shell(_READ_DEPLOY, None).splitlines()
    table = '\n'.join(lines[:1] + [line for line in lines[1:] if not line.startswith('[')])
    deploy = tomllib.loads(table).get('deploy', {}) if table.strip() else {}
    host = deploy.get('host', '')
    if not host:
        return f'{grant.user}: refused -- its machine file declares no [deploy] host; run its first deploy by hand'
    if host not in grant.hosts and host not in {login.split('.', 1)[0] for login in grant.hosts}:
        return f'{grant.user}: refused -- its [deploy] host {host} is not a login host of its grant {list(grant.hosts)}'
    return Target(host, deploy.get('root', DEFAULT_ROOT))


def remote_argv(user: str, target: Target) -> list[str]:
    """The ssh argv that runs *user*'s own deploy on its DECLARED host, never prompting."""
    python = venv_interpreter(os_name='posix')  # every cluster login host is POSIX
    command = f'cd {PurePosixPath("~", target.root, KIT)} && {python} -m dev_lab.dev.hpchost deploy'
    return [
        'ssh',
        '-o',
        'BatchMode=yes',
        '-o',
        'ConnectTimeout=20',
        f'{user}@{target.host}',
        f'bash -lc {shlex.quote(command)}',
    ]


def _detached(argv: Sequence[str], log: IO[Any]) -> object:
    # The door adds CREATE_NO_WINDOW; DETACHED_PROCESS would leave the windowless console the serve child inherits.
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
    return _door.popen(
        list(argv),
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=flags,
        start_new_session=os.name != 'nt',
    )


def deploy_fleet(
    grants: Sequence[Grant],
    accounts: Sequence[str],
    *,
    home: Path,
    dry_run: bool,
    say: Callable[[str], None],
    connect: Callable[[Grant], Runner] = runner_for,
    launch: Launch = _detached,
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
        try:
            target = declared_target(grant, connect(grant))
        except (RuntimeError, OSError, tomllib.TOMLDecodeError) as failed:
            target = f'{user}: refused -- its [deploy] could not be read: {failed}'
        if isinstance(target, str):
            say(target)
            refused += 1
            continue
        argv = remote_argv(user, target)
        path = dated_log(home, f'{user}.log', base=_BASE, kind=KIND)
        say(f'{user}: {"would start" if dry_run else "started"} {shlex.join(argv)}  log {path}')
        if not dry_run:
            with path.open('a', encoding='utf-8') as log:
                launch(argv, log)
    return 2 if refused else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``deploy-fleet`` and start it."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.hpchost deploy-fleet', description=__doc__.splitlines()[0])
    parser.add_argument('--account', action='append', default=[], help='one account of the fleet (repeatable)')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    return deploy_fleet(load_grants().grants, args.account, home=Path.home(), dry_run=args.dry_run, say=emit)
