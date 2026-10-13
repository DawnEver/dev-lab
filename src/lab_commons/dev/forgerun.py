"""A LONG PRODUCER IS A RESUMABLE TICK -- the cluster part, advanced one step per ``forge serve`` call.

WHY A TICK AND NOT A PROCESS. A cluster run takes hours; a login node's cron tick, a reaper or a
reboot does not let one process live that long. A blocking producer orphaned its Slurm jobs, its claim
aged out, and another account re-claimed the commit into a duplicate run (design 2026-10-11, gap 1).
So each ``forge serve`` invocation ADVANCES ON-DISK STATE and returns:

    claimed -> submitted (Slurm job ids) -> gathered (the run record) -> published -> released

DECLARED OUTPUTS SHIP WITH THE RECORD. The outputs a part declares (``[tool.lab_commons.hpc] outputs``,
captured in the run when it is claimed -- declared at REQUEST time) are packed from the run's work
tree and put in the artefact store (:mod:`lab_commons.dev.artefacts`) after the record is gathered and
before it is posted; the record's ``artefacts`` manifest names them. A declared output that is missing
releases the part as an error and alarms. Each serve tick on a cluster also cleans the stores
(:func:`lab_commons.dev.forgeship.tidy`) of this host's own account's runs: one of several writers.

One file per run, keyed by repo + sha + platform + scope, under ``forge-runs/`` beside the machine
file (:func:`directory`) -- in the account's home, so any login host of that account sees it.

SLURM IS THE TRUTH FOR JOB STATE; THE FILE ONLY SAYS HOW FAR THIS SIDE GOT. ``submitted`` is decided
by the run state ``hpc`` keeps on the cluster (``~/ci/runs/<sha>/state.json``), and gathering asks
``sacct`` (:func:`lab_commons.hpc.run.gather_run`). A crash between ticks therefore resumes; it never
resubmits: a ``claimed`` run whose jobs exist (by ``squeue`` job name) but whose run state was never
written is an ORPHAN -- it raises an alarm and waits for a human to ``scancel`` it, because submitting
again would double the run.

ONLY THE OWNER RENEWS. Every tick re-claims the run's commit through the forge's race
(:func:`lab_commons.dev.forgeclaim.claim`) before advancing it. A claim another owner now holds stands
this run DOWN (its file is dropped, nothing is produced, an alarm says so); a live claim held by
ANOTHER LOGIN HOST OF THIS ACCOUNT is left alone entirely -- ONE HOST PER ACCOUNT, and this is its
guard, since ``flock`` on GPFS does not lock across hosts.

PROGRESS TRAVELS ON THE CLAIM. Whenever where the run stands changes -- ``building``, ``queued 0/93``,
``running 40/93 done 12/93``, ``publishing`` -- the owner re-posts its pending claim with that progress
(:class:`lab_commons.dev.forgeclaim.Claim`), so any machine with a forge credential sees it; the final
status links the run record. A run whose REF MOVED ON is SUPERSEDED (:func:`supersede`): its Slurm jobs
are cancelled and its claim released as ``superseded by <sha>``, so nothing finishes for nothing -- unless
the new tip is reach-equivalent (:mod:`lab_commons.dev.forgecarry`): then the run finishes, and its
record is posted on the tip too, as a part naming the sha it was judged at.

THE FILE IS SCHEMA-VERSIONED (:data:`SCHEMA`). A tool upgraded under a live run never reads a run
of another schema: :func:`live` refuses with the remedy (:class:`ForeignSchema`), so the run is
finished by the tool that started it or abandoned on purpose -- never misread.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import shlex
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path
from typing import Final, Protocol

from lab_commons.compute.model import Supply
from lab_commons.config import config_path
from lab_commons.dev import forgeship
from lab_commons.dev.artefacts import MissingOutput, run_id
from lab_commons.dev.forgealarm import LEASE, RUN, Alarm
from lab_commons.dev.forgecarry import equivalent, publish
from lab_commons.dev.forgeclaim import DONE, MINE, Claim, Work, assess, claim, forge_now
from lab_commons.dev.forgeroute import pyproject_at, route
from lab_commons.dev.forgeschedule import tip_of
from lab_commons.dev.forgestatus import status_history, status_post
from lab_commons.dev.forgework import Client, ForgeCallFailed
from lab_commons.dev.platformparts import PartRefusal, part_context
from lab_commons.dev.producer import ProducerExit, release_reason
from lab_commons.hpc.records import read_record, write_record
from lab_commons.hpc.run import NotSubmitted
from lab_commons.hpc.shell import FULL

__all__ = [
    'CLAIMED_PHASE',
    'GATHERED',
    'PUBLISHED',
    'SCHEMA',
    'SUBMITTED',
    'Cluster',
    'ForeignSchema',
    'Run',
    'Standing',
    'advance',
    'directory',
    'drop',
    'live',
    'save',
    'start',
    'supersede',
    'supersede_moved',
]

#: The state file's schema. Bump it whenever a field changes meaning; a live run of another is refused.
SCHEMA: Final = 1

#: The phases a run passes through, in order; released is the file's removal.
CLAIMED_PHASE: Final = 'claimed'
SUBMITTED: Final = 'submitted'
GATHERED: Final = 'gathered'
PUBLISHED: Final = 'published'

#: What a tick may do with a run (:func:`_hold`).
_ADVANCE: Final = 'advance'
_WAIT: Final = 'wait'
_GONE: Final = 'gone'

#: A status description is short on every forge.
_DESCRIPTION_MAX: Final = 140


class ForeignSchema(RuntimeError):
    """A live run file of another schema; the message names it and the remedy."""


@dataclass(frozen=True)
class Standing:
    """What this account can take on, read locally on the login node: its supply, the last day's use, facts."""

    supply: Supply
    usage: dict[str, float] = dataclasses.field(default_factory=dict)
    facts: dict[str, object] = dataclasses.field(default_factory=dict)


