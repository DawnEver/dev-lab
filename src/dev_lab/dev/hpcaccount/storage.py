"""``python -m dev_lab.dev.hpcaccount retention (--account <user>... | --fleet) [--apply|--census]``.

AN ACCOUNT'S STORAGE, READ AND RECLAIMED FROM THE WORKSTATION. Every serve tick runs the account's retention
(:mod:`dev_lab.dev.retention`, in-flight aware), so a full quota means either the tick is not running or retention
keeps what it judges in use; neither is visible from here without a door. Per account this verb prints, through the
grant's own login hosts (never an agent's own ssh -- HPC-THROUGH-THE-DOOR):

* the account's quota (``quota -s``: blocks AND files -- files are the binding resource of a cluster home);
* whether its crontab carries the deploy's tick lines (``# lab-commons-deploy:``), i.e. whether serve ticks at all;
* with ``--census`` instead of a retention run, the FILES of every top-level entry of the home (dotdirs
  included: the uv cache, toolchains, the account root) and the :data:`CENSUS_DEEP` largest one level below, most files
  first -- ONE read-only walk (``du --inodes -x``). Files are what binds a cluster home, so bytes, a second walk
  of the same tree, are not taken. ``du`` counts a hard-linked file once: uv links envs from its cache, so an env
  costs few files of its own;
* otherwise, a dry run or the deletion itself with ``--apply``, in two parts. FIRST THE CALLER'S RULES, STREAMED
  (:func:`streamed_rules_command`, :mod:`dev_lab.dev.accountsweep`): old copies, environments no pointer names, uv's
  interrupted-install leftovers -- this workstation's version, run by the account's interpreter from stdin, nothing
  written there, so an account too full to update its kit is still reclaimed. THEN the account's OWN ``python -m
  dev_lab.dev.retention --cluster`` in its declared checkout: the in-flight-aware rules (runs, trees, builds, logs)
  need the forge's run state and the kit, so they are decided by the code that serves there.

A verification account needs this session's integrator role, exactly as every verb (HPC-ACCESS-BY-ROLE, through
:func:`~dev_lab.dev.hpcaccount.division.reached_machine`). An account whose login hosts do not answer is refused in
one line naming the door: the cluster is reached only from its site network (join it, or its VPN, and re-run).
Exit 2 when any account was refused.
"""

from __future__ import annotations

import argparse
import functools
import json
import shlex
import subprocess
import sys
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

from lab_commons.hpc.cluster import Runner, Unreachable
from lab_commons.hpc.grants import Grant
from lab_commons.hpc.layout import ROOT_VAR
from lab_commons.log import emit

from dev_lab.dev import accountsweep, quotawatch
from dev_lab.dev.diskusage import MMLSQUOTA, parse_mmlsquota, parse_quota
from dev_lab.dev.hpcaccount.division import division_of, reached_machine
from dev_lab.dev.hpcaccount.fleet import Target, declared_target, in_checkout, repo_dir
from dev_lab.dev.hpcaccount.spec import KIT, MARK
from dev_lab.dev.hpcaccount.transport import grant_runner, host_runner
from dev_lab.dev.oldcopies import STRAYS_IN_HOME, STRAYS_IN_ROOT
from dev_lab.dev.retentionrust import RULE_REGISTRY
from dev_lab.dev.venvpointer import HOME as ENVS_HOME
from dev_lab.dev.venvpointer import POINTER, RETIRED_POINTER, shell_interpreter

__all__ = [
    'CENSUS_DEEP',
    'QUOTA',
    'SWEEP_SOURCE',
    'UNREACHABLE',
    'census_rows',
    'retention_command',
    'retention_fleet',
    'streamed_rules_command',
    'sweep_spec',
    'ticks_command',
]

