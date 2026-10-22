"""WHAT RETENTION DELETES -- the policy, the one definition of IN FLIGHT, and the plan built from them.

A FILE IS AN HPC RESOURCE (user ruling 2026-10-15: control the NUMBER of files intermediate artefacts make).
Measured 2026-10-15 on the cluster accounts the forge serves (GPFS file quota 2 M or 4 M each):
``~/ci/trees`` held 0.85-2.05 M files per account (40-81 per-sha trees, ~22 k files each) and ``~/ci/envs``
0.54-1.32 M; everything else under 60 k. Trees and envs are the whole problem, so the rules for them are
derived from what each is FOR, not from what happens to name it:

* A TREE is the workdir of a run's jobs and the place its streams land until :func:`gather_run
  <lab_commons.hpc.gather.gather_run>` folds them into the record. Of its ~22 k files only the streams of the
  round in flight (``.lab-ci/<tag>.jsonl``, one file) are read after its jobs end: the carry takes a SUPERSEDED
  run's finished shards from them (:func:`lab_commons.hpc.records.held_cells`). So a tree is kept exactly
  while its sha is IN FLIGHT, by any repo's run -- ``tree-not-in-flight`` otherwise -- and before an
  unrecorded run's tree goes its round's stream is KEPT as one file beside its state
  (:func:`lab_commons.hpc.records.stream_sources`). A run kept in the retired many-file shape
  (``runs/<sha>/streams/<tag>.txt``) is upgraded into that one file, ``streams-upgraded``.
  A re-run of the sha re-adds the tree from the bare cache (its env lives apart, keyed). Keeping the newest
  tree per branch would save one checkout at the price of ~22 k files; it does not.
* An ENV (``envs/<key>``), a NATIVE build and its ``cargo-target/<key>`` are kept while an in-flight run
  was built with them, plus the newest recorded run's per repo -- the next commit of that repo most likely
  shares its key, and a rebuild costs minutes. ``env-unreferenced``/``native-unreferenced``/
  ``cargo-unreferenced`` otherwise. An in-flight sha whose builds cannot be read (a job-file job in a tree no
  run state names reads its env from the ``.lab-ci/env.sh`` it sources; an older state, an unreadable
  ``env.sh`` or an unreadable queue) makes these rules decide nothing: an unprovable
  reference is a reference. uv HARDLINKS each env's files to ``UV_CACHE_DIR`` (``UV_LINK_MODE=hardlink``,
  :mod:`lab_commons.hpc.shell`), so an env's own inodes are its directories and the files uv writes; the
  rest go only once ``uv cache prune`` drops the cache entry too.

* An ARTIFACT (``artifacts/<sha>.<suffix>``, :mod:`lab_commons.hpc.artifact`) is the one file a job at a
  commit runs from. It is kept while its sha is in flight -- a queued or running job submits from
  ``jobs/<sha>/<run>`` -- and the newest artifact is kept besides, as the next job most likely runs the same
  commit; ``artifact-not-live`` otherwise. An unreadable queue keeps every artifact.

IN FLIGHT IS ONE FUNCTION, :func:`in_flight`, and every rule that keeps something for being in flight
reads it: a sha a live run file names (``forge-runs/``), a sha a queued or running Slurm job of this
account works under (``squeue --me -o %Z`` at or under ``trees/<sha>`` or ``jobs/<sha>``,
:func:`occupied_shas`), or a sha ACTIVE within ``min_age_hours`` -- its run state, its tree, its artifact,
or a stream directory under ``.lab-ci`` touched (being built, or a round ended and not yet gathered). An unreadable
queue (``None``) keeps every tree. NOT "no record yet": measured 2026-10-15 on the served accounts, 9 run
states in 10 had no record -- runs SUPERSEDED by a newer commit or released, which nobody will ever gather --
and that clause kept 79 trees of 81 and every env.

THE COLLECT CACHE (``collect/``, :mod:`lab_commons.hpc.collect`) is one ``<key>.json`` per collection key,
and the key moves with every build key, so an old key is never read again. Its budget is ``collect_files``:
the newest that many key files stay; anything else there -- an older key, a dead writer's ``.tmp``, a
directory of the retired one-file-per-test layout (~0.75-1 M files per account, measured 2026-10-16) --
goes as ``collect-over-budget`` once older than ``min_age_hours``.

THE OTHER RULES. ``run-not-a-carry-source``: a recorded run of THIS serve's repo no origin branch tip
carries from (:func:`carry_sources`, the carry's own selection) -- its state goes; the kept sources are
the :attr:`Plan.harder` runs, removed oldest first only under quota pressure. ``run-abandoned``: no record,
not in flight, untouched ``abandon_days`` (a state is a few files, and the carry reads it).
``pack-not-in-flight``, ``slurm-out-finished``, ``log-over-size`` (rotated), and on a workstation
``forge-tree-stale``: a ``.claude/worktrees/forge-*``
its producer (:mod:`dev_lab.dev.shatree`) failed to remove -- the same rule, since a producer's tree is
in flight exactly while its producer runs. ``shared-cache-retired``: the one bare ``ci/cache.git`` every
repository once fetched into goes whole -- each repository has its own ``ci/cache/<slug>.git``
(:func:`lab_commons.hpc.shell.cache_dir`), whose worktrees are pruned every pass; a cache is regenerable.

UNIT RESULTS ON THE FORGE (``unit-<unit hash>-<result hash>.*`` beside the run records,
:class:`dev_lab.dev.forgeunit.ForgeResults`) are a content-addressed cache, not evidence: no sha keeps
one, and a pruned result is recomputed on the next miss. ``unit_results`` is their budget -- the newest that
many attachments stay, older ones go (:func:`dev_lab.dev.forgerecords.prune`).

THE POLICY IS DATA: :class:`Policy` holds the kit defaults, the machine file's ``[retention]`` table
overrides any of them, and an unknown or retired key is refused.
"""

