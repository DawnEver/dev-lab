"""A LONG PRODUCER IS A RESUMABLE TICK -- the cluster part, advanced one step per ``forge serve`` call.

WHY A TICK AND NOT A PROCESS. A cluster run takes hours; a login node's cron tick, a reaper or a
reboot does not let one process live that long. A blocking producer orphaned its Slurm jobs, its claim
aged out, and another account re-claimed the commit into a duplicate run (design 2026-10-11, gap 1).
So each ``forge serve`` invocation ADVANCES ON-DISK STATE and returns:

    claimed -> submitting -> submitted (Slurm job ids) -> gathered (the run record) -> published -> released

DECLARED OUTPUTS SHIP WITH THE RECORD. The outputs a part declares (``[tool.lab_commons.hpc] outputs``,
captured in the run when it is claimed -- declared at REQUEST time) are packed from the run's work
tree and put in the artefact store (:mod:`lab_commons.dev.artefacts`) after the record is gathered and
before it is posted; the record's ``artefacts`` manifest names them. A declared output that is missing
releases the part as an error and alarms. Each serve tick on a cluster also cleans the stores
(:func:`lab_commons.dev.forgeship.tidy`) of this host's own account's runs: one of several writers.

One file per run, keyed by repo + sha + platform + scope, under ``forge-runs/`` beside the machine
file (:func:`directory`) -- in the account's home, so any login host of that account sees it.

SLURM IS THE TRUTH FOR JOB STATE; THE FILE ONLY SAYS HOW FAR THIS SIDE GOT. ``submitted`` is decided
by the run state ``hpc`` keeps on the cluster (``~/ci/runs/<sha>/<part>/state.json``), and gathering asks
``sacct`` (:func:`lab_commons.hpc.gather.gather_run`). A crash between ticks therefore resumes; it never
resubmits: a ``claimed`` run whose jobs exist (by ``squeue`` job name) but whose run state was never
written is an ORPHAN -- it raises an alarm and waits for a human to ``scancel`` it, because submitting
again would double the run.

A RUN NOTHING MORE WILL COME OF SETTLES, ONCE (:func:`_settle`). A ``submitted`` run whose part has no
state and no job of its name never ran; one whose jobs ended without a record never will have one. Each
is released with its reason on record and its file dropped -- one alarm, never one per tick (Ada,
2026-10-17: two femm runs re-alarmed "ended without a record" every tick). A run that never ran is
released RETRYABLE while its sha is its ref's tip, else settled as superseded.

INTENT BEFORE ACTION (design D19). The run file says ``submitting`` -- fsynced -- BEFORE ``sbatch`` is
called, so a crash between the submit and the run state ``hpc`` writes after it is never an orphan: jobs of
the run's name found under a ``submitting`` run are THIS run's interrupted submit, by the journal's word.
They are cancelled (no state on the cluster says how to gather them) and the run is submitted afresh, with
no human in the loop. Jobs found under a ``claimed`` run were never journaled as ours and still alarm.

ONLY THE OWNER RENEWS. Every tick re-claims the run's commit through the forge's race
(:func:`lab_commons.dev.forgeclaim.claim`) before advancing it. A claim another owner now holds stands
this run DOWN (its file is dropped, nothing is produced, an alarm says so); a live claim held by
ANOTHER LOGIN HOST OF THIS ACCOUNT is left alone entirely -- ONE HOST PER ACCOUNT, and this is its
guard, since ``flock`` on GPFS does not lock across hosts.

PROGRESS TRAVELS ON THE CLAIM. Whenever where the run stands changes -- ``building``, ``queued 0/93``,
``running 40/93 done 12/93``, ``publishing`` -- the owner re-posts its pending claim with that progress
(:class:`lab_commons.dev.forgeclaim.Claim`), so any machine with a forge credential sees it; the final
status links the run record.

A COALESCED REF'S RUN IS SUPERSEDED THE TICK ITS REF MOVES ON, STARTED OR NOT (user ruling 2026-10-21). A run
of a ``Schedule.coalesce`` class whose sha is no longer its ref's tip has every Slurm job its state records
cancelled (every round and band, :func:`lab_commons.hpc.run.cancel_run`), is released as superseded naming
the tip, and is dropped -- one alarm. Its slot goes to the tip, which waited behind it (:mod:`forgecoalesce`);
the tip's run carries what the cancelled rounds finished (:mod:`lab_commons.dev.forgecarry`). A DOCS-ONLY tip
never supersedes it: its part is this run's result, carried on landing (DOCS-ONLY-CARRIES). Asked before a
submit and at every gather. Ada 2026-10-19: integrate/main's tip waited hours behind an older sha's array;
2026-10-21: a superseded pr head kept 70 array tasks running on alyyw103, eating the grant's QOS room.
A ref of any OTHER class is tested at every pushed sha: its run finishes and posts on its own sha, and when
the tip is reach-equivalent its record is posted on the tip too, as a part naming the sha it was judged at.

A SUBMIT REFUSED ON THE QOS LIMIT IS NO ROOM (:data:`lab_commons.hpc.cluster.SUBMIT_LIMIT`): released RETRYABLE,
so a grant with headroom claims the part, never a run alarming "cannot advance" every tick holding its claim.

THE RUN STATE -- the file, its schema and the cluster protocol -- lives in :mod:`lab_commons.dev.forgerunstate`.
"""