#: The account's own quota report, blocks and files; a host without ``quota`` says so instead of failing.
#: ``mmlsquota`` is tried where the account's retention reads it (:data:`~dev_lab.dev.diskusage.MMLSQUOTA`: a
#: non-interactive shell's PATH does not name GPFS's bin). A tool that answers with a non-zero exit is still an
#: answer -- ``quota`` exits 1 exactly when the account is OVER quota, the case this verb exists for (measured
#: 2026-11-22: "none ... answered" beside a retention summary reading 2019980/2000000 files) -- kept and printed
#: with its exit when no tool answers cleanly.
QUOTA: Final = (
    '( kept=""; for tool in '
    + ' '.join(f'"{tool} --block-size auto"' for tool in MMLSQUOTA)
    + ' "quota -s" "lfs quota -h $HOME"; do '
    'command -v "${tool%% *}" >/dev/null 2>&1 || continue; '
    'out=$($tool 2>&1); rc=$?; [ -n "$out" ] || continue; '
    '[ "$rc" -eq 0 ] && { echo "quota by ${tool%% *}:"; echo "$out"; exit 0; }; '
    '[ -n "$kept" ] || { kept="quota by ${tool%% *} (exit $rc: over quota, or the tool failed):"; held="$out"; }; '
    'done; [ -n "$kept" ] && { echo "$kept"; echo "$held"; exit 0; }; '
    'echo "quota: none of mmlsquota, quota, lfs answered on this host" )'
)
#: The quota in KB, for :func:`usage_of`: ``mmlsquota`` (each of :data:`MMLSQUOTA`), else ``quota -w``; an over-quota
#: exit is still the answer, so no exit status is read.
USAGE: Final = (
    '( for tool in ' + ' '.join(MMLSQUOTA) + '; do command -v "$tool" >/dev/null 2>&1 && '
    '{ "$tool" 2>/dev/null; exit 0; }; done; quota -w 2>/dev/null; true )'
)
#: The remedy of a cluster whose login hosts do not answer: it is reached only from its own network.
UNREACHABLE: Final = (
    'no login host answered -- the cluster is reached only from its site network: join it (or its VPN), then re-run'
)

#: The level below the home's own entries.
_SECOND: Final = 2
#: How many second-level directories the census lists (every top-level entry is always listed).
CENSUS_DEEP: Final = 25
#: The census's ONE read-only walk of the home, file counts two levels deep on one filesystem: ``du --inodes``,
#: or -- where the cluster's ``du`` lacks it -- one ``find -xdev`` aggregated by its first two path components.
#: A ``# `` line is a note (why the fallback ran, or why the walk read nothing), printed as the census's cause.
CENSUS: Final = (
    'out=$(du --inodes -x -d 2 "$HOME" 2>/dev/null); rc=$?; '
    'if [ -n "$out" ]; then echo "$out"; '
    '[ "$rc" -eq 0 ] || echo "# du rc=$rc: some directories were unreadable, so their counts are partial"; '
    'else err=$(du --inodes -x -d 0 "$HOME" 2>&1 >/dev/null | head -n 1); '
    'echo "# du --inodes unavailable (rc=$rc): $err"; '
    'find "$HOME" -xdev 2>/dev/null | awk -v h="$HOME" '
    '\'{ n[h]++; r = substr($0, length(h) + 2); if (r == "") next; k = split(r, a, "/"); '
    'n[h "/" a[1]]++; if (k > 1) n[h "/" a[1] "/" a[2]]++ } END { for (p in n) print n[p], p }\'; '
    'echo "# find rc=$?"; fi'
)
#: A remote command's default ceiling: a walk of a home of millions of files on a parallel filesystem is slow.
TIMEOUT: Final = 3600.0

#: Connects to one named login host of a grant: ``(grant, host) -> runner``.
Pin = Callable[[Grant, str], Runner]


def _sizes(text: str) -> tuple[dict[str, int], list[str]]:
    found: dict[str, int] = {}
    notes: list[str] = []
    for line in text.splitlines():
        if line.startswith('# '):
            notes.append(line[2:].strip())
            continue
        size, _, path = line.strip().partition('	') if '	' in line else line.strip().partition(' ')
        if size.isdigit() and path.strip():
            found[path.strip()] = int(size)
    return found, notes


