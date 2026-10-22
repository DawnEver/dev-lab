"""STORAGE RETENTION -- serve deletes what its own runs left behind, EVERY TICK, and alarms when that is not enough.

WHAT GOES is :mod:`dev_lab.dev.retentionplan`: the policy, the one definition of IN FLIGHT, and the
rules derived from it (a tree only while its sha is in flight; an env only while an in-flight run or its
repo's newest recorded run was built with it). This module RUNS that plan.

EVERY FORGE TICK (user ruling 2026-10-15: files are an HPC resource, and a budget read once a day is
exceeded between reads). ``forge serve`` (:mod:`dev_lab.dev.forgeserve`) calls :func:`serve_pass`
each tick, under one lock per account (``forge-retention.lock`` beside the machine file), so the several
serves of one account (one per served repo) never delete side by side. A tick with nothing to delete
deletes nothing and runs no command; ``git worktree prune`` and ``uv cache prune`` run only after a pass
that deleted something, so git and the cache forget what went.

THE FILE BUDGET IS THE ACCOUNT'S QUOTA, read once and used twice: ``mmlsquota`` (a workstation's disk) is
read every tick (:func:`dev_lab.dev.diskusage.read_usage`), and the same reading is the ``files``
supply admission compares (:mod:`dev_lab.dev.forgeslurm`). At ``pressure`` of the block OR file quota
the pass also removes the :attr:`~dev_lab.dev.retentionplan.Plan.harder` runs -- this repo's kept
carry sources, never one in flight, OLDEST FIRST, or MOST FILES FIRST when files bind -- until usage is
back to ``target``. Still over: the outcome carries a ``storage`` alarm (:mod:`dev_lab.dev.forgealarm`)
whose body is :func:`dev_lab.dev.diskusage.pressure_text` -- which limit, used/limit for each, and the
home's biggest directories by file count, the ones the forge does not own named and never touched. The
host alarms; it does not let jobs fail on a full quota in silence.

EVERY DELETION IS ONE JSON LINE (path, bytes, files, rule), and ``python -m dev_lab.dev.retention``
prints this host's plan without deleting anything.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import shutil
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import lab_commons.launch as _door
from lab_commons.config import config_path, section
from dev_lab.dev.diskusage import Usage, files_first, measure, pressure_text, read_usage, remove_tree
from dev_lab.dev.forgerunstate import directory as run_files
from dev_lab.dev.platformparts import origin_url
from dev_lab.dev.retentionplan import (
    Doomed,
    Plan,
    Policy,
    carry_sources,
    cluster_plan,
    load_policy,
    runs,
    slurm_occupied,
    workstation_plan,
)
from dev_lab.dev.servelock import held
from dev_lab.dev.worktreeplace import main_checkout
from lab_commons.hpc.records import kept_text
from lab_commons.log import emit

__all__ = ['EVENT', 'Freed', 'apply', 'main', 'serve_pass', 'summary']

#: The ``event`` of every deletion line.
EVENT: Final = 'lab_commons.forge.retention'

_MB: Final = 1024**2
_GIT: Final = shutil.which('git') or 'git'


@dataclass(frozen=True)
class Freed:
    """What one apply freed, and whether usage is still at the pressure line; *by_rule* is (paths, bytes, files)."""

    freed_bytes: int
    freed_files: int
    over: bool
    by_rule: Mapping[str, tuple[int, int, int]] = dataclasses.field(default_factory=dict)
    alarm: str = ''  # still over: the body of the storage alarm (dev_lab.dev.diskusage.pressure_text)


def _remove(doomed: Doomed) -> None:
    for source, target in doomed.keep:
        if text := kept_text(source):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding='utf-8')
    if doomed.rotate:
        doomed.path.replace(doomed.path.with_name(doomed.path.name + '.1'))
    elif doomed.path.is_dir() and not doomed.path.is_symlink():
        remove_tree(doomed.path)
    else:
        doomed.path.unlink(missing_ok=True)


def apply(
    plan: Plan,
    policy: Policy,
    *,
    usage: Usage | None,
    dry_run: bool,
    say: Callable[[str], None],
    run: Callable[..., Any] = _door.run,
) -> Freed:
    """Delete *plan*'s paths -- then its harder ones while *usage* is over ``pressure`` -- one JSON line each."""
    freed = [0, 0]
    by_rule: dict[str, tuple[int, int, int]] = {}

    def one(doomed: Doomed) -> None:
        if not (doomed.path.exists() or doomed.path.is_symlink()):
            return
        size, files = measure(doomed.path)
        if not dry_run:
            _remove(doomed)
        files = 0 if doomed.rotate else files
        freed[0], freed[1] = freed[0] + size, freed[1] + files
        paths, total, count = by_rule.get(doomed.rule, (0, 0, 0))
        by_rule[doomed.rule] = (paths + 1, total + size, count + files)
        row = {'path': str(doomed.path), 'bytes': size, 'files': files, 'rule': doomed.rule, 'dry_run': dry_run}
        say(json.dumps({'event': EVENT, **row}))

    for doomed in plan.doomed:
        one(doomed)
    if usage is not None and usage.fraction(*freed) >= policy.pressure:
        files_bind = usage.binding(*freed) == 'files'  # then a run with its tree, most files first
        for doomed in files_first(plan.harder, lambda d: d.path) if files_bind else plan.harder:
            if usage.fraction(*freed) <= policy.target:
                break
            one(doomed)
    for argv in plan.commands if by_rule else ():  # nothing went: nothing for git or the cache to forget
        say(json.dumps({'event': EVENT, 'command': list(argv), 'dry_run': dry_run}))
        if not dry_run:
            run(list(argv), capture_output=True, text=True, encoding='utf-8', errors='replace', check=False)
    over = usage is not None and usage.fraction(*freed) >= policy.pressure
    return Freed(freed[0], freed[1], over, by_rule)


