"""``python -m dev_lab.dev.hpcaccount forget --repo <url> --row <key> [--account <user>... | --fleet] [--dry-run]``.

FORGETS ONE LEARNED ROW ON EACH CLUSTER ACCOUNT: lab-commons' ``python -m lab_commons.compute.learned forget``
(:func:`lab_commons.compute.learned.forget`, which backs the table up beside itself), run in the account's own
dev-lab checkout. A learned table lives in the account's home, so the verb must run there -- through the door's
connection, never an agent's own ssh (HPC-THROUGH-THE-DOOR).

The accounts are the machine file's ``[[hpc.grant]]`` tables, exactly as ``deploy-fleet`` reads them
(:mod:`~dev_lab.dev.hpcaccount.fleet`): an ``--account`` outside them refuses the whole run before any ssh, and
each command runs through :func:`lab_commons.hpc.cluster.runner_for` -- the grant's own login hosts, nothing else.
Its checkout is the account's declared ``[deploy]`` root (:func:`~dev_lab.dev.hpcaccount.fleet.declared_target`).

Per account it prints ``forgotten`` with the row and the backup path, ``absent`` (the row is not in its table; never
an error), or ``refused`` with the reason (unreachable, no ``[deploy]``, a remote failure) -- and the rest still run.
``--dry-run`` reads the row each account holds (its peak) and changes nothing. Exit 2 when any account was refused.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
import tomllib
from collections.abc import Callable, Sequence
from pathlib import PurePosixPath
from typing import Final

from lab_commons.config import section
from lab_commons.hpc.cluster import Runner, runner_for
from lab_commons.hpc.grants import Grant, load_grants
from lab_commons.log import emit

from dev_lab.dev.hpcaccount.division import split_hpc
from dev_lab.dev.hpcaccount.fleet import Target, declared_target
from dev_lab.dev.hpcaccount.spec import KIT
from dev_lab.dev.venvpath import venv_interpreter

__all__ = ['forget_command', 'forget_fleet', 'main', 'peek_command']

#: Prints the account's row as JSON (``null``: absent), read by lab-commons' own reader of the table.
_PEEK: Final = (
    'import json, sys; from lab_commons.compute.learned import learned; '
    "print(json.dumps(learned(sys.argv[1]).get('runs', {}).get(sys.argv[2])))"
)


def _in_checkout(target: Target, argv: Sequence[str]) -> str:
    python = venv_interpreter(os_name='posix')  # every cluster login host is POSIX
    return f'cd {PurePosixPath("~", target.root, KIT)} && {python} {shlex.join(argv)}'


def peek_command(target: Target, repo: str, row: str) -> str:
    """The shell line that prints *row* of *repo*'s learned table on the account, read-only."""
    return _in_checkout(target, ['-c', _PEEK, repo, row])


def forget_command(target: Target, repo: str, row: str) -> str:
    """The shell line that runs lab-commons' ``learned forget`` of *row* on the account."""
    return _in_checkout(target, ['-m', 'lab_commons.compute.learned', 'forget', '--repo', repo, '--row', row])


def _one(grant: Grant, shell: Runner, repo: str, row: str, *, dry_run: bool) -> tuple[bool, str]:
    target = declared_target(grant, shell)
    if isinstance(target, str):
        return False, target
    held = json.loads(shell(peek_command(target, repo, row), None).strip().splitlines()[-1])
    if held is None:
        return True, f'{grant.user}: absent -- {row!r} is no row of its table for {repo}'
    if dry_run:
        return True, f'{grant.user}: holds {row!r} peak {held.get("peak_mem_gb")} GB {json.dumps(held)}'
    done = shell(forget_command(target, repo, row), None).strip()
    return True, f'{grant.user}: forgotten -- {done}'


def forget_fleet(
    grants: Sequence[Grant],
    accounts: Sequence[str],
    *,
    repo: str,
    row: str,
    dry_run: bool,
    say: Callable[[str], None],
    connect: Callable[[Grant], Runner] = runner_for,
) -> int:
    """Forget *row* on each of *accounts* (empty: every grant); 2 when any account was refused."""
    fleet = {grant.user: grant for grant in grants}
    if unknown := sorted(set(accounts) - set(fleet)):
        say(f'forget: refused -- {unknown} not in the declared fleet {sorted(fleet)}')
        return 2
    if not fleet:
        say('forget: refused -- the machine file declares no [[hpc.grant]]')
        return 2
    refused = 0
    for user in accounts or sorted(fleet):
        try:
            ok, line = _one(fleet[user], connect(fleet[user]), repo, row, dry_run=dry_run)
        except (RuntimeError, OSError, ValueError, IndexError, tomllib.TOMLDecodeError) as failed:
            ok, line = False, f'{user}: refused -- {failed}'
        say(line)
        refused += not ok
    return 2 if refused else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``forget`` and run it."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.hpcaccount forget', description=__doc__.splitlines()[0])
    parser.add_argument('--repo', required=True, help='the repository remote URL the learned table is keyed by')
    parser.add_argument('--row', required=True, help='the runs key, <producer>|<needs> (e.g. "slurm|")')
    who = parser.add_mutually_exclusive_group(required=True)
    who.add_argument('--account', action='append', default=[], help='one account of the fleet (repeatable)')
    who.add_argument('--fleet', action='store_true', help='every [[hpc.grant]] account')
    parser.add_argument('--dry-run', action='store_true', help='print the row each account holds; change nothing')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    grants = load_grants(split_hpc(section('hpc'))[0]).grants
    return forget_fleet(grants, args.account, repo=args.repo, row=args.row, dry_run=args.dry_run, say=emit)
