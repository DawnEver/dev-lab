"""``python -m dev_lab.dev.hpcaccount retention (--account <user>... | --fleet) [--apply|--census]``.

AN ACCOUNT'S STORAGE, READ AND RECLAIMED FROM THE WORKSTATION. Every serve tick runs the account's retention
(:mod:`dev_lab.dev.retention`, in-flight aware), so a full quota means either the tick is not running or retention
keeps what it judges in use; neither is visible from here without a door. Per account this verb prints, through the
grant's own login hosts (never an agent's own ssh -- HPC-THROUGH-THE-DOOR):

* the account's quota (``quota -s``: blocks AND files -- files are the binding resource of a cluster home);
* whether its crontab carries the deploy's tick lines (``# lab-commons-deploy:``), i.e. whether serve ticks at all;
* with ``--census`` instead of a retention run, the FILES of every top-level entry of the home (dotdirs
  included: the uv cache, toolchains, ``~/ci``) and the :data:`CENSUS_DEEP` largest one level below, most files
  first -- ONE read-only walk (``du --inodes -x``). Files are what binds a cluster home, so bytes, a second walk
  of the same tree, are not taken. ``du`` counts a hard-linked file once: uv links envs from its cache, so an env
  costs few files of its own;
* otherwise the account's OWN ``python -m dev_lab.dev.retention --cluster`` report, run in its declared
  checkout -- a dry run, or the deletion itself with ``--apply`` -- so what is deleted is decided by the code
  that serves there.

A verification account needs this session's integrator role, exactly as every verb (HPC-ACCESS-BY-ROLE, through
:func:`~dev_lab.dev.hpcaccount.division.reached_machine`). An account whose login hosts do not answer is refused in
one line naming the door: the cluster is reached only from its site network (join it, or its VPN, and re-run).
Exit 2 when any account was refused.
"""

from __future__ import annotations

import argparse
import functools
import subprocess
import sys
import tomllib
from collections.abc import Callable, Sequence
from typing import Final

from lab_commons.hpc.cluster import Runner, Unreachable, runner_for, ssh_runner
from lab_commons.hpc.grants import Grant
from lab_commons.log import emit

from dev_lab.dev.hpcaccount.division import reached_machine
from dev_lab.dev.hpcaccount.fleet import Target, declared_target, in_checkout
from dev_lab.dev.hpcaccount.spec import MARK

__all__ = [
    'CENSUS_DEEP',
    'QUOTA',
    'UNREACHABLE',
    'census_rows',
    'retention_command',
    'retention_fleet',
    'ticks_command',
]

#: The account's own quota report, blocks and files; a host without ``quota`` says so instead of failing.
QUOTA: Final = 'quota -s 2>&1 || echo "quota: not available on this host"'
#: The remedy of a cluster whose login hosts do not answer: it is reached only from its own network.
UNREACHABLE: Final = (
    'no login host answered -- the cluster is reached only from its site network: join it (or its VPN), then re-run'
)

#: The level below the home's own entries.
_SECOND: Final = 2
#: How many second-level directories the census lists (every top-level entry is always listed).
CENSUS_DEEP: Final = 25
#: The census's ONE read-only walk of the home: file counts two levels deep, one filesystem.
CENSUS: Final = 'du --inodes -x -d 2 ~ 2>/dev/null || true'
#: A remote command's default ceiling: a walk of a home of millions of files on a parallel filesystem is slow.
TIMEOUT: Final = 3600.0

#: Connects to one named login host of a grant: ``(grant, host) -> runner``.
Pin = Callable[[Grant, str], Runner]


def _sizes(text: str) -> dict[str, int]:
    found: dict[str, int] = {}
    for line in text.splitlines():
        size, _, path = line.strip().partition(' ')
        if size.isdigit() and path.strip():
            found[path.strip()] = int(size)
    return found


