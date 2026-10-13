"""STORAGE RETENTION -- the serve loop deletes what its own runs left behind, and only what nothing references.

THE GROWTH THIS BOUNDS, measured 2026-10-13 on Ada (``du``/``mmlsquota``, read-only): every account the
forge serves keeps adding ``~/ci/trees/<sha>`` (a worktree per judged sha), ``~/ci/runs/<sha>``,
``~/ci/envs/<key>`` (a venv per dependency key, 48 on one account), ``~/ci/native/<key>``, the uv cache
and an unrotated ``~/.cache/lab-forge-<repo>.log``. Nothing removed any of it. Files, not bytes, are the
nearer ceiling there: 0.5 M of a 2 M file quota against 10 GB of a 1000 GB block quota.

ONE PASS, RUN BY ``forge serve`` ITSELF (:mod:`lab_commons.dev.forgeserve`), at most once per
``every_hours`` (state: ``forge-retention*.json`` beside the machine file -- one per cluster account, one
per served checkout on a workstation) and under its own lock, so the several serves of one account (one
per served repo) never delete side by side. No cron line of its own.

THE POLICY IS DATA: :class:`Policy` holds the kit defaults, the machine file's ``[retention]`` table
overrides any of them, and an unknown key is refused. What each rule PROVES before it deletes:

* ``run-beyond-carry`` -- a finished run (its state holds a ``record``) that is not among the
  ``carry_keep`` newest finished runs of ITS ENV: compute-carry reads the nearest ancestor runs of the
  same env key, and the newest runs are the nearest ancestors of whatever comes next. Its tree goes with it.
* ``run-abandoned`` -- no record, no live run file (``forge-runs/``), untouched for ``abandon_days``.
* ``tree-unreferenced`` -- a ``trees/<sha>`` no kept run names.
* ``env-unreferenced`` -- an ``envs/<key>`` (and its ``.log``/``.lock``) no kept run was built in;
  the current env is always the env of some kept run, the newest of its env.
* ``native-beyond-keep`` -- native builds are not named by a run, so the ``native_keep`` newest stay.
* ``pack-not-in-flight``, ``slurm-out-finished`` (``~/slurm-*.out`` older than ``slurm_out_days``),
  ``log-over-size`` (rotated to ``.1``, the previous ``.1`` replaced), ``forge-tree-stale`` (a
  workstation's ``.claude/worktrees/forge-*`` its producer failed to remove, :mod:`lab_commons.dev.shatree`).

NEVER: a run in flight (a live run file names its sha), anything younger than ``min_age_hours`` (a
tree or env being built), or a path outside the roots the plan was given. Then ``uv cache prune`` and
``git worktree prune`` run, so the caches and git forget what went.

QUOTA-AWARE. The account's usage (``mmlsquota``; a workstation's disk) is read every tick; at
``pressure`` of the block OR file quota the pass runs at once and, after the plan, removes the
:attr:`Plan.harder` runs -- every kept run but the newest of its env and those in flight, OLDEST
FIRST -- until usage is back to ``target``. Still over: the pass says so and serve raises a ``storage``
alarm (:mod:`lab_commons.dev.forgealarm`). EVERY DELETION IS ONE JSON LINE (path, bytes, files, rule),
and ``python -m lab_commons.dev.retention`` prints this host's plan without deleting anything.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from lab_commons.log import emit

__all__ = [
    'EVENT',
    'Doomed',
    'Outcome',
    'Plan',
    'Policy',
    'Usage',
    'apply',
    'cluster_plan',
    'load_policy',
    'main',
    'parse_mmlsquota',
    'read_usage',
    'serve_pass',
    'workstation_plan',
]

#: The ``event`` of every deletion line.
EVENT: Final = 'lab_commons.forge.retention'

_MB: Final = 1024**2
_GIT: Final = shutil.which('git') or 'git'
_QUOTA_ROW: Final = re.compile(r'^\S+\s+\S+\s+USR\s+(\d+)\s+(\d+)\s+\d+\s+\d+\s+\S+\s*\|\s*(\d+)\s+(\d+)', re.MULTILINE)
_MMLSQUOTA: Final = ('mmlsquota', '/usr/lpp/mmfs/bin/mmlsquota')


@dataclass(frozen=True)
class Policy:
    """The kit defaults; the machine file's ``[retention]`` overrides any key (module docstring)."""

    every_hours: float = 24.0
    min_age_hours: float = 24.0
    carry_keep: int = 3
    abandon_days: float = 7.0
    native_keep: int = 3
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
class Usage:
    """Bytes and files held against their quota; ``files`` is ``None`` where no file quota is read."""

    used: int
    limit: int
    files: int | None
    files_limit: int | None

    def fraction(self, freed: int = 0, freed_files: int = 0) -> float:
        """The nearer of the two ceilings, as a fraction, after *freed* bytes and *freed_files* files."""
        parts = [(self.used - freed) / self.limit] if self.limit else []
        if self.files is not None and self.files_limit:
            parts.append((self.files - freed_files) / self.files_limit)
        return max(parts, default=0.0)


