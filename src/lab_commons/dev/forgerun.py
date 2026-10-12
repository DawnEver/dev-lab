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
(:func:`tidy`): this host is their single writer.

One file per run, keyed by repo + sha + platform + scope, under ``forge-runs/`` beside the machine
file (:func:`directory`) -- in the account's home, so any login host of that account sees it.

SLURM IS THE TRUTH FOR JOB STATE; THE FILE ONLY SAYS HOW FAR THIS SIDE GOT. ``submitted`` is decided
by the run state ``hpc`` keeps on the cluster (``~/ci/runs/<sha>/state.json``), and gathering asks
``sacct`` (:func:`lab_commons.hpc.run.gather_run`). A crash between ticks therefore resumes; it never
resubmits: a ``claimed`` run whose jobs exist (by ``squeue`` job name) but whose run state was never
written is an ORPHAN -- it raises an alarm and waits for a human to ``scancel`` it, because submitting
again would double the run.

ONLY THE OWNER RENEWS. Every tick re-claims the run's commit through the forge's race
(:func:`lab_commons.dev.forgetick.claim`) before advancing it. A claim another owner now holds stands
this run DOWN (its file is dropped, nothing is produced, an alarm says so); a live claim held by
ANOTHER LOGIN HOST OF THIS ACCOUNT is left alone entirely -- ONE HOST PER ACCOUNT, and this is its
guard, since ``flock`` on GPFS does not lock across hosts.

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

from lab_commons.config import config_path
from lab_commons.dev.artefacts import (
    ARCHIVE,
    ArtefactStore,
    ForgeStore,
    MissingOutput,
    clean,
    collect,
    large_store,
    load_config,
    pack,
    pinned,
    run_id,
    store_for,
)
from lab_commons.dev.forge import forge_from_remote
from lab_commons.dev.forgealarm import LEASE, RUN, Alarm
from lab_commons.dev.forgeroute import pyproject_at, route
from lab_commons.dev.forgestatus import status_history, status_post
from lab_commons.dev.forgetick import DONE, MINE, Claim, Work, assess, claim, forge_now
from lab_commons.dev.forgework import Client, ForgeCallFailed
from lab_commons.dev.platformparts import PartRefusal, part_context, post
from lab_commons.dev.producer import ProducerExit, release_reason
from lab_commons.hpc import learned, outstanding
from lab_commons.hpc.account import ClusterAccount
from lab_commons.hpc.builds import builds_at
from lab_commons.hpc.cluster import Runner, submitter
from lab_commons.hpc.config import Config
from lab_commons.hpc.grants import Grant, Machine, load_grants, workstation
from lab_commons.hpc.platforms import table_at
from lab_commons.hpc.records import read_record, write_record
from lab_commons.hpc.run import load_state, submit_run
from lab_commons.hpc.shell import FULL, RunSpec
from lab_commons.hpc.watch import PENDING, settle