class Cluster(Protocol):
    """What a run needs from Slurm, through this login node's own shell (:class:`lab_commons.dev.forgeserve`)."""

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
        """Where *run*'s jobs stand, one short phrase (:func:`lab_commons.dev.forgeslurm.progress_text`)."""

    def cancel(self, run: Run) -> list[str]:
        """``scancel`` every job of *run*; the ids cancelled."""

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
    platform: str = 'linux'
    scope: str = FULL
    outputs: tuple[str, ...] = ()  # declared at request time; only these are packed
    artefact: str = ''  # the artefact run id, fixed before the first put so a resumed tick re-puts the same key
    schema: int = SCHEMA
    #: The progress last posted on the claim; a change is posted, a repeat is not.
    progress: str = ''

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
    partial = target.with_suffix('.tmp')
    partial.write_text(json.dumps(asdict(run), indent=2), encoding='utf-8')
    partial.replace(target)
    return target


def drop(run: Run) -> None:
    """Release *run*: its file goes; nothing about it is kept here."""
    _path(run).unlink(missing_ok=True)


def live(repo_url: str) -> tuple[Run, ...]:
    """Every run of *repo_url* in flight here; a file of another schema is refused (:class:`ForeignSchema`)."""
    found = []
    for path in sorted(directory().glob('*.json')) if directory().is_dir() else ():
        raw = json.loads(path.read_text(encoding='utf-8'))
        if raw.get('schema') != SCHEMA:
            msg = (
                f'{path} is a live run of state schema {raw.get("schema")!r}; this tool reads schema {SCHEMA}. '
                'Finish it with the tool version that started it, or -- once `squeue --me` shows none of '
                'its jobs -- delete the file; the next tick claims the commit afresh'
            )
            raise ForeignSchema(msg)
        if raw['repo_url'] == repo_url:
            found.append(Run(**{**raw, 'job_ids': tuple(raw['job_ids']), 'outputs': tuple(raw.get('outputs', ()))}))
    return tuple(found)


def start(work: Work, owner: Claim) -> Run:
    """The run of a part just claimed: phase ``claimed``, saved before anything is submitted."""
    if work.cluster is None:
        msg = f'{work.sha[:12]}: a cluster run needs a claimed cluster part'
        raise ValueError(msg)
    run = Run(
        repo_url=work.cluster.repo_url,
        sha=work.sha,
        ref=work.ref,
        collect=work.cluster.collect,
        output=str(work.cluster.output),
        owner=owner.description(),
        outputs=work.cluster.outputs,
    )
    save(run)
    return run