from __future__ import annotations

import dataclasses
import shlex
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Final

from lab_commons.dev import forgeship
from lab_commons.dev.artefacts import MissingOutput, run_id
from lab_commons.dev.forgealarm import LEASE, RUN, Alarm
from lab_commons.dev.forgecarry import equivalent, publish
from lab_commons.dev.forgeclaim import DONE, MINE, Claim, Work, assess, claim, forge_now
from lab_commons.dev.forgecoalesce import PUBLISHING
from lab_commons.dev.forgeroute import pyproject_at, route
from lab_commons.dev.forgerunstate import (
    CLAIMED_PHASE,
    GATHERED,
    PUBLISHED,
    SUBMITTED,
    SUBMITTING,
    Cluster,
    Run,
    Unrecorded,
    drop,
    save,
)
from lab_commons.dev.forgeschedule import coalesced, tip_of
from lab_commons.dev.forgestatus import status_history, status_post
from lab_commons.dev.forgework import Client, ForgeCallFailed
from lab_commons.dev.platformparts import PartRefusal, part_context, run_tag
from lab_commons.dev.producer import RETRYABLE, ProducerExit, release_reason
from lab_commons.hpc.records import read_record, write_record
from lab_commons.hpc.run import NoRoom
from lab_commons.hpc.tree import NotSubmitted

__all__ = ['advance', 'start']

#: What a tick may do with a run (:func:`_hold`).
_ADVANCE: Final = 'advance'
_WAIT: Final = 'wait'
_GONE: Final = 'gone'

#: A status description is short on every forge.
_DESCRIPTION_MAX: Final = 140


def start(work: Work, owner: Claim) -> Run:
    """The run of a part just claimed: phase ``claimed``, saved before anything is submitted."""
    if work.cluster is None:
        msg = f'{work.sha[:12]}: a cluster run needs a claimed cluster part'
        raise ValueError(msg)
    part = work.cluster
    run = Run(
        repo_url=part.repo_url, sha=work.sha, ref=work.ref, collect=part.collect, output=str(part.output),
        owner=owner.description(), platform=work.platform, outputs=part.outputs,
    )  # fmt: skip
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
    tag = run_tag(run.platform, run.sha)
    held, run = _hold(run, client=client, me=me, lease=lease, say=say, alarm=alarm, tag=tag)
    if held != _ADVANCE:
        return run if held == _WAIT else None
    try:  # a build that submitted nothing, like an inconclusive record, ran no test: released, never red
        if run.phase in {CLAIMED_PHASE, SUBMITTING}:
            if tip := _superseding_tip(root, run):  # its ref moved on: no submit, the tip takes the slot
                _supersede(client, run, tip, cluster=cluster, say=say, alarm=alarm, tag=tag)
                return None
            submitted = _submit(run, client=client, lease=lease, cluster=cluster, say=say, alarm=alarm, tag=tag)
            if submitted is None:
                return run
            run = submitted
        if run.phase == SUBMITTED:
            gathered = _gather(root, run, client=client, lease=lease, cluster=cluster, say=say, alarm=alarm, tag=tag)
            if gathered is None or gathered.phase == SUBMITTED:  # settled, or still running
                return gathered
            run = gathered
        if run.phase == GATHERED:
            # routed BEFORE the part is posted: an INCONCLUSIVE record is refused a part, yet each red it
            # reported is real (lab_commons.dev.forgeroute); re-routing an unchanged record writes nothing.
            for one in route(client, read_record(Path(run.record)), pyproject_at(root, run.sha)):
                say(f'{tag}: routed {one.area} {one.action}' + (f' #{one.number}' if one.number else ''))
            run = _ship(root, run, client=client, cluster=cluster, say=say, tag=tag)
            say(publish(root, Path(run.record), client=client, ref=run.ref, sha=run.sha, platform=run.platform))
            run = _step(run, phase=PUBLISHED)
    except (MissingOutput, NotSubmitted, PartRefusal) as why:
        say(f'{tag}: {why}')
        _release(client, run, _release_reason(run, why, alarm), say)
        drop(run)
        return None
    drop(run)
    say(f'{tag}: published and released')
    return None


