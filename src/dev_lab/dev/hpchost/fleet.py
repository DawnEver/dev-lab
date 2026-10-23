"""``python -m dev_lab.dev.hpchost deploy-fleet [--account <user>]... [--dry-run]`` -- deploy every declared account.

THE FLEET IS THE MACHINE FILE'S ``[[hpc.grant]]`` TABLES (:func:`lab_commons.hpc.grants.load_grants`), the one
source the forge's submits read too; nothing here lists an account. For each account (or each ``--account``
named, which must be in the fleet -- anything else is refused before any ssh), it starts ONE detached
``ssh -o BatchMode=yes <user>@<first login host>`` that runs that account's own
``python -m dev_lab.dev.hpchost deploy`` in its kit checkout (``~/<root>/dev-lab``, ``--root``), and writes
everything it prints to one log per account (``~/.cache/dev-lab/<yy>/<mm>/<dd>/deploy-fleet/<user>.log``).
The deploy itself refuses off its declared host and is safe to repeat; this verb only starts it.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath
from typing import IO, Any, Final

import lab_commons.launch as _door
from lab_commons.hpc.grants import Grant, load_grants
from lab_commons.log import emit

from dev_lab.dev.datedlog import dated_log
from dev_lab.dev.hpchost.spec import DEFAULT_ROOT, KIT

__all__ = ['KIND', 'deploy_fleet', 'main', 'remote_argv']

#: The dated-log kind every account's log is written under.
KIND: Final = 'deploy-fleet'
_BASE: Final = '.cache/dev-lab'

#: Starts one detached process: ``(argv, log) -> None``.
Launch = Callable[[Sequence[str], IO[Any]], object]


def remote_argv(grant: Grant, *, root: str) -> list[str]:
    """The ssh argv that runs *grant*'s own deploy on its first login host, never prompting."""
    kit = PurePosixPath('~', root, KIT)
    command = f'cd {kit} && .venv/bin/python -m dev_lab.dev.hpchost deploy'
    return [
        'ssh',
        '-o',
        'BatchMode=yes',
        '-o',
        'ConnectTimeout=20',
        grant.targets[0],
        f'bash -lc {shlex.quote(command)}',
    ]


def _detached(argv: Sequence[str], log: IO[Any]) -> object:
    flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == 'nt' else 0
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
    root: str,
    home: Path,
    dry_run: bool,
    say: Callable[[str], None],
    launch: Launch = _detached,
) -> int:
    """Start each account's deploy; 2 (nothing started) when an account is not in the fleet or there is none."""
    fleet = {grant.user: grant for grant in reversed(grants)}  # the first grant of a user wins
    if unknown := sorted(set(accounts) - set(fleet)):
        say(f'deploy-fleet: refused -- {unknown} not in the declared fleet {sorted(fleet)}')
        return 2
    if not fleet:
        say('deploy-fleet: refused -- the machine file declares no [[hpc.grant]]')
        return 2
    for user in accounts or sorted(fleet):
        argv = remote_argv(fleet[user], root=root)
        path = dated_log(home, f'{user}.log', base=_BASE, kind=KIND)
        say(f'{user}: {"would start" if dry_run else "started"} {shlex.join(argv)}  log {path}')
        if not dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('a', encoding='utf-8') as log:
                launch(argv, log)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``deploy-fleet`` and start it."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.hpchost deploy-fleet', description=__doc__.splitlines()[0])
    parser.add_argument('--account', action='append', default=[], help='one account of the fleet (repeatable)')
    parser.add_argument('--root', default=DEFAULT_ROOT, help='the accounts keep their checkouts in ~/<root>')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    grants = load_grants().grants
    return deploy_fleet(grants, args.account, root=args.root, home=Path.home(), dry_run=args.dry_run, say=emit)