__all__ = [
    'CLAIMED_PHASE',
    'GATHERED',
    'PUBLISHED',
    'SCHEMA',
    'SUBMITTED',
    'Cluster',
    'ForeignSchema',
    'Run',
    'SlurmCluster',
    'advance',
    'directory',
    'drop',
    'live',
    'save',
    'slurm_cluster',
    'start',
    'tidy',
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
    if run.phase == CLAIMED_PHASE:
        ids = cluster.submitted(run)
        if not ids:
            orphans = cluster.orphans(run)
            if orphans:
                alarm(_orphaned(run, orphans))
                say(f'{tag}: orphaned jobs {" ".join(orphans)} -- not resubmitted')
                return run
            ids = cluster.submit(run)
            say(f'{tag}: submitted jobs {" ".join(ids)}')
        run = _step(run, phase=SUBMITTED, job_ids=tuple(ids))
    if run.phase == SUBMITTED:
        record = cluster.gather(run)
        if record is None:
            say(f'{tag}: running (jobs {" ".join(run.job_ids)})')
            return run
        run = _step(run, phase=GATHERED, record=str(record))
    if run.phase == GATHERED:
        published = _publish(root, run, client=client, cluster=cluster, say=say, alarm=alarm, tag=tag)
        if published is None:
            return None
        run = published
    record = read_record(Path(run.record))
    for one in route(client, record, pyproject_at(root, run.sha)):
        say(f'{tag}: routed {one.area} {one.action}' + (f' #{one.number}' if one.number else ''))
    drop(run)
    say(f'{tag}: published and released')
    return None


def _publish(
    root: Path,
    run: Run,
    *,
    client: Client,
    cluster: Cluster,
    say: Callable[[str], None],
    alarm: Callable[[Alarm], None],
    tag: str,
) -> Run | None:
    """Store the declared outputs, then post the record; ``None`` once the part is released instead."""
    try:
        run = _ship(root, run, client=client, cluster=cluster, say=say, tag=tag)
        say(post(root, Path(run.record)))
    except MissingOutput as missing:  # a declared output is part of the request: its absence fails the run
        alarm(Alarm(RUN, run.repo_url, f'the run of {run.sha[:12]} lacks a declared output', str(missing)))
        say(f'{tag}: {missing}')
        _release(client, run, f'declared outputs missing: {missing}'[:_DESCRIPTION_MAX], say)
    except PartRefusal as why:  # an inconclusive record is never a part
        say(f'{tag}: {why}')
        _release(client, run, release_reason(ProducerExit.INCONCLUSIVE), say)
    else:
        return _step(run, phase=PUBLISHED)
    drop(run)
    return None


def _ship(root: Path, run: Run, *, client: Client, cluster: Cluster, say: Callable[[str], None], tag: str) -> Run:
    """Pack the declared outputs, put them, and name them in the record's ``artefacts``; idempotent per run."""
    record = read_record(Path(run.record))
    if not run.outputs or 'artefacts' in record:
        return run
    if not run.artefact:
        run = _step(run, artefact=run_id(run.sha, run.platform, forge_now(client)))
    tree = cluster.tree(run)
    archive = pack(tree, collect(tree, run.outputs), Path(run.output) / f'{run.artefact}{ARCHIVE}')
    store = store_for(load_config(root), client, forge_from_remote(root).repo, size=archive.stat().st_size)
    ref = store.put(run.artefact, archive)
    archive.unlink()
    run = _step(run, record=str(write_record({**record, 'artefacts': [ref.manifest()]}, Path(run.record).parent)))
    say(f'{tag}: {len(run.outputs)} declared output(s) stored as {ref.backend}:{ref.key} ({ref.bytes} bytes)')
    return run


def tidy(root: Path, client: Client, *, say: Callable[[str], None]) -> tuple[str, ...]:
    """Clean every artefact store this repo writes: past ``retain_days``, then down to ``cap_gb``; pins stay."""
    config = load_config(root)
    stores: list[ArtefactStore] = [ForgeStore(client)]
    large = large_store(config, forge_from_remote(root).repo)
    stores += [large] if large is not None else []
    keep, now = pinned(client), forge_now(client)
    gone = []
    for store in stores:
        cap = config.cap_bytes if store is large else 0
        for ref in clean(store, now=now, retain_days=config.retain_days, cap_bytes=cap, pinned=keep):
            gone.append(f'{ref.backend}:{ref.key}')
            say(f'[artefacts] deleted {ref.backend}:{ref.key}')
    return tuple(gone)


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
    renewal = dataclasses.replace(me, until=now + lease)
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


@dataclass(frozen=True)
class SlurmCluster:
    """:class:`Cluster` through ``lab_commons.hpc`` and this login node's own shell (:func:`slurm_cluster`)."""

    root: Path
    machine: Machine
    config: Config
    connect: Callable[[Grant], Runner]

    def _runners(self) -> dict[tuple[str, str], Runner]:
        return {grant.account: self.connect(grant) for grant in self.machine.grants}

    def submitted(self, run: Run) -> list[str]:
        """The job ids of every round ``hpc`` recorded for *run*'s sha; ``[]`` when it recorded none."""
        try:
            state, _ = load_state(run.sha, self.machine, self._runners())
        except RuntimeError:  # no state.json: nothing was submitted, or it died before writing one
            return []
        return [one['job_id'] for one in state['rounds']]

    def orphans(self, run: Run) -> list[str]:
        """Jobs Slurm holds under this account with *run*'s job name (``run-<sha12>``)."""
        shell = self.connect(self.machine.grants[0])
        return shell(f'squeue -h --me -n run-{run.sha[:12]} -o %i', None).split()

    def submit(self, run: Run) -> list[str]:
        """Fetch, build, collect, plan and submit round 0 (:func:`lab_commons.hpc.run.submit_run`)."""
        spec = RunSpec(
            sha=run.sha,
            repo_url=run.repo_url,
            collect=run.collect,
            table=table_at(self.root, run.sha),
            pack_from=self.root,
            builds=builds_at(self.root, run.sha, python=''),
        )
        state = submit_run(
            spec,
            self.machine,
            self.connect,
            cost=self.config.cost,
            policy=self.config.policy,
            history=learned.learned(run.repo_url),
        )
        ids = [one['job_id'] for one in state['rounds']]
        outstanding.add(run.sha, repo=run.repo_url, grant=state['rounds'][0]['grant'], job_ids=ids)
        return ids

    def tree(self, run: Run) -> Path:
        """``~/ci/trees/<sha>`` in this account's home (:attr:`lab_commons.hpc.shell.RunSpec.tree`)."""
        return Path(f'~/ci/trees/{run.sha}').expanduser()

    def gather(self, run: Run) -> Path | None:
        """One :func:`lab_commons.hpc.watch.settle` without waiting: the record it wrote, or ``None`` while pending."""
        output = Path(run.output)
        if settle([run.sha], self.machine, self.connect, self.config, output, sleep=None) == PENDING:
            return None
        records = sorted(output.glob(f'run-{run.sha}-{run.platform}-*.json.gz'), key=lambda path: path.stat().st_mtime)
        if not records:
            msg = f'the run of {run.sha[:12]} ended without a record in {output}; its lines above say why'
            raise RuntimeError(msg)
        return records[-1]


def slurm_cluster(root: Path, seat: ClusterAccount | None) -> SlurmCluster:
    """The cluster of *seat*, through the grants of its account only (another user's home is not this one's)."""
    if seat is None:
        msg = 'this box is not on a cluster (no sbatch); a cluster run advances only on its login node'
        raise ValueError(msg)
    grants = tuple(grant for grant in load_grants().grants if grant.user == seat.account)
    if not grants:
        msg = (
            f'no [[hpc.grant]] in {config_path()} has user = "{seat.account}" (the Slurm user this runs as); '
            'add one naming its slurm_account and share so a cluster part can be planned'
        )
        raise ValueError(msg)
    return SlurmCluster(root, Machine(workstation=workstation(), grants=grants), Config(), submitter())
