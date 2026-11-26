"""A CLUSTER RUN'S STATE -- the on-disk run file, its schema, and what a run needs from Slurm.

The tick that advances a run is :mod:`dev_lab.dev.forgerun`; this module is what the tick, the
serve loop and the Slurm side share: the :class:`Run` record, its phases, the :class:`Cluster`
protocol, and the one-file-per-run store under ``forge-runs/`` beside the machine file
(:func:`directory`) -- keyed by repo + sha + platform + scope, in the account's home, so any login
host of that account sees it.

THE FILE IS SCHEMA-VERSIONED (:data:`SCHEMA`). A file of any other schema is refused by name with its
remedy (:class:`ForeignSchema`) -- finish the run with the tool that started it, or delete the file once its
jobs are gone -- and a tick hears that refusal for the one file and reads the rest (Ada, 2026-10-17: one
refused file stopped every tick of four accounts). No older schema is read: FORMATS-MIGRATE-ONCE.

A KEY A RENAME RETIRED (:data:`RETIRED_KEYS`) is refused the same way, naming the file, the key and the one-time
door that rewrites it (:data:`MIGRATE`, :func:`migrate`); a key no schema declares is refused, never a crash
(Ada, 2026-11-25: one record still keyed by the British spelling stopped every serve tick of the family).
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import re
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final, Protocol

from lab_commons.compute.durable import durable_write
from lab_commons.compute.model import Supply
from lab_commons.config import config_path
from lab_commons.hpc.needsets import BASE
from lab_commons.hpc.shell import FULL

from dev_lab.dev.forgeclaim import Claim

__all__ = [
    'CLAIMED_PHASE',
    'GATHERED',
    'MIGRATE',
    'PUBLISHED',
    'RETIRED_KEYS',
    'SCHEMA',
    'SUBMITTED',
    'SUBMITTING',
    'Cluster',
    'Draining',
    'ForeignSchema',
    'Killed',
    'RetiredKeys',
    'Run',
    'Stalled',
    'Standing',
    'Started',
    'Unrecorded',
    'directory',
    'drop',
    'held',
    'held_names',
    'live',
    'main',
    'migrate',
    'name_of',
    'save',
    'submit_lock',
]

#: The state file's schema. Bump it whenever a field changes meaning; a live run of another is refused.
#: 2: the ``submitting`` phase (intent before sbatch); jobs named ``run-<sha12>-<part>`` (were ``run-<sha12>``).
SCHEMA: Final = 2
#: Run-record keys a rename retired -> their successor (US spelling, user ruling 2026-11-24). Refused, never read.
RETIRED_KEYS: Final = {'artefact': 'artifact'}  # spelling-ignore-line
#: The one-time door that rewrites every retired key here (:func:`migrate`); without ``--apply`` it only lists.
MIGRATE: Final = 'python -m dev_lab.dev.forgerunstate migrate --apply'

#: The phases a run passes through, in order; released is the file's removal.
CLAIMED_PHASE: Final = 'claimed'
SUBMITTING: Final = 'submitting'
SUBMITTED: Final = 'submitted'
GATHERED: Final = 'gathered'
PUBLISHED: Final = 'published'


class ForeignSchema(RuntimeError):
    """A live run file of another schema; the message names it and the remedy."""


class RetiredKeys(ForeignSchema):
    """A live run file still carrying a retired key; the message names the file, the key and :data:`MIGRATE`."""


class Unrecorded(RuntimeError):
    """A run's jobs ended and wrote no record: no later tick gets one, so the run SETTLES (:func:`_settle`)."""


@dataclass(frozen=True)
class Standing:
    """What this account can take on, read locally on the login node: its supply, the last day's use, facts.

    *ceiling_gb* is the most memory one task may ask of any grant (:func:`lab_commons.hpc.plan.grantable_gb`;
    ``None``: no ceiling), the bound a cluster part's demand is held to.
    """

    supply: Supply
    usage: dict[str, float] = dataclasses.field(default_factory=dict)
    facts: dict[str, object] = dataclasses.field(default_factory=dict)
    ceiling_gb: float | None = None


@dataclass(frozen=True)
class Started:
    """One STARTED array task: its id (``7683032_12``), its start and its limit, seconds on the cluster's clock.

    *limit_s* is the packer's estimate of its items times ``policy.safety`` -- the figure its ``--time`` was cut from.
    """

    job_id: str
    started_at: float
    limit_s: float