from __future__ import annotations

import dataclasses
import json
import re
import shutil
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import lab_commons.launch as _door
from lab_commons.hpc.records import stream_sources
from lab_commons.hpc.retired import refuse_retired_keys
from lab_commons.hpc.slurm import WORKDIRS_COMMAND, parse_workdirs

from dev_lab.dev.forgecarry import read_by

__all__ = [
    'Doomed',
    'Plan',
    'Policy',
    'carry_sources',
    'cluster_plan',
    'in_flight',
    'load_policy',
    'occupied_shas',
    'runs',
    'slurm_occupied',
    'workstation_plan',
]

_MB: Final = 1024**2
_GIT: Final = shutil.which('git') or 'git'


@dataclass(frozen=True)
class Policy:
    """The kit defaults; the machine file's ``[retention]`` overrides any key (module docstring)."""

    min_age_hours: float = 6.0
    abandon_days: float = 7.0
    log_max_mb: float = 20.0
    slurm_out_days: float = 7.0
    uv_prune: bool = True
    pressure: float = 0.85
    target: float = 0.70
    collect_files: int = 16
    unit_results: int = 256


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
    keep: tuple[tuple[Path, Path], ...] = ()  # (round stream, kept file): kept before the path goes


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
    """Every ``runs/<sha>`` with the state of its least finished part and its newest mtime.

    Each part of a sha keeps its own ``runs/<sha>/<part>/state.json``; the sha is unrecorded while ANY part
    is. An unreadable state reads as ``{}`` (unrecorded) at the directory's mtime.
    """
    out = []
    for run in _entries(ci / 'runs'):
        read: list[tuple[dict[str, Any], datetime]] = []
        for state in sorted(run.glob('*/state.json')):
            try:
                data = json.loads(state.read_text(encoding='utf-8'))
                read.append(
                    (data if isinstance(data, dict) else {}, datetime.fromtimestamp(state.stat().st_mtime, UTC))
                )
            except (OSError, ValueError):
                read.append(({}, datetime.fromtimestamp(run.lstat().st_mtime, UTC)))
        if not read:
            read = [({}, datetime.fromtimestamp(run.lstat().st_mtime, UTC))]
        data = min(read, key=lambda one: ('record' in one[0], -one[1].timestamp()))[0]
        out.append((run, data, max(when for _, when in read)))
    return out


