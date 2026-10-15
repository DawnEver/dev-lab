"""WHAT RETENTION DELETES -- the policy, the one definition of IN FLIGHT, and the plan built from them.

A FILE IS AN HPC RESOURCE (user ruling 2026-10-15: control the NUMBER of files intermediate artefacts make).
Measured 2026-10-15 on the cluster accounts the forge serves (GPFS file quota 2 M or 4 M each):
``~/ci/trees`` held 0.85-2.05 M files per account (40-81 per-sha trees, ~22 k files each) and ``~/ci/envs``
0.54-1.32 M; everything else under 60 k. Trees and envs are the whole problem, so the rules for them are
derived from what each is FOR, not from what happens to name it:

* A TREE is the workdir of a run's jobs and the place its streams land until :func:`gather_run
  <lab_commons.hpc.run.gather_run>` folds them into the record. After gather nothing reads it: the carry
  reads the RUN STATE (``runs/<sha>/state.json``), never the tree, and a re-run of the sha re-adds it from
  the bare cache (a ``git worktree add``; its env lives apart, keyed). So a tree is kept exactly while its
  sha is IN FLIGHT, by any repo's run -- ``tree-not-in-flight`` otherwise. Keeping the newest tree per branch
  would save one checkout at the price of ~22 k files; it does not.
* An ENV (``envs/<key>``), a NATIVE build and its ``cargo-target/<key>`` are kept while an in-flight run
  was built with them, plus the newest recorded run's per repo -- the next commit of that repo most likely
  shares its key, and a rebuild costs minutes. ``env-unreferenced``/``native-unreferenced``/
  ``cargo-unreferenced`` otherwise. An in-flight sha whose builds cannot be read (a job-file job in a tree no
  run state names, an older state, an unreadable queue) makes these rules decide nothing: an unprovable
  reference is a reference. uv HARDLINKS each env's files to ``UV_CACHE_DIR`` (``UV_LINK_MODE=hardlink``,
  :mod:`lab_commons.hpc.shell`), so an env's own inodes are its directories and the files uv writes; the
  rest go only once ``uv cache prune`` drops the cache entry too.

IN FLIGHT IS ONE FUNCTION, :func:`in_flight`, and every rule that keeps something for being in flight
reads it: a sha a live run file names (``forge-runs/``), a tree a queued or running Slurm job of this
account works in (``squeue --me -o %Z`` at or under ``trees/<sha>`` -- a job file submits from
``trees/<sha>/.lab-hpc/<run>``), a run not yet gathered (no ``record``) and not abandoned, or a run state
or tree younger than ``min_age_hours`` (being built). An unreadable queue (``None``) keeps every tree.

THE OTHER RULES. ``run-not-a-carry-source``: a recorded run of THIS serve's repo no origin branch tip
carries from (:func:`carry_sources`, the carry's own selection) -- its state goes; the kept sources are
the :attr:`Plan.harder` runs, removed oldest first only under quota pressure. ``run-abandoned``: no record,
nothing live, untouched ``abandon_days``. ``pack-not-in-flight``, ``slurm-out-finished``,
``log-over-size`` (rotated), and on a workstation ``forge-tree-stale``: a ``.claude/worktrees/forge-*``
its producer (:mod:`lab_commons.dev.shatree`) failed to remove -- the same rule, since a producer's tree is
in flight exactly while its producer runs.

THE POLICY IS DATA: :class:`Policy` holds the kit defaults, the machine file's ``[retention]`` table
overrides any of them, and an unknown or retired key is refused.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from lab_commons.dev.forgecarry import read_by
from lab_commons.hpc.retired import refuse_retired_keys
from lab_commons.hpc.slurm import WORKDIRS_COMMAND, parse_workdirs

__all__ = [
    'Doomed',
    'Plan',
    'Policy',
    'carry_sources',
    'cluster_plan',
    'in_flight',
    'load_policy',
    'occupied_trees',
    'runs',
    'slurm_occupied',
    'workstation_plan',
]

_MB: Final = 1024**2
_GIT: Final = shutil.which('git') or 'git'


@dataclass(frozen=True)
class Policy:
    """The kit defaults; the machine file's ``[retention]`` overrides any key (module docstring)."""

    min_age_hours: float = 24.0
    abandon_days: float = 7.0
    log_max_mb: float = 20.0
    slurm_out_days: float = 7.0
    uv_prune: bool = True
    pressure: float = 0.85
    target: float = 0.70


def load_policy(table: Mapping[str, Any]) -> Policy:
    """:class:`Policy` with *table* (the ``[retention]`` section) over its defaults; an unknown key raises."""
    refuse_retired_keys('retention', table)
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


def _age(path: Path, now: datetime) -> timedelta:
    return now - datetime.fromtimestamp(path.lstat().st_mtime, UTC)


def _entries(directory: Path) -> list[Path]:
    return sorted(directory.iterdir()) if directory.is_dir() else []


def runs(ci: Path) -> list[tuple[Path, dict[str, Any], datetime]]:
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


def in_flight(ci: Path, policy: Policy, *, now: datetime, live: Iterable[str], occupied: Iterable[str]) -> set[str]:
    """THE shas in flight (module docstring): live, occupied, ungathered and not abandoned, or being built."""
    young, abandon = timedelta(hours=policy.min_age_hours), timedelta(days=policy.abandon_days)
    shas = set(live) | set(occupied)
    for path, state, when in runs(ci):
        if now - when < young or ('record' not in state and now - when < abandon):
            shas.add(path.name)
    return shas | {tree.name for tree in _entries(ci / 'trees') if _age(tree, now) < young}