def census_rows(files_text: str) -> list[str]:
    """``files  path`` per home entry (the home as ``~``), most files first.

    Every top-level entry is listed, and the :data:`CENSUS_DEEP` largest second-level ones.
    """
    files, notes = _sizes(files_text)
    if not files:
        return [f'census: the walk read nothing -- {"; ".join(notes) or "no output and no note"}']
    head = [f'census: {note}' for note in notes if not note.startswith('find rc=0')]
    home = min(files, key=len)

    def depth(path: str) -> int:
        return 0 if path == home else path[len(home) :].strip('/').count('/') + 1

    deep = sorted((p for p in files if depth(p) == _SECOND), key=lambda p: -files[p])[:CENSUS_DEEP]
    keep = sorted([p for p in files if depth(p) < _SECOND] + deep, key=lambda p: (-files[p], p))
    width = len(str(files[home]))
    return [*head, *(f'{files[p]:>{width}}  ~{p[len(home) :]}' for p in keep)]


def _too_slow(slow: subprocess.TimeoutExpired) -> str:
    return (
        f'a remote command ran past its timeout ({slow.timeout:.0f} s): the walk had not finished -- '
        're-run with a larger --timeout'
    )


def usage_of(user: str, text: str) -> list[str]:
    """*user*'s ONE usage-vs-quota line (files and bytes with headroom) and its named warning, from :data:`USAGE`."""
    usage = parse_mmlsquota(text) or parse_quota(text)
    return quotawatch.lines(usage, quotawatch.declared_lines(), who=user)


def ticks_command() -> str:
    """The shell line that counts the deploy's tick lines in the account's crontab (0: serve does not tick)."""
    return f"crontab -l 2>/dev/null | grep -c -F '{MARK}' || true"


def retention_command(target: Target, *, apply: bool) -> str:
    """The shell line that runs the account's own retention over its declared root: a dry run unless *apply*.

    THE ROOT IS PASSED, never left to the login file (as the cron line passes it): a deploy that could not finish
    wrote no ``export LAB_ROOT``, and an account whose quota is full cannot finish a deploy -- so the one verb that
    frees space would need the deploy that needs space (measured 2026-11-22, a deadlock).
    """
    retention = in_checkout(target, ['-m', 'dev_lab.dev.retention', '--cluster', *(['--apply'] if apply else [])])
    return f'export {ROOT_VAR}={shlex.quote(target.root)} && {retention}'


#: The oldest interpreter the streamed rules run on (``from __future__ import annotations``, ``:=``).
_SWEEP_PYTHON: Final = (3, 8)


def sweep_spec(target: Target, *, apply: bool) -> dict[str, object]:
    """What the streamed rules judge on *target*'s account: its root and the declared names, each from its source."""
    return {
        'root': target.root, 'apply': apply,
        'strays_in_home': list(STRAYS_IN_HOME), 'strays_in_root': list(STRAYS_IN_ROOT),
        'retired_pointer': RETIRED_POINTER, 'pointer': POINTER, 'envs': ENVS_HOME,
        'cargo_rule': RULE_REGISTRY, 'cargo_hours': quotawatch.declared_lines().min_age / 3600,
    }  # fmt: skip


def streamed_rules_command(target: Target, *, apply: bool) -> str:
    """The shell line that runs THE CALLER'S rules on the account, their source on stdin (:data:`SWEEP_SOURCE`).

    The interpreter is the account's own: its kit's current environment where that runs, else ``python3`` -- an
    account whose kit cannot be updated, or is half-built, is exactly the one this must reach. Nothing is written
    there (:mod:`dev_lab.dev.accountsweep`). An interpreter older than the rules need is refused by name.
    """
    old = f'sys.exit(sys.version_info < {_SWEEP_PYTHON})'
    major, minor = _SWEEP_PYTHON
    return (
        f'export {ROOT_VAR}={shlex.quote(target.root)}; cd {repo_dir(target, KIT)} 2>/dev/null; '
        f'py={shell_interpreter(".")}; "$py" -c "import sys; {old}" 2>/dev/null || py=python3; '
        f'"$py" -c "import sys; {old}" || {{ echo "retention: refused -- neither the kit environment nor python3 is '
        f'a python >= {major}.{minor} on this account: the streamed rules cannot run"; exit 2; }}; '
        f'"$py" - {shlex.quote(json.dumps(sweep_spec(target, apply=apply)))}'
    )