def _active(tree: Path, now: datetime) -> timedelta:
    """How long since *tree* was last touched: itself, its ``.lab-ci``, or any stream directory in it."""
    lab = tree / '.lab-ci'
    return min(_age(path, now) for path in [tree, *([lab, *_entries(lab)] if lab.is_dir() else [])])


def in_flight(ci: Path, policy: Policy, *, now: datetime, live: Iterable[str], occupied: Iterable[str]) -> set[str]:
    """THE shas in flight (module docstring): live, occupied, or active within ``min_age_hours``."""
    young = timedelta(hours=policy.min_age_hours)
    shas = set(live) | set(occupied) | {path.name for path, _, when in runs(ci) if now - when < young}
    shas |= {art.name.split('.')[0] for art in _entries(ci / 'artifacts') if _age(art, now) < young}
    return shas | {tree.name for tree in _entries(ci / 'trees') if _active(tree, now) < young}


def carry_sources(root: Path, shas: Iterable[str], tips: Iterable[str]) -> set[str]:
    """The runs among *shas* a commit at or on top of any of *tips* would carry from (module docstring).

    A tip's own :func:`~dev_lab.dev.forgecarry.read_by` covers a child's: the child reads the tip's run
    and the tip's nearest, a subset of what the tip reads.
    """
    shas = set(shas)
    return {sha for tip in set(tips) for sha in read_by(root, tip, shas)}


#: The ``~/ci`` directories whose ``<sha>`` entries a Slurm job works under: a test run's tree, a job's runs.
_WORKED_UNDER: Final = ('trees', 'jobs')


def occupied_shas(workdirs: Iterable[str]) -> set[str]:
    """The ``<sha>`` of every ``ci/trees/<sha>`` or ``ci/jobs/<sha>`` a Slurm job's workdir is or lies under."""
    shas = set()
    for workdir in workdirs:
        parts = workdir.split('/')  # Slurm's paths are POSIX
        shas |= {
            parts[i + 2]
            for i in range(len(parts) - 2)
            if parts[i] == 'ci' and parts[i + 1] in _WORKED_UNDER and parts[i + 2]
        }
    return shas


def slurm_occupied(run: Callable[..., Any] = _door.run) -> set[str] | None:
    """:func:`occupied_shas` of this account's queued and running jobs; ``None`` when the queue is unreadable."""
    try:
        done = run(list(WORKDIRS_COMMAND), capture_output=True, text=True, encoding='utf-8', errors='replace',
                   check=False, timeout=60)  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return None
    return occupied_shas(parse_workdirs(done.stdout)) if done.returncode == 0 else None


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
            if now - when >= timedelta(days=policy.abandon_days):
                doomed.append(Doomed(path, 'run-abandoned'))
        elif state.get('repo') != repo:
            continue  # another repo's serve judges its own runs
        elif sha in sources:
            harder.append((when, sha))
        else:
            doomed.append(Doomed(path, 'run-not-a-carry-source'))
    if occupied is not None:
        unrecorded = {path.name: state for path, state, _ in states if 'record' not in state}
        doomed += [
            Doomed(tree, 'tree-not-in-flight', keep=_kept_streams(ci, tree.name, unrecorded.get(tree.name)))
            for tree in _entries(ci / 'trees')
            if tree.name not in flying
        ]
    doomed += _retired_kept_streams(ci, states)
    if occupied is not None:
        doomed += _dead_artifacts(ci / 'artifacts', flying)
    doomed += _unreferenced_builds(ci, _needed_builds(ci, states, flying, occupied), now, policy)
    doomed += _collect_over_budget(ci / 'collect', policy, now)
    doomed += [Doomed(p, 'pack-not-in-flight') for p in _entries(ci / 'packs') if p.stem not in flying]
    doomed.append(Doomed(ci / 'cache.git', 'shared-cache-retired'))
    doomed += _home_rules(home, policy, now)
    hard = tuple(Doomed(ci / 'runs' / sha, 'quota-pressure') for _, sha in sorted(harder))
    commands = [(_GIT, '--git-dir', str(c), 'worktree', 'prune') for c in _entries(ci / 'cache') if c.is_dir()]
    commands += _uv(policy, ci / 'uv-cache')
    doomed = [d for d in doomed if d.path.exists() or d.path.is_symlink()]
    return Plan(tuple(doomed), hard, tuple(commands))