@dataclass(frozen=True)
class Draining:
    """A run's started tasks as the cluster read them, and the cluster's clock *now* at that read."""

    now: float
    tasks: tuple[Started, ...]


@dataclass(frozen=True)
class Killed:
    """One job Slurm killed (:data:`dev_lab.dev.slurmkilled.KILLED`): its ask and use, in MB and seconds."""

    job: str
    state: str
    asked_mb: int
    used_mb: int
    asked_s: int
    used_s: int

    def text(self) -> str:
        """``7_0 OUT_OF_MEMORY 4199/4096 MB 190/3600 s`` -- used over asked."""
        return f'{self.job} {self.state} {self.used_mb}/{self.asked_mb} MB {self.used_s}/{self.asked_s} s'


@dataclass(frozen=True)
class Stalled:
    """One RUNNING forge task past its stall bound (:meth:`dev_lab.dev.forgeslurm.SlurmCluster.stalled`), cancelled.

    *last* is the test its stream last STARTED (``''`` when none had), *why* the bound it passed.
    """

    job_id: str
    name: str
    sha: str
    last: str
    why: str

    def text(self) -> str:
        """``7811859_0 9be9382e8d6e in tests/w.py::t: <why>`` -- what an alarm names."""
        return f'{self.job_id} {self.sha[:12]} in {self.last or "no test yet"}: {self.why}'


class Cluster(Protocol):
    """What a run needs from Slurm, through this login node's own shell (:class:`dev_lab.dev.forgeserve`)."""

    def submitted(self, run: Run) -> list[str]:
        """The job ids of the run ``hpc`` recorded on the cluster for *run*'s sha, ``[]`` when none."""

    def orphans(self, run: Run) -> list[str]:
        """Job ids of *run*'s sha that Slurm holds although no run state was written (squeue by job name)."""

    def submit(self, run: Run) -> list[str]:
        """Submit round 0 of *run* and return its job ids; returns once queued."""

    def gather(self, run: Run) -> Path | None:
        """One short gather: the record written into ``run.output``, or ``None`` while Slurm still runs it."""

    def killed(self, run: Run, record: Path | None = None) -> tuple[Killed, ...]:
        """*run*'s jobs Slurm killed for memory or time with ask and use; their asks learned, also into *record*."""

    def strays(self, held: Callable[[], set[str]]) -> list[str]:
        """Cancel every forge job (``run-<sha12>...``) whose name *held* does not return; the ids cancelled."""

    def stalled(self) -> list[Stalled]:
        """Cancel every RUNNING forge task of this account past its stall bound, whatever its run; those cancelled."""

    def tree(self, run: Run) -> Path:
        """The run's work tree as this login node sees it -- where its declared outputs are globbed."""

    def progress(self, run: Run) -> str:
        """Where *run*'s jobs stand, one short phrase (:func:`dev_lab.dev.forgeslurm.progress_text`)."""

    def rounds(self, run: Run) -> list[dict[str, Any]]:
        """*run*'s rounds as its cluster state holds them; a folded one carries ``lost`` (what it failed or lost)."""

    def cancel(self, run: Run) -> list[str]:
        """``scancel`` every job of *run*, started or not; the ids cancelled. Never for supersession."""

    def withdraw(self, run: Run) -> list[str]:
        """Withdraw *run*'s NOT-YET-STARTED tasks; the job ids still started (``[]``: nothing left running)."""

    def started_tasks(self, run: Run) -> Draining:
        """*run*'s STARTED tasks, each with its start and learned limit, on the cluster's clock."""

    def cancel_tasks(self, run: Run, ids: list[str]) -> list[str]:
        """``scancel`` these tasks of *run* only -- a superseded run's task past its deadline; the ids cancelled."""

    def standing(self) -> Standing:
        """The account's supply, core-hours used per run in the last day, and the partitions and quota."""


