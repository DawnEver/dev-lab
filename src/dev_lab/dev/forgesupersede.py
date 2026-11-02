"""NEWEST-HEAD-ONLY: what becomes of a cluster run once its ref has moved on, or is gone.

:mod:`dev_lab.dev.forgerun` advances a run one tick at a time; at a submit and at every gather it asks
:func:`superseding_tip`, and a run with one is handed to :func:`supersede`: its pending tasks withdrawn, its
started ones drained to their deadline (:func:`overdue`), then released superseded. A run whose ref is gone and
whose result no live head carries has every job cancelled. The rulings and incidents are in
:mod:`dev_lab.dev.forgerun`'s docstring.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Final

from dev_lab.dev import forgerunpost
from dev_lab.dev.forgealarm import RUN, Alarm
from dev_lab.dev.forgecarry import data_only, equivalent
from dev_lab.dev.forgecoalesce import DRAINING
from dev_lab.dev.forgerunpost import DESCRIPTION_MAX
from dev_lab.dev.forgerunstate import Cluster, Draining, Run, drop
from dev_lab.dev.forgeschedule import coalesced, tip_of
from dev_lab.dev.forgework import Client
from dev_lab.dev.lanepolicy import load_policy

__all__ = ['REF_GONE', 'overdue', 'supersede', 'superseding_tip']

#: :func:`superseding_tip` for a run whose ref is gone (merged or closed) and no live head carries it.
REF_GONE: Final = '(ref gone)'


def superseding_tip(root: Path, run: Run) -> str:
    """The newer tip of *run*'s coalesced ref that supersedes it; ``''`` when none (still the tip, another class).

    A DOCS-ONLY tip never supersedes (DOCS-ONLY-CARRIES, :func:`dev_lab.dev.forgecarry.docs_only`): no test's
    footprint reaches its diff, so its part IS this run's result, posted on it too when it lands (:func:`publish`).
    A DATA-ONLY tip (a memory or docs head a whole-tree test still reads, P6) never supersedes either: it waits
    on this run and then carries every outcome its diff cannot reach (:func:`dev_lab.dev.forgecarry.docs_only`).
    :data:`REF_GONE` when the ref itself is gone and no live head carries the run (:func:`_ref_gone`).
    A STARTED run of the INTEGRATION branch (a job submitted) is never superseded (D111): it is the only verdict
    ``integrate promote`` can read, and the branch moves faster than one run finishes.
    """
    if _ref_gone(root, run):
        return REF_GONE
    if run.job_ids and run.ref == _integration(root):
        return ''
    tip = tip_of(root, run.ref)
    moved = tip and tip != run.sha and coalesced(root, run.ref)
    return tip if moved and not (equivalent(root, run.sha, tip) or data_only(root, run.sha, tip)) else ''


def _integration(root: Path) -> str:
    """*root*'s integration branch."""
    return load_policy(root).integration


def _ref_gone(root: Path, run: Run) -> bool:
    """Whether *run*'s ref has no tip (merged or closed, deleted) and its result carries to no live head.

    NEWEST-HEAD-ONLY drains a superseded run's started tasks because its tip carries them; a gone ref has no
    tip. The integration tip is the one live head left that may carry it (DOCS-ONLY-CARRIES, P6).
    """
    if tip_of(root, run.ref):
        return False
    integration = tip_of(root, _integration(root))
    return not (integration and equivalent(root, run.sha, integration))


def _cancel_orphan(
    client: Client, run: Run, *, cluster: Cluster, say: Callable[[str], None], alarm: Callable[[Alarm], None], tag: str
) -> None:
    """Cancel every job of *run* -- started ones too -- release it superseded and drop it: one alarm."""
    ids = cluster.cancel(run)
    reason = f'released: superseded -- {run.ref} is gone and no live head carries its result'[:DESCRIPTION_MAX]
    why = f'jobs {" ".join(ids) or "none"} cancelled'
    alarm(Alarm(RUN, run.repo_url, f'the cluster run of {run.sha[:12]} was orphaned', why))
    say(f'{tag}: {why} -- {reason}')
    forgerunpost.release(client, run, reason, say)
    drop(run)


def supersede(
    client: Client,
    run: Run,
    tip: str,
    *,
    cluster: Cluster,
    lease: timedelta,
    say: Callable[[str], None],
    alarm: Callable[[Alarm], None],
    tag: str,
) -> Run | None:
    """Withdraw *run*'s NOT-YET-STARTED tasks; drain its started ones to their deadline; then release it.

    NEWEST-HEAD-ONLY (user rulings 2026-10-22, 2026-10-24 "B"): while a started task runs within its deadline
    (:func:`overdue`) the run keeps its claim -- so the tip waits behind it (:mod:`dev_lab.dev.forgecoalesce`)
    and its run carries what the drained tasks finished (:mod:`dev_lab.dev.forgecarry`) -- and is returned. A
    task past its deadline is cancelled alone, its tests left for the tip. Once none runs the run is released
    superseded by *tip* and dropped: one alarm.
    """
    if tip == REF_GONE:  # no tip to drain for: every job goes, started ones too
        _cancel_orphan(client, run, cluster=cluster, say=say, alarm=alarm, tag=tag)
        return None
    started, cut = cluster.withdraw(run), []
    if started:
        drain = cluster.started_tasks(run)
        if not run.superseded_at:
            run = forgerunpost.step(run, superseded_at=drain.now)
        if late := overdue(drain, since=run.superseded_at):
            cut = cluster.cancel_tasks(run, late)
            say(f'{tag}: superseded by {tip[:12]} -- past their deadline, tasks {" ".join(cut)} cancelled')
        left = [one.job_id for one in drain.tasks if one.job_id not in cut]
        if left or not drain.tasks:  # an unread task is never judged late: it drains
            say(f'{tag}: superseded by {tip[:12]} -- pending tasks withdrawn, draining jobs {" ".join(started)}')
            count = len(left) if drain.tasks else len(started)
            return forgerunpost.report(client, run, f'{DRAINING} {count} started job(s) for {tip[:12]}', lease, say)
    reason = f'released: superseded -- {run.ref} moved on to {tip[:12]}; its slot goes to the tip'
    reason = reason[:DESCRIPTION_MAX]
    why = 'pending tasks withdrawn, ' + (
        f'tasks {" ".join(cut)} cancelled past their deadline' if cut else 'no started task cancelled'
    )
    alarm(Alarm(RUN, run.repo_url, f'the cluster run of {run.sha[:12]} was superseded by {tip[:12]}', why))
    say(f'{tag}: {why} -- {reason}')
    forgerunpost.release(client, run, reason, say)
    drop(run)
    return None


def overdue(drain: Draining, *, since: float) -> list[str]:
    """The started tasks of *drain* past their deadline: their limit after *since* or their start, the later.

    A task started just before supersession is never cut short below its own limit.
    """
    return [one.job_id for one in drain.tasks if drain.now > max(since, one.started_at) + one.limit_s]
