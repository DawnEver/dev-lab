"""``python -m dev_lab.dev.hpcaccount retention (--account <user>... | --fleet) [--apply]``.

AN ACCOUNT'S STORAGE, READ AND RECLAIMED FROM THE WORKSTATION. Every serve tick runs the account's retention
(:mod:`dev_lab.dev.retention`, in-flight aware), so a full quota means either the tick is not running or retention
keeps what it judges in use; neither is visible from here without a door. Per account this verb prints, through the
grant's own login hosts (never an agent's own ssh -- HPC-THROUGH-THE-DOOR):

* the account's quota (``quota -s``: blocks AND files -- files are the binding resource of a cluster home);
* whether its crontab carries the deploy's tick lines (``# lab-commons-deploy:``), i.e. whether serve ticks at all;
* the account's OWN ``python -m dev_lab.dev.retention --cluster`` report, run in its declared checkout -- a dry run,
  or the deletion itself with ``--apply`` -- so what is deleted is decided by the code that serves there.

A verification account needs this session's integrator role, exactly as every verb (HPC-ACCESS-BY-ROLE, through
:func:`~dev_lab.dev.hpcaccount.division.reached_machine`). An account whose login hosts do not answer is refused in
one line naming the door: the cluster is reached only from its site network (join it, or its VPN, and re-run).
Exit 2 when any account was refused.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from collections.abc import Callable, Sequence
from typing import Final

from lab_commons.hpc.cluster import Runner, Unreachable, runner_for
from lab_commons.hpc.grants import Grant
from lab_commons.log import emit

from dev_lab.dev.hpcaccount.division import reached_machine
from dev_lab.dev.hpcaccount.fleet import Target, declared_target, in_checkout
from dev_lab.dev.hpcaccount.spec import MARK

__all__ = ['QUOTA', 'UNREACHABLE', 'retention_command', 'retention_fleet', 'ticks_command']

#: The account's own quota report, blocks and files; a host without ``quota`` says so instead of failing.
QUOTA: Final = 'quota -s 2>&1 || echo "quota: not available on this host"'
#: The remedy of a cluster whose login hosts do not answer: it is reached only from its own network.
UNREACHABLE: Final = (
    'no login host answered -- the cluster is reached only from its site network: join it (or its VPN), then re-run'
)


def ticks_command() -> str:
    """The shell line that counts the deploy's tick lines in the account's crontab (0: serve does not tick)."""
    return f"crontab -l 2>/dev/null | grep -c -F '{MARK}' || true"


def retention_command(target: Target, *, apply: bool) -> str:
    """The shell line that runs the account's own retention over its ``~/ci``: a dry run unless *apply*."""
    return in_checkout(target, ['-m', 'dev_lab.dev.retention', '--cluster', *(['--apply'] if apply else [])])


def _one(grant: Grant, shell: Runner, *, apply: bool) -> tuple[bool, list[str]]:
    target = declared_target(grant, shell)
    if isinstance(target, str):
        return False, [target]
    ticks = shell(ticks_command(), None).strip().splitlines()
    count = ticks[-1] if ticks else '0'
    lines = [f'{grant.user}: quota', *shell(QUOTA, None).rstrip().splitlines()]
    lines.append(
        f'{grant.user}: serve tick lines in crontab: {count}' + ('' if count != '0' else ' -- serve never ticks')
    )
    lines.append(f'{grant.user}: retention {"--apply" if apply else "(dry run)"}')
    lines.extend(shell(retention_command(target, apply=apply), None).rstrip().splitlines())
    return True, lines


def retention_fleet(
    grants: Sequence[Grant],
    accounts: Sequence[str],
    *,
    apply: bool,
    say: Callable[[str], None],
    connect: Callable[[Grant], Runner] = runner_for,
) -> int:
    """Read (and with *apply* reclaim) each of *accounts*' storage (empty: every grant); 2 when any was refused."""
    fleet = {grant.user: grant for grant in grants}
    if unknown := sorted(set(accounts) - set(fleet)):
        say(f'retention: refused -- {unknown} not in the declared fleet {sorted(fleet)}')
        return 2
    if not fleet:
        say('retention: refused -- the machine file declares no [[hpc.grant]]')
        return 2
    refused = 0
    for user in accounts or sorted(fleet):
        try:
            ok, lines = _one(fleet[user], connect(fleet[user]), apply=apply)
        except Unreachable:
            ok, lines = False, [f'{user}: refused -- {UNREACHABLE}']
        except (RuntimeError, OSError, ValueError, IndexError, tomllib.TOMLDecodeError) as failed:
            ok, lines = False, [f'{user}: refused -- {failed}']
        for line in lines:
            say(line)
        refused += not ok
    return 2 if refused else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``retention`` and run it."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.hpcaccount retention', description=__doc__.splitlines()[0])
    who = parser.add_mutually_exclusive_group(required=True)
    who.add_argument('--account', action='append', default=[], help='one account of the fleet (repeatable)')
    who.add_argument('--fleet', action='store_true', help='every [[hpc.grant]] account this session reaches')
    parser.add_argument('--apply', action='store_true', help="run the account's retention for real; default: dry run")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        grants = reached_machine(args.account).grants
    except (PermissionError, LookupError, ValueError) as refused:
        emit(f'retention: refused -- {refused}')
        return 2
    return retention_fleet(grants, args.account, apply=args.apply, say=emit)
