"""``backup`` and ``backup-fleet`` -- an account's crontab and machine file, saved before maintenance, restored after.

``python -m dev_lab.dev.hpcaccount backup [--config <machine file>] [--dry-run] [--restore <stamp>|latest]`` runs ON
the account. Without ``--restore`` it writes ``~/.cache/dev-lab/<yy>/<mm>/<dd>/backup/<utc stamp>/`` holding exactly
two things: the FULL ``crontab -l`` (every line, not only this tool's marked ones -- a research account carries
none of ours by design, yet whatever it has is kept) and the rendered machine file; then prints that path. Nothing
else is read or written (no credential store is ever touched). A ``crontab -l`` failing other than "no crontab"
exits 2 and writes nothing.

``--restore <stamp>`` puts those two things back from that backup (``latest``: the newest one). The crontab's
MARKED lines are replaced with the backup's (:func:`dev_lab.dev.hpcaccount.spec.merge_crontab`), every other line
kept -- unless one of the user's own backed-up lines is gone, and then the whole backed-up crontab is restored. The
machine file is replaced the way ``devhost render --write`` replaces it (:func:`dev_lab.dev.devhost.replace_backed_up`:
the current file copied under ``~/.cache/dev-lab/<yy>/<mm>/<dd>/devhost`` first). A CI-PAUSED account refuses a
restore, which would bring its CI lines back: ``ci-resume-fleet`` is the door (:mod:`dev_lab.dev.hpcaccount.cimark`).

``python -m dev_lab.dev.hpcaccount backup-fleet (--cluster <name> | --account <user>)... [--dry-run] [--restore S]``
runs that on each SELECTED account of the declared fleet, through the same transport and layer target as
``deploy-fleet`` (:mod:`dev_lab.dev.hpcaccount.fleet`), one log per account under
``~/.cache/dev-lab/<yy>/<mm>/<dd>/<verb>-fleet/``. A run naming neither filter is refused: the whole fleet is never
selected by default. Both filters select the accounts matching both; an undeclared cluster or account is refused
before any ssh.
"""

from __future__ import annotations

import argparse
import datetime as dt
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

from lab_commons import config as machineconfig
from lab_commons.config import config_path
from lab_commons.hpc.grants import Grant
from lab_commons.log import emit

from dev_lab.dev.datedlog import date_parts, dated_log
from dev_lab.dev.devhost import replace_backed_up
from dev_lab.dev.hpcaccount.cimark import paused_refusal
from dev_lab.dev.hpcaccount.division import division_of, reached_machine
from dev_lab.dev.hpcaccount.fleet import (
    ConfigSource,
    Launch,
    Target,
    config_source_of,
    in_checkout,
    layer_refusal,
    layer_target,
)
from dev_lab.dev.hpcaccount.spec import MARK, merge_crontab
from dev_lab.dev.hpcaccount.steps import Step, Tools
from dev_lab.dev.hpcaccount.transport import describe, start

__all__ = ['CRONTAB', 'KIND', 'backup', 'backup_fleet', 'main', 'main_fleet', 'restore', 'select', 'write_backup']

#: The dated kind of an account's backup directory.
KIND: Final = 'backup'
#: The crontab's file in a backup; the machine file sits beside it as ``machine-<name>``.
CRONTAB: Final = 'crontab.txt'
_BASE: Final = '.cache/dev-lab'


def _listed(step: Step) -> str | None:
    """The account's crontab text (``''`` when it has none); ``None`` when ``crontab -l`` fails otherwise."""
    done = step.read([*step.tools.crontab, '-l'])
    if done.returncode == 0:
        return done.stdout
    return '' if 'no crontab' in done.stderr else None