def _gather(
    root: Path,
    run: Run,
    *,
    client: Client,
    lease: timedelta,
    cluster: Cluster,
    say: Callable[[str], None],
    alarm: Callable[[Alarm], None],
    tag: str,
) -> Run | None:
    """A submitted run gathered (phase ``gathered``), still running (``submitted``), or ``None`` once settled."""
    ids = tuple(cluster.submitted(run))
    if not ids and not cluster.orphans(run):  # no state and no job of this part: it never ran
        _settle(root, run, client=client, why='no job of this part was ever submitted', say=say, alarm=alarm, ran=False)
        return None
    if tip := _superseding_tip(root, run):  # started or not (user ruling 2026-10-21)
        _supersede(client, run, tip, cluster=cluster, say=say, alarm=alarm, tag=tag)
        return None
    try:
        record = cluster.gather(run)
    except Unrecorded as why:
        _settle(root, run, client=client, why=str(why), say=say, alarm=alarm, ran=True)
        return None
    if record is None:
        # hpc submits retry rounds inside a gather: re-read every round's job id each tick (Ada,
        # 2026-10-12: the submit's r0 id was still shown while r2 ran).
        run = _step(run, job_ids=tuple(cluster.submitted(run)) or ids or run.job_ids)
        say(f'{tag}: running (job {run.job_ids[-1]}, round {len(run.job_ids)})')
        return _report(client, run, cluster.progress(run), lease, say)
    run = _step(run, phase=GATHERED, record=str(record))
    return _report(client, run, PUBLISHING, lease, say)


def _superseding_tip(root: Path, run: Run) -> str:
    """The newer tip of *run*'s coalesced ref that supersedes it; ``''`` when none (still the tip, another class).

    A DOCS-ONLY tip never supersedes (DOCS-ONLY-CARRIES, :func:`lab_commons.dev.forgecarry.docs_only`): no test's
    footprint reaches its diff, so its part IS this run's result, posted on it too when it lands (:func:`publish`).
    """
    tip = tip_of(root, run.ref)
    moved = tip and tip != run.sha and coalesced(root, run.ref)
    return tip if moved and not equivalent(root, run.sha, tip) else ''


def _supersede(
    client: Client,
    run: Run,
    tip: str,
    *,
    cluster: Cluster,
    say: Callable[[str], None],
    alarm: Callable[[Alarm], None],
    tag: str,
) -> None:
    """Cancel EVERY job of *run* (each round and band, an interrupted submit's too), release it superseded by *tip*.

    Then drop it: one alarm. Started or not (user ruling 2026-10-21).
    """
    cancelled = cluster.cancel(run)
    reason = (
        f'released: superseded -- {run.ref} moved on to {tip[:12]}; its jobs are cancelled, its slot goes to the tip'
    )
    reason = reason[:_DESCRIPTION_MAX]
    why = f'jobs {" ".join(cancelled) or "none"} cancelled'
    alarm(Alarm(RUN, run.repo_url, f'the cluster run of {run.sha[:12]} was superseded by {tip[:12]}', why))
    say(f'{tag}: {why} -- {reason}')
    _release(client, run, reason, say)
    drop(run)