@dataclass(frozen=True)
class Run:
    """One cluster part in flight, as this side last left it."""

    repo_url: str
    sha: str
    ref: str
    collect: str
    output: str
    owner: str  # the owning claim's description; only its machine/login/hpc identify the owner
    phase: str = CLAIMED_PHASE
    job_ids: tuple[str, ...] = ()
    record: str = ''
    platform: str = BASE  # the part (its need-set) this run produces
    scope: str = FULL
    outputs: tuple[str, ...] = ()  # declared at request time; only these are packed
    artifact: str = ''  # the artifact run id, fixed before the first put so a resumed tick re-puts the same key
    schema: int = SCHEMA
    #: The progress last posted on the claim; a change is posted, a repeat is not.
    progress: str = ''
    #: Slurm job names this run's jobs may bear besides :func:`lab_commons.hpc.run.job_name` -- an
    #: schema-1 run's, sbatched by a tool that named jobs otherwise; empty for every run this tool starts.
    job_aliases: tuple[str, ...] = ()
    #: When the run was first found superseded, on the cluster's clock; ``0.0`` while it is not.
    superseded_at: float = 0.0
    #: How many folded rounds this run has published to the forge (:mod:`dev_lab.dev.forgerunshow`).
    rounds_posted: int = 0

    @property
    def claim(self) -> Claim:
        """The owner, as a claim."""
        found = Claim.parse(self.owner)
        if found is None:
            msg = f'run {self.sha[:12]} names no owner claim: {self.owner!r}'
            raise ValueError(msg)
        return found


def directory() -> Path:
    """``forge-runs/`` beside the machine file -- in the account's home, seen by every login host of it."""
    return config_path().parent / 'forge-runs'


def _path(run: Run) -> Path:
    repo = hashlib.sha256(run.repo_url.encode('utf-8')).hexdigest()[:12]
    return directory() / f'{repo}-{run.sha}-{run.platform}-{run.scope}.json'


def name_of(run: Run) -> str:
    """*run*'s file name without its suffix: how a detached submit names the run it takes (:mod:`forgesubmit`)."""
    return _path(run).stem


def submit_lock(run: Run) -> Path:
    """The lock a detached submit of *run* holds, beside its file; not a ``*.json``, so no reader takes it for a run."""
    return _path(run).with_suffix('.submit')


def save(run: Run) -> Path:
    """Write *run* (atomically: a crash mid-write never leaves half a state)."""
    target = _path(run)
    target.parent.mkdir(parents=True, exist_ok=True)
    return durable_write(target, json.dumps(asdict(run), indent=2).encode('utf-8'))


#: A run file's name: ``<repo12>-<sha>-<part>-<scope>.json`` (:func:`_path`).
_FILE: Final = re.compile(r'[0-9a-f]{12}-(?P<sha>[0-9a-f]{40})-(?P<part>.+)-[^-]+\.json')


def held_names() -> set[str]:
    """The Slurm job names every run file here holds, of ANY repo or schema: ``run-<sha12>-<part>`` and ``run-<sha12>``.

    Read from the file NAMES, so a file this tool cannot parse still holds its jobs; a forge job of no name here
    has no run left to gather it (:meth:`dev_lab.dev.forgeslurm.SlurmCluster.strays`).
    """
    names: set[str] = set()
    for path in directory().glob('*.json') if directory().is_dir() else ():
        if found := _FILE.fullmatch(path.name):
            names |= {f'run-{found["sha"][:12]}-{found["part"]}', f'run-{found["sha"][:12]}'}
    return names


def touch(run: Run) -> None:
    """Mark *run* advanced now: its file's mtime is when a tick last reached it (:func:`live`'s order).

    The mark is strictly after every other run's: a coarse filesystem clock (Linux stamps mtimes per tick, not per
    nanosecond) gave two touches in one tick EQUAL mtimes, the name broke the tie, and a run reached a moment ago
    sorted first again (measured 2026-11-20, CI).
    """
    path = _path(run)
    if not path.exists():
        return
    others = [one.stat().st_mtime_ns for one in directory().glob('*.json') if one != path]
    stamp = max([time.time_ns(), *(newest + 1 for newest in others)])
    os.utime(path, ns=(stamp, stamp))


def drop(run: Run) -> None:
    """Release *run*: its file goes; nothing about it is kept here."""
    _path(run).unlink(missing_ok=True)


def held(run: Run) -> bool:
    """Whether *run* is still in flight here: its file stands. A settled or released run's is gone (:func:`drop`)."""
    return _path(run).exists()


