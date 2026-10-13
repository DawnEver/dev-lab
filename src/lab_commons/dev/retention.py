"""STORAGE RETENTION -- the serve loop deletes what its own runs left behind, and only what nothing references.

THE GROWTH THIS BOUNDS, measured 2026-10-13 on Ada (``du``/``mmlsquota``, read-only): every account the
forge serves keeps adding ``~/ci/trees/<sha>`` (a worktree per judged sha), ``~/ci/runs/<sha>``,
``~/ci/envs/<key>`` (a venv per dependency key, 48 on one account), ``~/ci/native/<key>``, the uv cache
and an unrotated ``~/.cache/lab-forge-<repo>.log``. Nothing removed any of it. Files, not bytes, are the
nearer ceiling there: 0.5 M of a 2 M file quota against 10 GB of a 1000 GB block quota.

ONE PASS, RUN BY ``forge serve`` ITSELF (:mod:`lab_commons.dev.forgeserve`), at most once per
``every_hours`` (state: ``forge-retention-<checkout hash>.json`` beside the machine file, one per served
checkout) and under one lock per account, so the several serves of one account (one per served repo)
never delete side by side. No cron line of its own.

THE POLICY IS DATA: :class:`Policy` holds the kit defaults, the machine file's ``[retention]`` table
overrides any of them, and an unknown key is refused. What each rule PROVES before it deletes:

* ``run-not-a-carry-source`` -- a finished run (its state holds a ``record``) of THIS serve's repo that
  no live tip can carry from. The sources are the carry's OWN selection
  (:func:`lab_commons.dev.forgecarry.read_by`, what ``SlurmCluster.carry`` reads) for every origin branch
  tip -- the integration tip, PR heads and lane tips -- plus each tip's own run, since a commit on top of
  a tip reads that run first (:func:`carry_sources`). Another repo's runs are its own serve's to judge.
  Its tree goes with it.
* ``run-abandoned`` -- no record, no live run file (``forge-runs/``), untouched for ``abandon_days``.
* ``tree-unreferenced`` -- a ``trees/<sha>`` no kept run names.
* ``env-unreferenced``, ``native-unreferenced`` -- an ``envs/<key>`` or ``native/<key>`` (and its
  ``.log``/``.lock``) no kept run was built with: a run state names its build keys
  (``builds = {env, native}``, :func:`lab_commons.hpc.run.submit_run`). A kept run of an older state that
  names none makes both rules decide nothing -- an unprovable reference is a reference.
* ``pack-not-in-flight``, ``slurm-out-finished`` (``~/slurm-*.out`` older than ``slurm_out_days``),
  ``log-over-size`` (rotated to ``.1``, the previous ``.1`` replaced), ``forge-tree-stale`` (a
  workstation's ``.claude/worktrees/forge-*`` its producer failed to remove, :mod:`lab_commons.dev.shatree`).

NEVER: a run in flight (a live run file names its sha), anything younger than ``min_age_hours`` (a
tree or env being built), or a path outside the roots the plan was given. Then ``uv cache prune`` and
``git worktree prune`` run, so the caches and git forget what went.

QUOTA-AWARE. The account's usage (``mmlsquota``; a workstation's disk) is read every tick; at
``pressure`` of the block OR file quota the pass runs at once and, after the plan, removes the
:attr:`Plan.harder` runs -- this repo's kept carry sources, never one in flight, OLDEST FIRST (a lost
source only costs the re-run it would have saved) -- until usage is back to ``target``. Still over: the
pass says so and serve raises a ``storage`` alarm (:mod:`lab_commons.dev.forgealarm`). EVERY DELETION IS
ONE JSON LINE (path, bytes, files, rule), and ``python -m lab_commons.dev.retention`` prints this host's
plan without deleting anything.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from lab_commons.config import config_path, section
from lab_commons.dev.diskusage import Usage, measure, read_usage, writable
from lab_commons.dev.forgecarry import read_by
from lab_commons.dev.forgerun import directory as run_files
from lab_commons.dev.platformparts import origin_url
from lab_commons.dev.servelock import held
from lab_commons.dev.worktreeplace import main_checkout
from lab_commons.log import emit

__all__ = [
    'EVENT',
    'Doomed',
    'Outcome',
    'Plan',
    'Policy',
    'apply',
    'carry_sources',
    'cluster_plan',
    'load_policy',
    'main',
    'serve_pass',
    'summary',
    'workstation_plan',
]

#: The ``event`` of every deletion line.
EVENT: Final = 'lab_commons.forge.retention'

_MB: Final = 1024**2
_GIT: Final = shutil.which('git') or 'git'


@dataclass(frozen=True)
class Policy:
    """The kit defaults; the machine file's ``[retention]`` overrides any key (module docstring)."""

    every_hours: float = 24.0
    min_age_hours: float = 24.0
    abandon_days: float = 7.0
    log_max_mb: float = 20.0
    slurm_out_days: float = 7.0
    uv_prune: bool = True
    pressure: float = 0.85
    target: float = 0.70