@dataclass(frozen=True)
class Outcome:
    """What one apply freed, and whether usage is still at the pressure line."""

    freed_bytes: int
    freed_files: int
    over: bool


def parse_mmlsquota(text: str) -> Usage | None:
    """The ``USR`` row of ``mmlsquota`` (KB blocks, then files); ``None`` when there is none."""
    hit = _QUOTA_ROW.search(text)
    if hit is None:
        return None
    used, limit, files, files_limit = (int(v) for v in hit.groups())
    return Usage(used * 1024, limit * 1024, files, files_limit)


def read_usage(home: Path, *, cluster: bool, run: Callable[..., Any] = subprocess.run) -> Usage | None:
    """The account quota on a cluster (``mmlsquota``; ``None`` when unreadable), else *home*'s disk."""
    if not cluster:
        disk = shutil.disk_usage(home)
        return Usage(disk.used, disk.total, None, None)
    for name in _MMLSQUOTA:
        if found := shutil.which(name) or (Path(name).is_file() and name):
            done = run([found], capture_output=True, text=True, encoding='utf-8', errors='replace', check=False)
            return parse_mmlsquota(done.stdout or '')
    return None


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


def cluster_plan(home: Path, policy: Policy, *, now: datetime, live: Iterable[str]) -> Plan:
    """The plan for one cluster account: ``~/ci`` by reference, then its slurm outputs and forge logs."""
    ci, live, young = home / 'ci', set(live), timedelta(hours=policy.min_age_hours)
    runs = sorted(_runs(ci), key=lambda r: r[2], reverse=True)  # newest first
    doomed: list[Doomed] = []
    kept: dict[str, str] = {}  # sha -> env
    harder: list[tuple[datetime, str]] = []
    seen: dict[str, int] = {}
    for path, state, when in runs:
        sha, env = path.name, str(state.get('env', ''))
        if sha in live or now - when < young:
            kept[sha] = env
            continue
        if 'record' not in state:
            if now - when < timedelta(days=policy.abandon_days):
                kept[sha] = env
            else:
                doomed += [Doomed(path, 'run-abandoned'), Doomed(ci / 'trees' / sha, 'run-abandoned')]
            continue
        seen[env] = seen.get(env, 0) + 1
        if seen[env] <= policy.carry_keep:
            kept[sha] = env
            if seen[env] > 1:
                harder.append((when, sha))
        else:
            doomed += [Doomed(path, 'run-beyond-carry'), Doomed(ci / 'trees' / sha, 'run-beyond-carry')]
    gone = {d.path for d in doomed}
    for tree in _entries(ci / 'trees'):
        if tree not in gone and tree.name not in kept and _age(tree, now) >= young:
            doomed.append(Doomed(tree, 'tree-unreferenced'))
    envs = set(kept.values())
    doomed += [
        Doomed(e, 'env-unreferenced')
        for e in _entries(ci / 'envs')
        if e.name.split('.')[0] not in envs and _age(e, now) >= young
    ]
    doomed += _beyond_keep(ci / 'native', policy.native_keep, now, young)
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


def _beyond_keep(directory: Path, keep: int, now: datetime, young: timedelta) -> list[Doomed]:
    keys: dict[str, list[Path]] = {}
    for entry in _entries(directory):
        keys.setdefault(entry.name.split('.')[0], []).append(entry)
    newest = sorted(keys, key=lambda k: max(p.lstat().st_mtime for p in keys[k]), reverse=True)
    return [Doomed(p, 'native-beyond-keep') for k in newest[keep:] for p in keys[k] if _age(p, now) >= young]


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