def _dead_artifacts(store: Path, flying: set[str]) -> list[Doomed]:
    """Every artifact whose sha is not in flight, except the newest built one (module docstring).

    A half-written ``.part`` is never the newest built; a live builder's is young, so in flight.
    """
    files = sorted((e for e in _entries(store) if e.is_file()), key=lambda e: e.stat().st_mtime)
    newest = [e for e in files if not e.name.endswith('.part')][-1:]
    return [Doomed(e, 'artifact-not-live') for e in files if e not in newest and e.name.split('.')[0] not in flying]


def _current_tag(state: Mapping[str, Any] | None) -> str:
    return str(((state or {}).get('current') or {}).get('tag', ''))


def _kept_streams(ci: Path, sha: str, state: Mapping[str, Any] | None) -> tuple[tuple[Path, Path], ...]:
    """An unrecorded run's round stream and the one file :func:`lab_commons.hpc.records.stream_sources` keeps."""
    if not (tag := _current_tag(state)):
        return ()
    live, kept = (ci / source.split('/ci/', 1)[1] for source in stream_sources(sha, tag))
    return ((live, kept),)


def _retired_kept_streams(ci: Path, states: list[tuple[Path, dict[str, Any], datetime]]) -> list[Doomed]:
    """Each run kept in the retired ``streams/<tag>.txt`` shape, its current round upgraded into one file.

    Upgraded only while the run is unrecorded and its tree is gone -- the one case a reader opens it; a tree
    still present streams the round itself and is kept from (:func:`_kept_streams`) when it goes.
    """
    doomed = []
    for path, state, _ in states:
        old = path / 'streams'
        if not old.is_dir():
            continue
        tag = _current_tag(state)
        live = not (ci / 'trees' / path.name).exists() and 'record' not in state and tag
        keep = ((old / f'{tag}.txt', _kept_streams(ci, path.name, state)[0][1]),) if live else ()
        doomed.append(Doomed(old, 'streams-upgraded', keep=keep))
    return doomed


def _sourced_builds(tree: Path) -> object:
    """The ``{env, native}`` keys a job-file job in *tree* sources from ``.lab-ci/env.sh``; ``None`` unread."""
    try:
        text = (tree / '.lab-ci' / 'env.sh').read_text(encoding='utf-8')
    except OSError:
        return None
    env, native = re.search(r'/ci/envs/([^/"\s:]+)', text), re.search(r'/ci/native/([^/"\s:]+)', text)
    return {'env': env.group(1), 'native': native.group(1) if native else None} if env else None


def _needed_builds(
    ci: Path, states: list[tuple[Path, dict[str, Any], datetime]], flying: set[str], occupied: Iterable[str] | None
) -> list[object]:
    """The ``builds`` of each in-flight run and each repo's newest recorded run naming any; ``None`` unread.

    A job in a tree no run state names reads the ``env.sh`` it sources; an unreadable queue reads nothing.
    """
    by_sha = {path.name: state for path, state, _ in states}
    needed = [by_sha[sha].get('builds') for sha in sorted(flying) if sha in by_sha]
    needed += [_sourced_builds(ci / 'trees' / sha) for sha in sorted(occupied or ()) if sha not in by_sha]
    needed += [None] if occupied is None else []
    newest: dict[str, tuple[datetime, object]] = {}
    for _, state, when in states:
        repo = str(state.get('repo', ''))
        if (
            'record' in state
            and isinstance(state.get('builds'), dict)
            and (repo not in newest or when >= newest[repo][0])
        ):
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


def _collect_over_budget(store: Path, policy: Policy, now: datetime) -> list[Doomed]:
    """Every entry of ``collect/`` but its newest ``collect_files`` key files, once past ``min_age_hours``."""
    keys = sorted((e for e in _entries(store) if e.suffix == '.json' and e.is_file()), key=lambda e: e.stat().st_mtime)
    kept = set(keys[-policy.collect_files :] if policy.collect_files > 0 else [])
    young = timedelta(hours=policy.min_age_hours)
    return [Doomed(e, 'collect-over-budget') for e in _entries(store) if e not in kept and _age(e, now) >= young]


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