def _settle(
    root: Path,
    run: Run,
    *,
    client: Client,
    why: str,
    say: Callable[[str], None],
    alarm: Callable[[Alarm], None],
    ran: bool,
) -> None:
    """Release a run nothing more will come of, with the reason on record, and drop it: ONE alarm, never one per tick.

    A run that RAN and wrote no record is inconclusive (a human reads its lines). One that never submitted
    ran no test: it is released RETRYABLE while its sha is still its ref's tip (the candidate any host claims
    again), else settled as superseded -- the newer tip is the candidate now.
    """
    if ran:
        reason = f'{release_reason(ProducerExit.INCONCLUSIVE)}: ended without a record'
    elif tip_of(root, run.ref) == run.sha:
        reason = f'{RETRYABLE} -- never submitted; claimable again'
    else:
        reason = f'released: superseded -- never submitted, and {run.ref} moved on'
    reason = reason[:_DESCRIPTION_MAX]
    alarm(Alarm(RUN, run.repo_url, f'the cluster run of {run.sha[:12]} settled', f'{why}; {reason}'))
    say(f'{run_tag(run.platform, run.sha)}: {why} -- {reason}')
    _release(client, run, reason, say)
    drop(run)


def _submit(
    run: Run,
    *,
    client: Client,
    lease: timedelta,
    cluster: Cluster,
    say: Callable[[str], None],
    alarm: Callable[[Alarm], None],
    tag: str,
) -> Run | None:
    """*run* submitted: Slurm's recorded jobs adopted, else ``submitting`` journaled then sbatch; ``None``: orphans.

    Jobs of the run's name under a ``claimed`` run alarm and wait (never journaled as ours); under a
    ``submitting`` run they are this run's interrupted submit: cancelled, and the run submitted afresh.
    """
    ids = cluster.submitted(run)
    if not ids:
        orphans = cluster.orphans(run)
        if orphans and run.phase == CLAIMED_PHASE:
            alarm(_orphaned(run, orphans))
            say(f'{tag}: orphaned jobs {" ".join(orphans)} -- not resubmitted')
            return None
        if orphans:
            cancelled = cluster.cancel(dataclasses.replace(run, job_ids=tuple(orphans)))
            say(f'{tag}: an interrupted submit left jobs {" ".join(cancelled)} -- cancelled, resubmitting')
        run = _report(client, _step(run, phase=SUBMITTING), 'building', lease, say)
        ids = cluster.submit(run)
        say(f'{tag}: submitted jobs {" ".join(ids)}')
    return _step(run, phase=SUBMITTED, job_ids=tuple(ids))


def _report(client: Client, run: Run, progress: str, lease: timedelta, say: Callable[[str], None]) -> Run:
    """Re-post the owner's claim carrying *progress* when it changed; the run with it recorded."""
    if not progress or progress == run.progress:
        return run
    renewed = dataclasses.replace(run.claim, until=forge_now(client) + lease, progress=progress)
    context = part_context(run.platform)
    try:
        status_post(client, run.sha, context=context, state='pending', description=renewed.description())
    except ForgeCallFailed as failed:  # a missed progress post is not a dead run; the next tick posts it
        say(f'{run_tag(run.platform, run.sha)}: could not post progress: {failed}')
        return run
    return _step(run, owner=dataclasses.replace(renewed, progress='').description(), progress=progress)


def _release_reason(run: Run, why: Exception, alarm: Callable[[Alarm], None]) -> str:
    """Why a run that ran no judged test is released: a missing declared output alarms and fails the run."""
    if isinstance(why, MissingOutput):  # a declared output is part of the request: its absence fails the run
        alarm(Alarm(RUN, run.repo_url, f'the run of {run.sha[:12]} lacks a declared output', str(why)))
        return f'declared outputs missing: {why}'[:_DESCRIPTION_MAX]
    if isinstance(why, NoRoom):  # a fact about this HOST: the part stays open to every host (forgeclaim.assess)
        return f'{RETRYABLE} -- this host had no room: {why}'[:_DESCRIPTION_MAX]
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
    state, holder = assess(status_history(client, run.sha), part_context(run.platform), me=owner, now=now)
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
        say(f'{run_tag(run.platform, run.sha)} could not release: {failed}')


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