def _measure(path: Path) -> tuple[int, int]:
    if not path.is_dir() or path.is_symlink():
        return path.lstat().st_size, 1
    size, files = 0, 0
    for here, dirs, names in os.walk(path):
        for name in (*names, *dirs):
            try:
                size += (Path(here) / name).lstat().st_size
            except OSError:
                continue
            files += 1
    return size, files + 1


def _writable(func: Callable[..., Any], path: str, _exc: BaseException) -> None:
    Path(path).chmod(stat.S_IWRITE)  # a read-only git object on Windows
    func(path)


def _remove(doomed: Doomed) -> None:
    if doomed.rotate:
        doomed.path.replace(doomed.path.with_name(doomed.path.name + '.1'))
    elif doomed.path.is_dir() and not doomed.path.is_symlink():
        shutil.rmtree(doomed.path, onexc=_writable)
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

    def one(doomed: Doomed) -> None:
        if not (doomed.path.exists() or doomed.path.is_symlink()):
            return
        size, files = _measure(doomed.path)
        if not dry_run:
            _remove(doomed)
        freed[0], freed[1] = freed[0] + size, freed[1] + (0 if doomed.rotate else files)
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
    return Outcome(freed[0], freed[1], over)


def _live_shas() -> set[str]:
    from lab_commons.dev.forgerun import directory  # noqa: PLC0415 -- the serve path's run files

    shas = set()
    for path in sorted(directory().glob('*.json')) if directory().is_dir() else ():
        try:
            shas.add(str(json.loads(path.read_text(encoding='utf-8'))['sha']))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return shas


def _plan_for(root: Path, policy: Policy, *, cluster: bool, home: Path, now: datetime, live: set[str]) -> Plan:
    if cluster:
        return cluster_plan(home, policy, now=now, live=live)
    from lab_commons.dev.worktreeplace import main_checkout  # noqa: PLC0415 -- git only off a cluster

    return workstation_plan([main_checkout(root)], policy, now=now)


def _state_name(root: Path, *, cluster: bool) -> str:
    """One pass clock per account on a cluster; per served checkout on a workstation, which serves several."""
    if cluster:
        return 'forge-retention.json'
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
) -> Outcome | None:
    """One due pass (module docstring): ``None`` when not due or another serve holds the pass."""
    from lab_commons.config import config_path, section  # noqa: PLC0415 -- the machine file, read when serving
    from lab_commons.dev.servelock import held  # noqa: PLC0415

    home = Path.home() if home is None else home
    state = config_path().parent / _state_name(root, cluster=cluster) if state is None else state
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
    with held(state.with_suffix('.lock')) as mine:
        if not mine:
            return None
        plan = _plan_for(root, policy, cluster=cluster, home=home, now=now, live=live())
        done = apply(plan, policy, usage=measured, dry_run=False, say=say, run=run)
        state.write_text(json.dumps({'last': now.isoformat(), 'freed_bytes': done.freed_bytes}), encoding='utf-8')
    return done


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m lab_commons.dev.retention [--apply]``: this host's plan, one line per path; 0 always."""
    parser = argparse.ArgumentParser(prog='lab_commons.dev.retention', description=__doc__.splitlines()[0])
    parser.add_argument('--cluster', action='store_true', help="plan ~/ci (default: this checkout's forge trees)")
    parser.add_argument('--apply', action='store_true', help='delete; without it nothing is touched')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    from lab_commons.config import section  # noqa: PLC0415

    policy, home, now = load_policy(section('retention')), Path.home(), datetime.now(UTC)
    plan = _plan_for(Path.cwd(), policy, cluster=args.cluster, home=home, now=now, live=_live_shas())
    usage = read_usage(home if args.cluster else Path.cwd(), cluster=args.cluster)
    done = apply(plan, policy, usage=usage, dry_run=not args.apply, say=emit)
    after = f'; usage then {usage.fraction(done.freed_bytes, done.freed_files):.1%}' if usage else ''
    verb = 'freed' if args.apply else 'would free'
    emit(f'[retention] {verb} {done.freed_bytes / _MB:.1f} MB, {done.freed_files} files{after}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