def census_rows(files_text: str) -> list[str]:
    """``files  path`` per home entry (the home as ``~``), most files first.

    Every top-level entry is listed, and the :data:`CENSUS_DEEP` largest second-level ones.
    """
    files = _sizes(files_text)
    if not files:
        return ['census: du read nothing']
    home = min(files, key=len)

    def depth(path: str) -> int:
        return 0 if path == home else path[len(home) :].strip('/').count('/') + 1

    deep = sorted((p for p in files if depth(p) == _SECOND), key=lambda p: -files[p])[:CENSUS_DEEP]
    keep = sorted([p for p in files if depth(p) < _SECOND] + deep, key=lambda p: (-files[p], p))
    width = len(str(files[home]))
    return [f'{files[p]:>{width}}  ~{p[len(home) :]}' for p in keep]


def _too_slow(slow: subprocess.TimeoutExpired) -> str:
    return (
        f'a remote command ran past its timeout ({slow.timeout:.0f} s): the walk had not finished -- '
        're-run with a larger --timeout'
    )


def ticks_command() -> str:
    """The shell line that counts the deploy's tick lines in the account's crontab (0: serve does not tick)."""
    return f"crontab -l 2>/dev/null | grep -c -F '{MARK}' || true"


def retention_command(target: Target, *, apply: bool) -> str:
    """The shell line that runs the account's own retention over its ``~/ci``: a dry run unless *apply*."""
    return in_checkout(target, ['-m', 'dev_lab.dev.retention', '--cluster', *(['--apply'] if apply else [])])


def on_host(grant: Grant, host: str, timeout: float = TIMEOUT) -> Runner:
    """A runner pinned to *host*: what lives on one login host (its crontab) is read there, never on a failover."""
    return ssh_runner(f'{grant.user}@{host}', timeout)


def _one(grant: Grant, shell: Runner, pin: Pin, *, apply: bool, census: bool) -> tuple[bool, list[str]]:
    target = declared_target(grant, shell)
    if isinstance(target, str):
        return False, [target]
    # the deploy writes the crontab on its declared host; another login host's crontab says nothing about it
    ticks = pin(grant, target.host)(ticks_command(), None).strip().splitlines()
    count = ticks[-1] if ticks else '0'
    lines = [f'{grant.user}: quota', *shell(QUOTA, None).rstrip().splitlines()]
    lines.append(
        f'{grant.user}: serve tick lines in crontab on {target.host}: {count}'
        + ('' if count != '0' else ' -- serve never ticks')
    )
    if census:
        lines.append(f'{grant.user}: census (files, path; most files first)')
        lines.extend(census_rows(shell(CENSUS, None)))
        return True, lines
    lines.append(f'{grant.user}: retention {"--apply" if apply else "(dry run)"}')
    lines.extend(shell(retention_command(target, apply=apply), None).rstrip().splitlines())
    return True, lines


def retention_fleet(
    grants: Sequence[Grant],
    accounts: Sequence[str],
    *,
    apply: bool,
    say: Callable[[str], None],
    census: bool = False,
    connect: Callable[[Grant], Runner] = runner_for,
    pin: Pin = on_host,
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
            ok, lines = _one(fleet[user], connect(fleet[user]), pin, apply=apply, census=census)
        except subprocess.TimeoutExpired as slow:
            ok, lines = False, [f'{user}: refused -- {_too_slow(slow)}']
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
    what = parser.add_mutually_exclusive_group()
    what.add_argument('--apply', action='store_true', help="run the account's retention for real; default: dry run")
    what.add_argument('--census', action='store_true', help='files per home directory, read only, one walk')
    parser.add_argument('--timeout', type=float, default=TIMEOUT, help='seconds per remote command (default 3600)')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        grants = reached_machine(args.account).grants
    except (PermissionError, LookupError, ValueError) as refused:
        emit(f'retention: refused -- {refused}')
        return 2
    connect = functools.partial(runner_for, timeout=args.timeout)
    pin = functools.partial(on_host, timeout=args.timeout)
    return retention_fleet(
        grants, args.account, apply=args.apply, census=args.census, say=emit, connect=connect, pin=pin
    )