def load_policy(table: Mapping[str, Any]) -> Policy:
    """:class:`Policy` with *table* (the ``[retention]`` section) over its defaults; an unknown key raises."""
    known = {field.name for field in dataclasses.fields(Policy)}
    if unknown := sorted(set(table) - known):
        msg = f'[retention] has no key {", ".join(unknown)}; the keys are {", ".join(sorted(known))}'
        raise ValueError(msg)
    return Policy(**table)


@dataclass(frozen=True)
class Doomed:
    """One path the policy proved unreferenced, the rule that proved it, and how it goes."""

    path: Path
    rule: str
    rotate: bool = False


@dataclass(frozen=True)
class Plan:
    """What goes now, what goes only under quota pressure (oldest first), and the commands after."""

    doomed: tuple[Doomed, ...]
    harder: tuple[Doomed, ...] = ()
    commands: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class Outcome:
    """What one apply freed, and whether usage is still at the pressure line; *by_rule* is (paths, bytes, files)."""

    freed_bytes: int
    freed_files: int
    over: bool
    by_rule: Mapping[str, tuple[int, int, int]] = dataclasses.field(default_factory=dict)


def _age(path: Path, now: datetime) -> timedelta:
    return now - datetime.fromtimestamp(path.lstat().st_mtime, UTC)


def _entries(directory: Path) -> list[Path]:
    return sorted(directory.iterdir()) if directory.is_dir() else []


def _runs(ci: Path) -> list[tuple[Path, dict[str, Any], datetime]]:
    """Every ``runs/<sha>`` with its state and the state's mtime; an unreadable state reads as ``{}``."""
    out = []
    for run in _entries(ci / 'runs'):
        state = run / 'state.json'
        try:
            data = json.loads(state.read_text(encoding='utf-8'))
            when = datetime.fromtimestamp(state.stat().st_mtime, UTC)
        except (OSError, ValueError):
            data, when = {}, datetime.fromtimestamp(run.lstat().st_mtime, UTC)
        out.append((run, data if isinstance(data, dict) else {}, when))
    return out


def carry_sources(root: Path, shas: Iterable[str], tips: Iterable[str]) -> set[str]:
    """The runs among *shas* a commit at or on top of any of *tips* would carry from (module docstring).

    A tip's own :func:`~lab_commons.dev.forgecarry.read_by` covers a child's: the child reads the tip's run
    and the tip's nearest, a subset of what the tip reads.
    """
    shas = set(shas)
    return {sha for tip in set(tips) for sha in read_by(root, tip, shas)}


def cluster_plan(
    home: Path, policy: Policy, *, now: datetime, live: Iterable[str], repo: str, sources: Iterable[str]
) -> Plan:
    """The plan for one cluster account: ``~/ci`` by reference, then its slurm outputs and forge logs."""
    ci, live, sources, young = home / 'ci', set(live), set(sources), timedelta(hours=policy.min_age_hours)
    doomed: list[Doomed] = []
    kept: dict[str, dict[str, Any]] = {}
    harder: list[tuple[datetime, str]] = []
    for path, state, when in _runs(ci):
        sha = path.name
        if sha in live or now - when < young:
            kept[sha] = state
        elif 'record' not in state:
            if now - when < timedelta(days=policy.abandon_days):
                kept[sha] = state
            else:
                doomed += [Doomed(path, 'run-abandoned'), Doomed(ci / 'trees' / sha, 'run-abandoned')]
        elif state.get('repo') != repo:
            kept[sha] = state
        elif sha in sources:
            kept[sha] = state
            harder.append((when, sha))
        else:
            rule = 'run-not-a-carry-source'
            doomed += [Doomed(path, rule), Doomed(ci / 'trees' / sha, rule)]
    gone = {d.path for d in doomed}
    for tree in _entries(ci / 'trees'):
        if tree not in gone and tree.name not in kept and _age(tree, now) >= young:
            doomed.append(Doomed(tree, 'tree-unreferenced'))
    doomed += _unreferenced_builds(ci, [state.get('builds') for state in kept.values()], now, young)
    doomed += [
        Doomed(p, 'pack-not-in-flight') for p in _entries(ci / 'packs') if p.stem not in live and _age(p, now) >= young
    ]
    doomed += _home_rules(home, policy, now)
    order = [sha for _, sha in sorted(harder)]
    hard = tuple(Doomed(where / sha, 'quota-pressure') for sha in order for where in (ci / 'runs', ci / 'trees'))
    commands: list[tuple[str, ...]] = []
    if (ci / 'cache.git').is_dir():
        commands.append((_GIT, '--git-dir', str(ci / 'cache.git'), 'worktree', 'prune'))
    commands += _uv(policy, ci / 'uv-cache')
    return Plan(tuple(d for d in doomed if d.path.exists() or d.path.is_symlink()), hard, tuple(commands))