#: The source the streamed rules are: this workstation's own :mod:`dev_lab.dev.accountsweep`, whole.
SWEEP_SOURCE: Final = Path(accountsweep.__file__).read_text(encoding='utf-8')


def on_host(grant: Grant, host: str, timeout: float = TIMEOUT) -> Runner:
    """A runner pinned to *host*: what lives on one login host (its crontab) is read there, never on a failover."""
    return host_runner(f'{grant.user}@{host}', timeout)


def tick_line(user: str, host: str, count: str, *, serves: bool) -> str:
    """The crontab line judged by ROLE: a serving account ticks; a research one never carries a cron."""
    head = f'{user}: serve tick lines in crontab on {host}: {count}'
    if serves:
        return head + (' -- serve never ticks' if count == '0' else '')
    if count == '0':
        return head + ' -- a non-serving (research) account: no serve cron, by design'
    return head + ' -- a non-serving (research) account must carry none: remove them (hpcaccount deploy --remove)'


def _one(grant: Grant, shell: Runner, pin: Pin, *, apply: bool, census: bool, serves: bool) -> tuple[bool, list[str]]:
    target = declared_target(grant, shell)
    if isinstance(target, str):
        return False, [target]
    # the deploy writes the crontab on its declared host; another login host's crontab says nothing about it
    ticks = pin(grant, target.host)(ticks_command(), None).strip().splitlines()
    count = ticks[-1] if ticks else '0'
    lines = [
        f'{grant.user}: quota',
        *shell(QUOTA, None).rstrip().splitlines(),
        *usage_of(grant.user, shell(USAGE, None)),
    ]
    lines.append(tick_line(grant.user, target.host, count, serves=serves))
    if census:
        lines.append(f'{grant.user}: census (files, path; most files first)')
        lines.extend(census_rows(shell(CENSUS, None)))
        return True, lines
    mode = '--apply' if apply else '(dry run)'
    # the caller's rules first, streamed: they need nothing of the account's kit, which may be the thing that is full
    lines.append(f"{grant.user}: retention {mode}, the caller's rules (streamed; nothing is written on the account)")
    lines.extend(shell(streamed_rules_command(target, apply=apply), SWEEP_SOURCE).rstrip().splitlines())
    lines.append(f"{grant.user}: retention {mode}, the account kit's own rules")
    try:
        lines.extend(shell(retention_command(target, apply=apply), None).rstrip().splitlines())
    except RuntimeError as broken:  # a kit that cannot run is named; the caller's rules above already ran
        return False, [*lines, f"{grant.user}: refused -- the kit's own retention did not run: {broken}"]
    return True, lines


def retention_fleet(
    grants: Sequence[Grant],
    accounts: Sequence[str],
    *,
    apply: bool,
    say: Callable[[str], None],
    census: bool = False,
    connect: Callable[[Grant], Runner] = grant_runner,
    pin: Pin = on_host,
    serves: Callable[[Grant], bool] = lambda _grant: True,
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
            ok, lines = _one(
                fleet[user], connect(fleet[user]), pin, apply=apply, census=census, serves=serves(fleet[user])
            )
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
        machine = reached_machine(args.account)
        grants, division = machine.grants, division_of(machine)
    except (PermissionError, LookupError, ValueError) as refused:
        emit(f'retention: refused -- {refused}')
        return 2
    connect = functools.partial(grant_runner, timeout=args.timeout)
    pin = functools.partial(on_host, timeout=args.timeout)
    return retention_fleet(
        grants, args.account, apply=args.apply, census=args.census, say=emit, connect=connect, pin=pin,
        serves=lambda grant: bool(division.roles.get(grant.role, {}).get('serves', True)),
    )  # fmt: skip