def carry_sources(root: Path, shas: Iterable[str], tips: Iterable[str]) -> set[str]:
    """The runs among *shas* a commit at or on top of any of *tips* would carry from (module docstring).

    A tip's own :func:`~lab_commons.dev.forgecarry.read_by` covers a child's: the child reads the tip's run
    and the tip's nearest, a subset of what the tip reads.
    """
    shas = set(shas)
    return {sha for tip in set(tips) for sha in read_by(root, tip, shas)}


def occupied_trees(workdirs: Iterable[str]) -> set[str]:
    """The ``<sha>`` of every ``ci/trees/<sha>`` a Slurm job's workdir is or lies under."""
    shas = set()
    for workdir in workdirs:
        parts = workdir.split('/')  # Slurm's paths are POSIX
        shas |= {parts[i + 2] for i in range(len(parts) - 2) if parts[i : i + 2] == ['ci', 'trees'] and parts[i + 2]}
    return shas


def slurm_occupied(run: Callable[..., Any] = subprocess.run) -> set[str] | None:
    """:func:`occupied_trees` of this account's queued and running jobs; ``None`` when the queue is unreadable."""
    try:
        done = run(list(WORKDIRS_COMMAND), capture_output=True, text=True, encoding='utf-8', errors='replace',
                   check=False, timeout=60)  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return None
    return occupied_trees(parse_workdirs(done.stdout)) if done.returncode == 0 else None


def cluster_plan(
    home: Path,
    policy: Policy,
    *,
    now: datetime,
    live: Iterable[str],
    repo: str,
    sources: Iterable[str],
    occupied: Iterable[str] | None = (),
) -> Plan:
    """The plan for one cluster account: ``~/ci`` by the rules above, then its slurm outputs and forge logs.

    *occupied* is :func:`slurm_occupied`: those trees are in flight; ``None`` (unreadable) keeps every tree.
    """
    ci, sources = home / 'ci', set(sources)
    flying = in_flight(ci, policy, now=now, live=live, occupied=occupied or ())
    states = runs(ci)
    doomed: list[Doomed] = []
    harder: list[tuple[datetime, str]] = []
    for path, state, when in states:
        sha = path.name
        if sha in flying:
            continue
        if 'record' not in state:
            doomed.append(Doomed(path, 'run-abandoned'))
        elif state.get('repo') != repo:
            continue  # another repo's serve judges its own runs
        elif sha in sources:
            harder.append((when, sha))
        else:
            doomed.append(Doomed(path, 'run-not-a-carry-source'))
    if occupied is not None:
        doomed += [Doomed(tree, 'tree-not-in-flight') for tree in _entries(ci / 'trees') if tree.name not in flying]
    doomed += _unreferenced_builds(ci, _needed_builds(states, flying, occupied), now, policy)
    doomed += [Doomed(p, 'pack-not-in-flight') for p in _entries(ci / 'packs') if p.stem not in flying]
    doomed += _home_rules(home, policy, now)
    hard = tuple(Doomed(ci / 'runs' / sha, 'quota-pressure') for _, sha in sorted(harder))
    commands: list[tuple[str, ...]] = []
    if (ci / 'cache.git').is_dir():
        commands.append((_GIT, '--git-dir', str(ci / 'cache.git'), 'worktree', 'prune'))
    commands += _uv(policy, ci / 'uv-cache')
    doomed = [d for d in doomed if d.path.exists() or d.path.is_symlink()]
    return Plan(tuple(doomed), hard, tuple(commands))


def _needed_builds(
    states: list[tuple[Path, dict[str, Any], datetime]], flying: set[str], occupied: Iterable[str] | None
) -> list[object]:
    """The ``builds`` of each in-flight run and each repo's newest recorded run; ``None`` where one is unread.

    A job in a tree no run state names, and an unreadable queue, name builds nobody can read.
    """
    by_sha = {path.name: state for path, state, _ in states}
    needed = [by_sha[sha].get('builds') for sha in sorted(flying) if sha in by_sha]
    needed += [None for sha in (() if occupied is None else occupied) if sha not in by_sha]
    needed += [None] if occupied is None else []
    newest: dict[str, tuple[datetime, object]] = {}
    for _, state, when in states:
        repo = str(state.get('repo', ''))
        if 'record' in state and (repo not in newest or when >= newest[repo][0]):
            newest[repo] = (when, state.get('builds'))
    return needed + [builds for _, builds in newest.values()]


def _unreferenced_builds(ci: Path, builds: list[object], now: datetime, policy: Policy) -> list[Doomed]:
    """Env and native directories none of *builds* names; nothing when one of them names none."""
    if not all(isinstance(b, dict) for b in builds):
        return []
    young, out = timedelta(hours=policy.min_age_hours), []
    # ``cargo-target/<native key>`` is lab_commons.hpc.builds.cargo_target, keyed like ``native/<key>``
    for kind, where in (('env', 'envs'), ('native', 'native'), ('native', 'cargo-target')):
        named = {b.get(kind) for b in builds if isinstance(b, dict)}
        out += [
            Doomed(e, f'{"cargo" if where == "cargo-target" else kind}-unreferenced')
            for e in _entries(ci / where)
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
