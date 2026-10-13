"""LENDING ON THE SERVE LOOP'S SIDE: what runs here as :class:`~lab_commons.compute.admission.Held`, and preemption.

The rule is pure (:mod:`lab_commons.compute.admission`): a reservation lends what its holders leave idle,
and a holder's job preempts the loans in its lease. This module is its I/O half. A claim on loan says so
in its pending status (``on_loan=<lease id>``, :class:`~lab_commons.dev.forgeclaim.Claim`), so every
later tick reads a run back as the loan it is. A preempted CLUSTER loan is cancelled, its claim released
``preempted by reservation <id>`` -- OPEN again, re-queued, never an error -- and its run dropped; a
preempted LOCAL loan yields at its next wake (:func:`lab_commons.dev.forgeproduce.produce`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from lab_commons.compute.admission import Held
from lab_commons.compute.model import Job, Resources
from lab_commons.dev import forgerun
from lab_commons.dev.forgeclaim import Claim, Work
from lab_commons.dev.forgestatus import status_post
from lab_commons.dev.forgework import Client, ForgeCallFailed
from lab_commons.dev.platformparts import part_context
from lab_commons.dev.producer import preempted

__all__ = ['held_part', 'held_run', 'job_of', 'preempt_runs']

_Sized = Callable[[str, frozenset[str]], Mapping[str, float]]


def job_of(one: forgerun.Run | Work) -> Job:
    """The job a run or a claimed part is: what a holder's lease matches (its session is its ref)."""
    return Job('', one.sha, one.platform, session=one.ref)


def held_run(run: forgerun.Run, sized: _Sized) -> Held:
    """A cluster run in flight as what runs here: its learned demand, its job, the lease it borrows from."""
    return Held(Resources(sized(run.platform, frozenset())), job_of(run), _on_loan(Claim.parse(run.owner)))


def held_part(item: Work, sized: _Sized) -> Held:
    """A local part this serve produces, as what runs here."""
    return Held(Resources(sized(item.platform, frozenset())), job_of(item), _on_loan(item.holder))


def _on_loan(holder: Claim | None) -> int:
    return holder.on_loan if holder is not None else 0


def preempt_runs(
    runs: list[forgerun.Run],
    loans: Sequence[Held],
    *,
    client: Client,
    cluster: forgerun.Cluster,
    say: Callable[[str], None],
) -> list[forgerun.Run]:
    """Withdraw each cluster run a holder preempted -- cancel, release re-queued, drop; the runs kept."""
    displaced = {(one.job.sha, one.job.producer): one.on_loan for one in loans if one.job is not None}
    kept = []
    for run in runs:
        lease_id = displaced.get((run.sha, run.platform), 0)
        if not lease_id:
            kept.append(run)
            continue
        cancelled = cluster.cancel(run)
        try:
            status_post(
                client, run.sha, context=part_context(run.platform), state='error', description=preempted(lease_id)
            )
        except ForgeCallFailed as failed:
            say(f'[{run.platform}] could not release: {failed}')
        forgerun.drop(run)
        say(f'[{run.platform}] {run.sha[:12]}: {preempted(lease_id)}; cancelled {" ".join(cancelled) or "nothing"}')
    return kept