def summary(done: Freed, usage: Usage | None, *, applied: bool) -> list[str]:
    """One line per rule (paths, MB, files), the total, then usage now -> after for bytes and FILES."""
    verb = 'deleted' if applied else 'would delete'
    lines = [
        f'[retention] {verb} {rule}: {paths} paths, {size / _MB:.1f} MB, {files} files'
        for rule, (paths, size, files) in sorted(done.by_rule.items())
    ]
    total = sum(paths for paths, _, _ in done.by_rule.values())
    lines.append(f'[retention] {verb} {total} paths, {done.freed_bytes / _MB:.1f} MB, {done.freed_files} files')
    after = usage.after(done.freed_bytes, done.freed_files) if usage is not None else []
    return lines + [f'[retention] {line}' for line in after]


def _live_shas() -> set[str]:
    shas = set()
    for path in sorted(run_files().glob('*.json')) if run_files().is_dir() else ():
        try:
            shas.add(str(json.loads(path.read_text(encoding='utf-8'))['sha']))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return shas


def _origin_tips(root: Path) -> list[str]:
    """Every origin branch tip *root* fetched: the integration tip, PR heads and lane tips alike."""
    done = _door.run(
        [_GIT, '-C', str(root), 'for-each-ref', '--format=%(objectname)', 'refs/remotes/origin'],
        capture_output=True, text=True, encoding='utf-8', errors='replace', check=True, timeout=60,
    )  # fmt: skip
    return done.stdout.split()


def _plan_for(root: Path, policy: Policy, *, cluster: bool, home: Path, now: datetime, live: set[str]) -> Plan:
    if cluster:
        repo = origin_url(root)
        mine = [p.name for p, state, _ in runs(home / 'ci') if state.get('repo') == repo]
        sources = carry_sources(root, mine, _origin_tips(root))
        occupied = slurm_occupied()
        return cluster_plan(home, policy, now=now, live=live, repo=repo, sources=sources, occupied=occupied)
    return workstation_plan([main_checkout(root)], policy, now=now)


def serve_pass(
    root: Path,
    *,
    cluster: bool,
    home: Path | None = None,
    lock: Path | None = None,
    table: Mapping[str, Any] | None = None,
    usage: Callable[[], Usage | None] | None = None,
    live: Callable[[], set[str]] = _live_shas,
    say: Callable[[str], None] = emit,
    run: Callable[..., Any] = _door.run,
    now: datetime | None = None,
    planner: Callable[..., Plan] | None = None,
) -> Freed | None:
    """One pass, every tick (module docstring): ``None`` only when another serve of the account holds it."""
    home = Path.home() if home is None else home
    lock = config_path().parent / 'forge-retention.lock' if lock is None else lock
    policy = load_policy(section('retention') if table is None else table)
    now = datetime.now(UTC) if now is None else now
    measured = (usage or (lambda: read_usage(home if cluster else root, cluster=cluster)))()
    with held(lock) as mine:  # one deleter per account
        if not mine:
            return None
        plan = (planner or _plan_for)(root, policy, cluster=cluster, home=home, now=now, live=live())
        done = apply(plan, policy, usage=measured, dry_run=False, say=say, run=run)
    if done.over:
        freed = (done.freed_bytes, done.freed_files)
        done = dataclasses.replace(done, alarm=pressure_text(measured, freed, home if cluster else None))
    return done


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m dev_lab.dev.retention [--cluster] [--apply]``: a DRY RUN unless ``--apply``; 0 always.

    One JSON line per path (path, bytes, files, rule), then :func:`summary` -- per rule, the total, and usage
    now -> after for bytes and files (Ada's binding ceiling is its FILE quota). Run it in the served checkout:
    on a cluster it judges that repo's runs only.
    """
    parser = argparse.ArgumentParser(prog='dev_lab.dev.retention', description=__doc__.splitlines()[0])
    parser.add_argument('--cluster', action='store_true', help="plan ~/ci (default: this checkout's forge trees)")
    parser.add_argument('--apply', action='store_true', help='delete; without it nothing is touched')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    policy, home, now = load_policy(section('retention')), Path.home(), datetime.now(UTC)
    plan = _plan_for(Path.cwd(), policy, cluster=args.cluster, home=home, now=now, live=_live_shas())
    usage = read_usage(home if args.cluster else Path.cwd(), cluster=args.cluster)
    done = apply(plan, policy, usage=usage, dry_run=not args.apply, say=emit)
    for line in summary(done, usage, applied=args.apply):
        emit(line)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