def _read(path: Path) -> Run:
    """*path*'s run at :data:`SCHEMA`; :class:`ForeignSchema` for any other."""
    raw = json.loads(path.read_text(encoding='utf-8'))
    stored = raw.get('schema')
    if stored != SCHEMA:
        msg = (
            f'{path} is a live run of state schema {stored!r}; this tool reads schema {SCHEMA}. '
            'Finish it with the tool version that started it, or -- once `squeue --me` shows none of '
            'its jobs -- delete the file; the next tick claims the commit afresh'
        )
        raise ForeignSchema(msg)
    if retired := sorted(set(raw) & set(RETIRED_KEYS)):
        keys = ', '.join(f'{key!r} (now {RETIRED_KEYS[key]!r})' for key in retired)
        msg = f'{path} carries retired key(s) {keys}; migrate the run files once: {MIGRATE}'
        raise RetiredKeys(msg)
    if unknown := sorted(set(raw) - {field.name for field in dataclasses.fields(Run)}):
        msg = (
            f'{path} carries key(s) {unknown} schema {SCHEMA} does not declare. Finish it with the tool version '
            'that wrote it, or -- once `squeue --me` shows none of its jobs -- delete the file'
        )
        raise ForeignSchema(msg)
    return Run(**{
        **raw,
        'job_ids': tuple(raw['job_ids']),
        'outputs': tuple(raw.get('outputs', ())),
        'job_aliases': tuple(raw.get('job_aliases', ())),
    })  # fmt: skip


def live(repo_url: str, *, refused: Callable[[str], None] | None = None) -> tuple[Run, ...]:
    """Every run of *repo_url* in flight here, least recently advanced first (:func:`touch`); any other schema refused.

    A file of an unknown schema raises :class:`ForeignSchema` -- or, given *refused*, is skipped and its
    refusal handed to it, so one bad file never stops the other runs.
    """
    found = []
    paths = directory().glob('*.json') if directory().is_dir() else ()
    for path in sorted(paths, key=lambda one: (one.stat().st_mtime_ns, one.name)):
        try:
            run = _read(path)
        except ForeignSchema as why:
            if refused is None:
                raise
            refused(str(why))
            continue
        if run.repo_url == repo_url:
            found.append(run)
    return tuple(found)


def migrate(*, apply: bool) -> tuple[str, ...]:
    """Each run file here carrying a :data:`RETIRED_KEYS` key, named; with *apply*, rewritten to its successor.

    The one-time migration FORMATS-MIGRATE-ONCE owes the rename. A rewrite keeps the file's mtime, so the run
    keeps its place in :func:`live`'s order. A file carrying both a retired key and its successor is named and
    left as it is: which value is the run's is not this door's to guess.
    """
    lines = []
    paths = sorted(directory().glob('*.json')) if directory().is_dir() else ()
    for path in paths:
        raw = json.loads(path.read_text(encoding='utf-8'))
        retired = sorted(set(raw) & set(RETIRED_KEYS))
        if not retired:
            continue
        renames = ', '.join(f'{key} -> {RETIRED_KEYS[key]}' for key in retired)
        if clash := [key for key in retired if RETIRED_KEYS[key] in raw]:
            lines.append(f'{path}: carries both {clash} and their successors; settle it by hand, nothing written')
            continue
        if not apply:
            lines.append(f'{path}: would rename {renames} (add --apply)')
            continue
        stamp = path.stat().st_mtime_ns
        durable_write(path, json.dumps({RETIRED_KEYS.get(key, key): value for key, value in raw.items()}, indent=2)
                      .encode('utf-8'))  # fmt: skip
        os.utime(path, ns=(stamp, stamp))
        lines.append(f'{path}: renamed {renames}')
    return tuple(lines)


def main(argv: list[str] | None = None) -> int:
    """``migrate [--apply]``: list (or rewrite) the run files here still carrying a retired key."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.forgerunstate', description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    once = verbs.add_parser(
        'migrate', help='rename every retired key in the run files here (a dry run without --apply)'
    )
    once.add_argument('--apply', action='store_true', help='rewrite the files; without it nothing is written')
    args = parser.parse_args(argv)
    lines = migrate(apply=args.apply)
    for line in lines:
        sys.stdout.write(f'{line}\n')
    sys.stdout.write(f'{len(lines)} run file(s) with a retired key under {directory()}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
