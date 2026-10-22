"""A CLUSTER RUN'S STATE -- the on-disk run file, its schema, and what a run needs from Slurm.

The tick that advances a run is :mod:`dev_lab.dev.forgerun`; this module is what the tick, the
serve loop and the Slurm side share: the :class:`Run` record, its phases, the :class:`Cluster`
protocol, and the one-file-per-run store under ``forge-runs/`` beside the machine file
(:func:`directory`) -- keyed by repo + sha + platform + scope, in the account's home, so any login
host of that account sees it.

THE FILE IS SCHEMA-VERSIONED (:data:`SCHEMA`). A tool redeployed under a live run ADOPTS it: :func:`live`
upgrades a file of an older schema it knows (:data:`_UPGRADES`) on read -- every field carried, the new
ones derived -- and writes it back at this schema, atomically. Only a schema it does not know is refused
(:class:`ForeignSchema`), and a tick hears that refusal for the one file and reads the rest (Ada,
2026-10-17: a redeploy from schema 1 to 2 under 17 live runs stopped every tick of four accounts).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, Protocol

from lab_commons.compute.durable import durable_write
from lab_commons.compute.model import Supply
from lab_commons.config import config_path
from lab_commons.hpc.needsets import BASE
from lab_commons.hpc.shell import FULL

from dev_lab.dev.forgeclaim import Claim

__all__ = [
    'CLAIMED_PHASE',
    'GATHERED',
    'PUBLISHED',
    'SCHEMA',
    'SUBMITTED',
    'SUBMITTING',
    'Cluster',
    'ForeignSchema',
    'Run',
    'Standing',
    'Unrecorded',
    'directory',
    'drop',
    'live',
    'save',
]

#: The state file's schema. Bump it whenever a field changes meaning; a live run of another is refused.
#: 2: the ``submitting`` phase (intent before sbatch); jobs named ``run-<sha12>-<part>`` (were ``run-<sha12>``).
SCHEMA: Final = 2

#: The phases a run passes through, in order; released is the file's removal.
CLAIMED_PHASE: Final = 'claimed'
SUBMITTING: Final = 'submitting'
SUBMITTED: Final = 'submitted'
GATHERED: Final = 'gathered'
PUBLISHED: Final = 'published'


class ForeignSchema(RuntimeError):
    """A live run file of another schema; the message names it and the remedy."""


class Unrecorded(RuntimeError):
    """A run's jobs ended and wrote no record: no later tick gets one, so the run SETTLES (:func:`_settle`)."""


@dataclass(frozen=True)
class Standing:
    """What this account can take on, read locally on the login node: its supply, the last day's use, facts."""

    supply: Supply
    usage: dict[str, float] = dataclasses.field(default_factory=dict)
    facts: dict[str, object] = dataclasses.field(default_factory=dict)


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

    def tree(self, run: Run) -> Path:
        """The run's work tree as this login node sees it -- where its declared outputs are globbed."""

    def progress(self, run: Run) -> str:
        """Where *run*'s jobs stand, one short phrase (:func:`dev_lab.dev.forgeslurm.progress_text`)."""

    def cancel(self, run: Run) -> list[str]:
        """``scancel`` every job of *run*, started or not; the ids cancelled. Never for supersession."""

    def withdraw(self, run: Run) -> list[str]:
        """Withdraw *run*'s NOT-YET-STARTED tasks; the job ids still started (``[]``: nothing left running)."""

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
    artefact: str = ''  # the artefact run id, fixed before the first put so a resumed tick re-puts the same key
    schema: int = SCHEMA
    #: The progress last posted on the claim; a change is posted, a repeat is not.
    progress: str = ''
    #: Slurm job names this run's jobs may bear besides :func:`lab_commons.hpc.run.job_name` -- an
    #: upgraded run's, sbatched by a tool that named jobs otherwise (:data:`_UPGRADES`).
    job_aliases: tuple[str, ...] = ()

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


def save(run: Run) -> Path:
    """Write *run* (atomically: a crash mid-write never leaves half a state)."""
    target = _path(run)
    target.parent.mkdir(parents=True, exist_ok=True)
    return durable_write(target, json.dumps(asdict(run), indent=2).encode('utf-8'))


def drop(run: Run) -> None:
    """Release *run*: its file goes; nothing about it is kept here."""
    _path(run).unlink(missing_ok=True)


def _from_1(raw: dict[str, object]) -> dict[str, object]:
    """Schema 1 -> 2: same fields and phases; its jobs were sbatched as ``run-<sha12>``, before the part was named."""
    return {**raw, 'schema': 2, 'job_aliases': [f'run-{str(raw["sha"])[:12]}']}


#: Each older schema this tool adopts, and the step that takes it one schema on.
_UPGRADES: Final[dict[int, Callable[[dict[str, object]], dict[str, object]]]] = {1: _from_1}


def _read(path: Path) -> Run:
    """*path*'s run, upgraded to :data:`SCHEMA` and written back when older; :class:`ForeignSchema` if unknown."""
    raw = json.loads(path.read_text(encoding='utf-8'))
    stored = raw.get('schema')
    while raw.get('schema') in _UPGRADES:
        raw = _UPGRADES[raw['schema']](raw)
    if raw.get('schema') != SCHEMA:
        msg = (
            f'{path} is a live run of state schema {stored!r}; this tool reads schema {SCHEMA}. '
            'Finish it with the tool version that started it, or -- once `squeue --me` shows none of '
            'its jobs -- delete the file; the next tick claims the commit afresh'
        )
        raise ForeignSchema(msg)
    run = Run(**{
        **raw,
        'job_ids': tuple(raw['job_ids']),
        'outputs': tuple(raw.get('outputs', ())),
        'job_aliases': tuple(raw.get('job_aliases', ())),
    })  # fmt: skip
    if stored != SCHEMA:
        save(run)
    return run


def live(repo_url: str, *, refused: Callable[[str], None] | None = None) -> tuple[Run, ...]:
    """Every run of *repo_url* in flight here, older schemas adopted (:func:`_read`).

    A file of an unknown schema raises :class:`ForeignSchema` -- or, given *refused*, is skipped and its
    refusal handed to it, so one bad file never stops the other runs.
    """
    found = []
    for path in sorted(directory().glob('*.json')) if directory().is_dir() else ():
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