def advance(
    root: Path,
    run: Run,
    *,
    client: Client,
    me: Claim,
    lease: timedelta,
    cluster: Cluster,
    say: Callable[[str], None],
    alarm: Callable[[Alarm], None],
) -> Run | None:
    """Take *run* as far as it goes without waiting; the run as left, or ``None`` once released or stood down."""
    tag = f'[{run.platform}] {run.sha[:12]}'
    held, run = _hold(run, client=client, me=me, lease=lease, say=say, alarm=alarm, tag=tag)
    if held != _ADVANCE:
        return run if held == _WAIT else None
    try:  # a build that submitted nothing, like an inconclusive record, ran no test: released, never red
        if run.phase == CLAIMED_PHASE:
            ids = cluster.submitted(run)
            if not ids:
                orphans = cluster.orphans(run)
                if orphans:
                    alarm(_orphaned(run, orphans))
                    say(f'{tag}: orphaned jobs {" ".join(orphans)} -- not resubmitted')
                    return run
                run = _report(client, run, 'building', lease, say)
                ids = cluster.submit(run)
                say(f'{tag}: submitted jobs {" ".join(ids)}')
            run = _step(run, phase=SUBMITTED, job_ids=tuple(ids))
        if run.phase == SUBMITTED:
            record = cluster.gather(run)
            if record is None:
                # hpc submits retry rounds inside a gather: re-read every round's job id each tick (Ada,
                # 2026-10-12: the submit's r0 id was still shown while r2 ran).
                run = _step(run, job_ids=tuple(cluster.submitted(run)) or run.job_ids)
                say(f'{tag}: running (job {run.job_ids[-1]}, round {len(run.job_ids)})')
                return _report(client, run, cluster.progress(run), lease, say)
            run = _step(run, phase=GATHERED, record=str(record))
            run = _report(client, run, 'publishing', lease, say)
        if run.phase == GATHERED:
            run = _ship(root, run, client=client, cluster=cluster, say=say, tag=tag)
            say(publish(root, Path(run.record), client=client, ref=run.ref, sha=run.sha, platform=run.platform))
            run = _step(run, phase=PUBLISHED)
    except (MissingOutput, NotSubmitted, PartRefusal) as why:
        say(f'{tag}: {why}')
        _release(client, run, _release_reason(run, why, alarm), say)
        drop(run)
        return None
    record = read_record(Path(run.record))
    for one in route(client, record, pyproject_at(root, run.sha)):
        say(f'{tag}: routed {one.area} {one.action}' + (f' #{one.number}' if one.number else ''))
    drop(run)
    say(f'{tag}: published and released')
    return None


def _report(client: Client, run: Run, progress: str, lease: timedelta, say: Callable[[str], None]) -> Run:
    """Re-post the owner's claim carrying *progress* when it changed; the run with it recorded."""
    if not progress or progress == run.progress:
        return run
    renewed = dataclasses.replace(run.claim, until=forge_now(client) + lease, progress=progress)
    context = part_context(run.platform)
    try:
        status_post(client, run.sha, context=context, state='pending', description=renewed.description())
    except ForgeCallFailed as failed:  # a missed progress post is not a dead run; the next tick posts it
        say(f'[{run.platform}] {run.sha[:12]}: could not post progress: {failed}')
        return run
    return _step(run, owner=dataclasses.replace(renewed, progress='').description(), progress=progress)


def supersede(run: Run, tip: str, *, client: Client, cluster: Cluster, say: Callable[[str], None]) -> None:
    """*run*'s ref moved on to *tip*: cancel its jobs, release its claim ``superseded by <tip>``, drop it.

    The run cache is untouched, so a newer commit whose tree was already judged still cites it.
    """
    cancelled = cluster.cancel(run)
    _release(client, run, f'superseded by {tip[:12]}', say)
    drop(run)
    say(f'[{run.platform}] {run.sha[:12]}: superseded by {tip[:12]}; cancelled {" ".join(cancelled) or "nothing"}')


def supersede_moved(
    root: Path, runs: list[Run], *, client: Client, cluster: Cluster, say: Callable[[str], None]
) -> list[Run]:
    """:func:`supersede` every run whose ref's origin tip moved on to a tip it is not equivalent to; the runs kept."""
    kept = []
    for run in runs:
        tip = tip_of(root, run.ref)
        if tip and tip != run.sha and not equivalent(root, run.sha, tip):
            supersede(run, tip, client=client, cluster=cluster, say=say)
        else:
            kept.append(run)
    return kept


def _release_reason(run: Run, why: Exception, alarm: Callable[[Alarm], None]) -> str:
    """Why a run that ran no judged test is released: a missing declared output alarms and fails the run."""
    if isinstance(why, MissingOutput):  # a declared output is part of the request: its absence fails the run
        alarm(Alarm(RUN, run.repo_url, f'the run of {run.sha[:12]} lacks a declared output', str(why)))
        return f'declared outputs missing: {why}'[:_DESCRIPTION_MAX]
    log = next((word for word in str(why).split() if word.startswith('log=')), '')  # the build log, named
    return f'{release_reason(ProducerExit.INCONCLUSIVE)} {log}'.strip()