def _unreferenced_builds(ci: Path, builds: list[object], now: datetime, young: timedelta) -> list[Doomed]:
    """Env and native directories no kept run's ``builds`` names; nothing when a kept run names none."""
    if not all(isinstance(b, dict) for b in builds):
        return []
    out = []
    for kind, directory in (('env', ci / 'envs'), ('native', ci / 'native')):
        named = {b.get(kind) for b in builds if isinstance(b, dict)}
        out += [
            Doomed(e, f'{kind}-unreferenced')
            for e in _entries(directory)
            if e.name.split('.')[0] not in named and _age(e, now) >= young
        ]
    return out


def _home_rules(home: Path, policy: Policy, now: datetime) -> list[Doomed]:
    out = [
        Doomed(p, 'slurm-out-finished')
        for p in sorted(home.glob('slurm-*.out'))
        if _age(p, now) >= timedelta(days=policy.slurm_out_days)
    ]
    out += [
        Doomed(p, 'log-over-size', rotate=True)
        for p in sorted((home / '.cache').glob('lab-forge-*.log'))
        if p.stat().st_size > policy.log_max_mb * _MB
    ]
    return out


def _uv(policy: Policy, *caches: Path) -> list[tuple[str, ...]]:
    uv = shutil.which('uv')
    if not policy.uv_prune or uv is None:
        return []
    return [*((uv, 'cache', 'prune', '--cache-dir', str(c)) for c in caches if c.is_dir()), (uv, 'cache', 'prune')]


def workstation_plan(checkouts: Sequence[Path], policy: Policy, *, now: datetime) -> Plan:
    """The plan for a workstation: each checkout's stale ``forge-*`` trees, then ``git worktree prune``."""
    young = timedelta(hours=policy.min_age_hours)
    doomed: list[Doomed] = []
    commands: list[tuple[str, ...]] = []
    for checkout in checkouts:
        stale = [
            Doomed(t, 'forge-tree-stale')
            for t in _entries(checkout / '.claude' / 'worktrees')
            if t.name.startswith('forge-') and _age(t, now) >= young
        ]
        doomed += stale
        commands += [(_GIT, '-C', str(checkout), 'worktree', 'prune')] if stale else []
    return Plan(tuple(doomed), (), (*commands, *_uv(policy)))


def _remove(doomed: Doomed) -> None:
    if doomed.rotate:
        doomed.path.replace(doomed.path.with_name(doomed.path.name + '.1'))
    elif doomed.path.is_dir() and not doomed.path.is_symlink():
        shutil.rmtree(doomed.path, onexc=writable)
    else:
        doomed.path.unlink(missing_ok=True)


def apply(
    plan: Plan,
    policy: Policy,
    *,
    usage: Usage | None,
    dry_run: bool,
    say: Callable[[str], None],
    run: Callable[..., Any] = subprocess.run,
) -> Outcome:
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
        for doomed in plan.harder:
            if usage.fraction(*freed) <= policy.target:
                break
            one(doomed)
    for argv in plan.commands:
        say(json.dumps({'event': EVENT, 'command': list(argv), 'dry_run': dry_run}))
        if not dry_run:
            run(list(argv), capture_output=True, text=True, encoding='utf-8', errors='replace', check=False)
    over = usage is not None and usage.fraction(*freed) >= policy.pressure
    return Outcome(freed[0], freed[1], over, by_rule)


