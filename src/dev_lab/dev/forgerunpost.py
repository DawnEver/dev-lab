"""A cluster run's forge-facing posts and saved steps, for :mod:`dev_lab.dev.forgerun`.

Progress re-posted on the owner's claim, a release with its reason, a phase step saved to the run's state
file, and the alarms a run raises when it loses its claim or finds jobs it never recorded.
"""

from __future__ import annotations

import dataclasses
import shlex
from typing import TYPE_CHECKING, Final

from lab_commons.hpc.declared import RetiredTable
from lab_commons.hpc.run import NoRoom

from dev_lab.dev.artefacts import MissingOutput
from dev_lab.dev.forgealarm import LEASE, RUN, Alarm
from dev_lab.dev.forgeclaim import Claim, forge_now
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgerunstate import Killed, Run, save
from dev_lab.dev.forgestatus import status_post
from dev_lab.dev.forgework import Client
from dev_lab.dev.platformparts import part_context, run_tag
from dev_lab.dev.producer import RETRYABLE, ProducerExit, release_reason

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import timedelta

__all__ = ['DESCRIPTION_MAX', 'killed', 'lost', 'orphaned', 'release', 'release_reason_for', 'report', 'step']

#: A status description is short on every forge.
DESCRIPTION_MAX: Final = 140


def report(client: Client, run: Run, progress: str, lease: timedelta, say: Callable[[str], None]) -> Run:
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
    return step(run, owner=dataclasses.replace(renewed, progress='').description(), progress=progress)


def release_reason_for(run: Run, why: Exception, alarm: Callable[[Alarm], None]) -> str:
    """Why a run that ran no judged test is released: a missing declared output alarms and fails the run."""
    if isinstance(why, MissingOutput):  # a declared output is part of the request: its absence fails the run
        alarm(Alarm(RUN, run.repo_url, f'the run of {run.sha[:12]} lacks a declared output', str(why)))
        return f'declared outputs missing: {why}'[:DESCRIPTION_MAX]
    if isinstance(why, RetiredTable):  # fixed AT THE SHA: no retry publishes it, so it settles once
        alarm(Alarm(RUN, run.repo_url, f'the cluster run of {run.sha[:12]} settled', str(why)))
        return f'{release_reason(ProducerExit.INCONCLUSIVE)}: {why}'[:DESCRIPTION_MAX]
    if isinstance(why, NoRoom):  # a fact about this HOST: the part stays open to every host (forgeclaim.assess)
        return f'{RETRYABLE} -- this host had no room: {why}'[:DESCRIPTION_MAX]
    log = next((word for word in str(why).split() if word.startswith('log=')), '')  # the build log, named
    return f'{release_reason(ProducerExit.INCONCLUSIVE)} {log}'.strip()


def step(run: Run, **changes: object) -> Run:
    """*run* with *changes*, saved to its state file."""
    moved = dataclasses.replace(run, **changes)
    save(moved)
    return moved


def release(client: Client, run: Run, reason: str, say: Callable[[str], None]) -> None:
    """Post *run*'s part ``error`` with *reason*: released for any host to take; a failed post is said."""
    try:
        status_post(client, run.sha, context=part_context(run.platform), state='error', description=reason)
    except ForgeCallFailed as failed:
        say(f'{run_tag(run.platform, run.sha)} could not release: {failed}')


def lost(run: Run, holder: Claim) -> Alarm:
    """The alarm for *run* losing its claim to *holder*."""
    return Alarm(
        LEASE,
        run.repo_url,
        f'lost the claim on {run.sha[:12]} to {holder.login}@{holder.machine}',
        f'{holder.description()} holds {part_context(run.platform)} now; this run stood down. Its Slurm jobs '
        f'({" ".join(run.job_ids) or "none submitted"}) keep running unless cancelled: scancel them if the '
        'new owner re-runs the commit.',
    )


def orphaned(run: Run, jobs: list[str]) -> Alarm:
    """The alarm for Slurm *jobs* of *run* that no run state recorded."""
    return Alarm(
        LEASE,
        run.repo_url,
        f'orphaned Slurm jobs for {run.sha[:12]}',
        f'jobs {shlex.join(jobs)} run under this account but no run state was recorded, so the tick will not '
        'resubmit. Remedy: scancel them; the next tick submits the run afresh.',
    )


def killed(client: Client, run: Run, jobs: Sequence[Killed], say: Callable[[str], None], tag: str) -> None:
    """Post *jobs* Slurm killed for memory or time as ``slurm/<part>`` ``failure``: counts, the worst used/asked.

    Their own context, so the part's verdict stays the record's; the asks are already learned
    (:meth:`dev_lab.dev.forgeslurm.SlurmCluster.killed`). Nothing killed posts nothing.
    """
    if not jobs:
        return
    say(f'{tag}: killed by Slurm: {"; ".join(one.text() for one in jobs)}')
    words = []
    for state in sorted({one.state for one in jobs}):
        some = [one for one in jobs if one.state == state]
        worst = max(some, key=lambda one: one.used_mb if state == 'OUT_OF_MEMORY' else one.used_s)
        used = (
            f'{worst.used_mb}/{worst.asked_mb} MB' if state == 'OUT_OF_MEMORY' else f'{worst.used_s}/{worst.asked_s} s'
        )
        words.append(f'{len(some)} {state} (worst {worst.job} used/asked {used})')
    description = f'{"; ".join(words)}; next ask learned'[:DESCRIPTION_MAX]
    try:
        status_post(client, run.sha, context=f'slurm/{run.platform}', state='failure', description=description)
    except ForgeCallFailed as failed:  # a missed report is not a dead run
        say(f'{tag}: could not post the killed jobs: {failed}')