def _ship(root: Path, run: Run, *, client: Client, cluster: Cluster, say: Callable[[str], None], tag: str) -> Run:
    """Store the declared outputs and name them in the record's ``artefacts``; idempotent per run."""
    record = read_record(Path(run.record))
    if not run.outputs or 'artefacts' in record:
        return run
    if not run.artefact:
        account = run.claim.hpc.rpartition('/')[2]  # the claim owner's cluster account names the writer
        run = _step(run, artefact=run_id(run.sha, run.platform, account, forge_now(client)))
    ref = forgeship.store_outputs(
        root, client, cluster.tree(run), run.outputs, ident=run.artefact, workdir=Path(run.output)
    )
    run = _step(run, record=str(write_record({**record, 'artefacts': [ref.manifest()]}, Path(run.record).parent)))
    say(f'{tag}: {len(run.outputs)} declared output(s) stored as {ref.backend}:{ref.key} ({ref.bytes} bytes)')
    return run


def _step(run: Run, **changes: object) -> Run:
    moved = dataclasses.replace(run, **changes)
    save(moved)
    return moved


def _hold(
    run: Run,
    *,
    client: Client,
    me: Claim,
    lease: timedelta,
    say: Callable[[str], None],
    alarm: Callable[[Alarm], None],
    tag: str,
) -> tuple[str, Run]:
    """Whether this host advances *run* (renewed), waits (leaves it), or it is gone (released or stood down).

    A live claim of its own is renewed only once a third of the lease has passed, so a five-minute cron
    does not post a status every five minutes.
    """
    now = forge_now(client)
    owner = run.claim
    state, holder = assess(status_history(client, run.sha), run.platform, me=owner, now=now)
    if state == DONE:
        say(f'{tag}: the part is already settled on the forge -- released')
        drop(run)
        return _GONE, run
    foreign_host = not owner.same_owner(me) and owner.hpc == me.hpc
    if foreign_host and state == MINE:  # another login host of this account holds it live: one host per account
        say(f'{tag}: owned live by {owner.machine} under {owner.hpc} -- this host does nothing')
        return _WAIT, run
    if state == MINE and owner.same_owner(me) and holder is not None and holder.until - now > lease * 2 / 3:
        return _ADVANCE, run
    renewal = dataclasses.replace(me, until=now + lease, progress=run.progress)  # a renewal keeps showing progress
    try:
        held = claim(client, Work(run.ref, run.sha, run.platform, state), renewal)
    except ForgeCallFailed as failed:
        alarm(Alarm(LEASE, run.repo_url, f'cannot renew the claim on {run.sha[:12]}', str(failed)))
        say(f'{tag}: could not renew its claim: {failed}')
        return _WAIT, run
    if held.state != MINE:
        holder = held.holder or renewal
        alarm(_lost(run, holder))
        say(f'{tag}: lost the race to {holder.login}@{holder.machine} -- standing down')
        drop(run)
        return _GONE, run
    if not owner.same_owner(me):
        say(f'{tag}: adopted from {owner.machine} (its lease lapsed); Slurm says where the run is')
        run = dataclasses.replace(run, owner=renewal.description())
        save(run)
    return _ADVANCE, run


def _release(client: Client, run: Run, reason: str, say: Callable[[str], None]) -> None:
    try:
        status_post(client, run.sha, context=part_context(run.platform), state='error', description=reason)
    except ForgeCallFailed as failed:
        say(f'[{run.platform}] could not release: {failed}')


def _lost(run: Run, holder: Claim) -> Alarm:
    return Alarm(
        LEASE,
        run.repo_url,
        f'lost the claim on {run.sha[:12]} to {holder.login}@{holder.machine}',
        f'{holder.description()} holds {part_context(run.platform)} now; this run stood down. Its Slurm jobs '
        f'({" ".join(run.job_ids) or "none submitted"}) keep running unless cancelled: scancel them if the '
        'new owner re-runs the commit.',
    )


def _orphaned(run: Run, jobs: list[str]) -> Alarm:
    return Alarm(
        LEASE,
        run.repo_url,
        f'orphaned Slurm jobs for {run.sha[:12]}',
        f'jobs {shlex.join(jobs)} run under this account but no run state was recorded, so the tick will not '
        'resubmit. Remedy: scancel them; the next tick submits the run afresh.',
    )