def summary(done: Outcome, usage: Usage | None, *, applied: bool) -> list[str]:
    """One line per rule (paths, MB, files), the total, then usage now -> after for bytes and FILES."""
    verb = 'deleted' if applied else 'would delete'
    lines = [
        f'[retention] {verb} {rule}: {paths} paths, {size / _MB:.1f} MB, {files} files'
        for rule, (paths, size, files) in sorted(done.by_rule.items())
    ]
    total = sum(paths for paths, _, _ in done.by_rule.values())
    lines.append(f'[retention] {verb} {total} paths, {done.freed_bytes / _MB:.1f} MB, {done.freed_files} files')
    if usage is not None:
        gb = 1024**3
        block = (
            f'bytes {usage.used / gb:.1f}/{usage.limit / gb:.1f} GB -> {(usage.used - done.freed_bytes) / gb:.1f} GB'
        )
        lines.append(f'[retention] usage {block}')
        if usage.files is not None and usage.files_limit:
            now, after = usage.files, usage.files - done.freed_files
            ceiling = usage.files_limit
            lines.append(
                f'[retention] usage files {now}/{ceiling} ({now / ceiling:.1%}) -> {after} ({after / ceiling:.1%})'
            )
    return lines


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
    done = subprocess.run(
        [_GIT, '-C', str(root), 'for-each-ref', '--format=%(objectname)', 'refs/remotes/origin'],
        capture_output=True, text=True, encoding='utf-8', errors='replace', check=True, timeout=60,
    )  # fmt: skip
    return done.stdout.split()


def _plan_for(root: Path, policy: Policy, *, cluster: bool, home: Path, now: datetime, live: set[str]) -> Plan:
    if cluster:
        repo = origin_url(root)
        mine = [p.name for p, state, _ in _runs(home / 'ci') if state.get('repo') == repo]
        sources = carry_sources(root, mine, _origin_tips(root))
        return cluster_plan(home, policy, now=now, live=live, repo=repo, sources=sources)
    return workstation_plan([main_checkout(root)], policy, now=now)


def _state_name(root: Path) -> str:
    """One pass clock per served checkout: on a cluster each repo's serve judges its own runs."""
    return f'forge-retention-{hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:12]}.json'


def serve_pass(
    root: Path,
    *,
    cluster: bool,
    home: Path | None = None,
    state: Path | None = None,
    table: Mapping[str, Any] | None = None,
    usage: Callable[[], Usage | None] | None = None,
    live: Callable[[], set[str]] = _live_shas,
    say: Callable[[str], None] = emit,
    run: Callable[..., Any] = subprocess.run,
    now: datetime | None = None,
    planner: Callable[..., Plan] | None = None,
) -> Outcome | None:
    """One due pass (module docstring): ``None`` when not due or another serve holds the pass."""
    home = Path.home() if home is None else home
    state = config_path().parent / _state_name(root) if state is None else state
    policy = load_policy(section('retention') if table is None else table)
    now = datetime.now(UTC) if now is None else now
    measured = (usage or (lambda: read_usage(home if cluster else root, cluster=cluster)))()
    try:
        last = datetime.fromisoformat(json.loads(state.read_text(encoding='utf-8'))['last'])
    except (OSError, ValueError, KeyError, TypeError):
        last = None
    pressed = measured is not None and measured.fraction() >= policy.pressure
    if not pressed and last is not None and now - last < timedelta(hours=policy.every_hours):
        return None
    with held(state.parent / 'forge-retention.lock') as mine:  # one deleter per account
        if not mine:
            return None
        plan = (planner or _plan_for)(root, policy, cluster=cluster, home=home, now=now, live=live())
        done = apply(plan, policy, usage=measured, dry_run=False, say=say, run=run)
        state.write_text(json.dumps({'last': now.isoformat(), 'freed_bytes': done.freed_bytes}), encoding='utf-8')
    return done


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m lab_commons.dev.retention [--cluster] [--apply]``: a DRY RUN unless ``--apply``; 0 always.

    One JSON line per path (path, bytes, files, rule), then :func:`summary` -- per rule, the total, and usage
    now -> after for bytes and files (Ada's binding ceiling is its FILE quota). Run it in the served checkout:
    on a cluster it judges that repo's runs only.
    """
    parser = argparse.ArgumentParser(prog='lab_commons.dev.retention', description=__doc__.splitlines()[0])
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