def write_backup(step: Step, home: Path, machine: Path) -> Path | str:
    """Back up the crontab and *machine* under *home*; the directory, else why nothing was written.

    Under ``step.dry`` the directory it would write is returned and nothing is written.
    """
    current = _listed(step)
    if current is None:
        return 'crontab -l failed: the crontab cannot be read, so nothing was backed up'
    target = home.joinpath(_BASE, *date_parts(), KIND, dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ'))
    if step.dry:
        return target
    try:
        target.mkdir(parents=True, exist_ok=False)
        (target / CRONTAB).write_text(current, encoding='utf-8')
        if machine.is_file():
            (target / f'machine-{machine.name}').write_bytes(machine.read_bytes())
    except OSError as failed:
        return f'could not write {target}: {failed}'
    return target


def _found(home: Path, stamp: str) -> Path | str:
    backups = sorted(home.glob(f'{_BASE}/*/*/*/{KIND}/*'), key=lambda path: path.name)
    chosen = backups[-1:] if stamp == 'latest' else [path for path in backups if path.name == stamp]
    if not chosen:
        return f'no backup {stamp!r} under {home / _BASE}; take one with python -m dev_lab.dev.hpcaccount backup-fleet'
    return chosen[-1]


def _machine(step: Step, home: Path, machine: Path, copy: Path) -> None:
    if not copy.is_file():
        return
    if step.dry:
        emit(f'  [dry-run] restore {machine} from {copy}')
        return
    backups = home.joinpath(_BASE, *date_parts(), 'devhost')
    previous = replace_backed_up(machine, copy.read_text(encoding='utf-8'), backups)
    emit(f'  restored {machine}; the previous file is {previous}')


def restore(step: Step, home: Path, machine: Path, stamp: str) -> int:
    """Put back the crontab and machine file of backup *stamp*; 0 restored, 2 refused."""
    found = _found(home, stamp)
    current = _listed(step)
    why = paused_refusal(home) or (found if isinstance(found, str) else '')
    if why or current is None or isinstance(found, str):
        emit(f'restore refused: {why or "crontab -l failed"}', err=True)
        return 2
    saved = (found / CRONTAB).read_text(encoding='utf-8')
    lost = [line for line in saved.splitlines() if MARK not in line and line not in current.splitlines()]
    wanted = saved if lost else merge_crontab(current, [line for line in saved.splitlines() if MARK in line])
    how = f'the whole backed-up crontab ({len(lost)} of your own lines were gone)' if lost else 'its marked lines'
    if rc := step.change(f'crontab: restore {how} from {found}', [*step.tools.crontab, '-'], stdin=wanted):
        return rc
    _machine(step, home, machine, found / f'machine-{machine.name}')
    emit(f'restored from {found}')
    return 0


def backup(argv: Sequence[str], *, home: Path, tools: Tools | None = None) -> int:
    """Back up this account (or ``--restore`` one backup); 0 done (or printed under ``--dry-run``), 2 refused."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.hpcaccount backup', description=__doc__.splitlines()[0])
    parser.add_argument('--config', type=Path, help='the rendered machine file (default: lab_commons.config)')
    parser.add_argument('--dry-run', action='store_true', help='print what would be written; write nothing')
    parser.add_argument('--restore', metavar='STAMP', help="put back backup STAMP's crontab and machine file (latest)")
    args = parser.parse_args(list(argv))
    step, machine = Step(tools or Tools(), dry=args.dry_run), args.config or config_path()
    if args.restore:
        return restore(step, home, machine, args.restore)
    written = write_backup(step, home, machine)
    if isinstance(written, str):
        emit(f'backup refused: {written}', err=True)
        return 2
    emit(f'{"[dry-run] would write" if step.dry else "backup written:"} {written}')
    return 0


def main(argv: Sequence[str]) -> int:
    """The on-account ``backup`` verb."""
    return backup(argv, home=Path.home())


def select(grants: Sequence[Grant], accounts: Sequence[str], clusters: Sequence[str]) -> list[Grant] | str:
    """The first grant of each account matching every given filter; else why the selection is refused."""
    if not (accounts or clusters):
        return 'name at least one --cluster or --account: the whole fleet is never selected by default'
    if unknown := sorted(set(accounts) - {g.user for g in grants}):
        return f'{unknown} not in the declared fleet'
    if unknown := sorted(set(clusters) - {g.cluster_name for g in grants}):
        return f'cluster(s) {unknown} not in the declared fleet'
    chosen: dict[str, Grant] = {}
    for grant in grants:
        if (not accounts or grant.user in accounts) and (not clusters or grant.cluster_name in clusters):
            chosen.setdefault(grant.user, grant)
    return list(chosen.values()) or 'no declared account matches both --cluster and --account'


def backup_fleet(
    grants: Sequence[Grant],
    accounts: Sequence[str],
    clusters: Sequence[str],
    *,
    home: Path,
    source: ConfigSource,
    say: Callable[[str], None],
    launch: Launch = start,
    verb: str = 'backup',
    args: Sequence[str] = (),
    serving_only: Callable[[Target], bool] | None = None,
) -> int:
    """Start ``<verb> <args>`` on each selected account's declared host; 2 when the selection or an account is refused.

    With *serving_only*, an account it rejects is skipped when a ``--cluster`` selected it and refused when named by
    ``--account``: a research account has no CI cron by design.
    """
    chosen = select(grants, accounts, clusters)
    if isinstance(chosen, str):
        say(f'{verb}-fleet: refused -- {chosen}')
        return 2
    refused = 0
    for grant in chosen:
        target = layer_refusal(grant, source) or layer_target(grant, source)
        if isinstance(target, str):
            say(target)
            refused += 1
            continue
        if serving_only is not None and not serving_only(target):
            say(f'{grant.user} ({target.role or "role undeclared"}): {verb} skipped -- no CI cron by design')
            refused += grant.user in accounts
            continue
        dest = f'{grant.user}@{target.host}'
        command = in_checkout(target, ['-m', 'dev_lab.dev.hpcaccount', verb, *args])
        path = dated_log(home, f'{grant.user}.log', base=_BASE, kind=f'{verb}-fleet')
        say(f'{grant.user} ({grant.cluster_name}): started {describe(dest, command)}  log {path}')
        with path.open('a', encoding='utf-8') as log:
            launch(dest, command, log)
    return 2 if refused else 0


def main_fleet(argv: Sequence[str], *, verb: str = 'backup', ci_only: bool = False) -> int:
    """Parse ``<verb>-fleet`` and start *verb* on each selected account; *ci_only* skips non-serving roles."""
    parser = argparse.ArgumentParser(prog=f'dev_lab.dev.hpcaccount {verb}-fleet', description=f'{verb} accounts')
    parser.add_argument('--cluster', action='append', default=[], help='every account of one cluster (repeatable)')
    parser.add_argument('--account', action='append', default=[], help='one account of the fleet (repeatable)')
    parser.add_argument('--dry-run', action='store_true', help='each account prints what it would do, changes nothing')
    if verb == KIND:
        parser.add_argument('--restore', metavar='STAMP', help="put back backup STAMP's crontab and machine file")
    args = parser.parse_args(list(argv))
    forwarded = ['--dry-run'] * args.dry_run + (['--restore', args.restore] if getattr(args, 'restore', None) else [])
    try:
        machine = reached_machine(args.account)
        source = config_source_of(machineconfig.machine())
    except (PermissionError, LookupError, ValueError) as refused:
        emit(f'{verb}-fleet: refused -- {refused}')
        return 2
    roles = division_of(machine).roles
    return backup_fleet(
        machine.grants, args.account, args.cluster, home=Path.home(), source=source, say=emit, verb=verb,
        args=forwarded, serving_only=(lambda t: bool(roles.get(t.role, {}).get('serves'))) if ci_only else None,
    )  # fmt: skip
