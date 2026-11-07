"""NEWEST-HEAD-ONLY: what becomes of a cluster run once its ref has moved on, has landed, or is gone.

:mod:`dev_lab.dev.forgerun` advances a run one tick at a time; at a submit and at every gather it asks
:func:`superseding_tip`, and a run with one is handed to :func:`supersede`: its pending tasks withdrawn, its
started ones drained to their deadline (:func:`overdue`), then released superseded. A run whose ref is gone and
whose result no live head carries has every job cancelled. The rulings and incidents are in
:mod:`dev_lab.dev.forgerun`'s docstring.

A HEAD ALREADY IN THE INTEGRATION REF IS SUPERSEDED TOO (user ruling 2026-11-07). The integration tip runs the
full suite over it, so a run of any other ref whose sha that tip already contains -- its own ref moved or not --
is superseded by the integration tip, unless its result carries there (equivalent, P6). On 2026-11-07 the
integrator settled such claims by hand: pending ``tests/base`` claims with a lease held the integration tip.

EVERY SUPERSEDED CLAIM SETTLES ``error`` ``superseded by <sha>`` (:data:`SUPERSEDED_BY`): DONE on the forge
(:func:`dev_lab.dev.forgeclaim.assess`), so it is never retaken when its lease lapses. ``forge run supersede
--ref <ref>`` (:func:`settle_superseded`) posts the same settlement from any workstation for every claim on the
ref's earlier heads; the owning host's next tick then withdraws and drains that run, posting nothing
(:func:`drain_settled`).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Final

from dev_lab.dev import forgerunpost
from dev_lab.dev.forgealarm import RUN, Alarm
from dev_lab.dev.forgecarry import contained, data_only, equivalent
from dev_lab.dev.forgeclaim import Claim
from dev_lab.dev.forgecoalesce import DRAINING, PUBLISHING, earlier_tips
from dev_lab.dev.forgerunpost import DESCRIPTION_MAX
from dev_lab.dev.forgerunstate import Cluster, Draining, Run, drop
from dev_lab.dev.forgeschedule import coalesced, tip_of
from dev_lab.dev.forgestatus import status_history, status_post
from dev_lab.dev.forgework import Client
from dev_lab.dev.lanepolicy import load_policy
from dev_lab.supervise.notice import Context

__all__ = [
    'REF_GONE',
    'SUPERSEDED_BY',
    'drain_settled',
    'overdue',
    'settle_superseded',
    'supersede',
    'superseded_reason',
    'superseding_tip',
]

#: :func:`superseding_tip` for a run whose ref is gone (merged or closed) and no live head carries it.
REF_GONE: Final = '(ref gone)'
#: The description prefix of a part settled for a newer head: ``superseded by <sha> -- <why>``; DONE, never OPEN.
SUPERSEDED_BY: Final = 'superseded by'
#: The status contexts a part's claim lives in (:func:`dev_lab.dev.platformparts.part_context`).
_PART_CONTEXT: Final = 'tests/'


def superseded_reason(tip: str, why: str) -> str:
    """``superseded by <tip> -- <why>``, cut to a status description."""
    return f'{SUPERSEDED_BY} {tip} -- {why}'[:DESCRIPTION_MAX]


def superseding_tip(root: Path, run: Run) -> str:
    """The newer tip that supersedes *run*; ``''`` when none (still the tip, another class, or it carries).

    A DOCS-ONLY tip never supersedes (DOCS-ONLY-CARRIES, :func:`dev_lab.dev.forgecarry.docs_only`): no test's
    footprint reaches its diff, so its part IS this run's result, posted on it too when it lands (:func:`publish`).
    A DATA-ONLY tip (a memory or docs head a whole-tree test still reads, P6) never supersedes either: it waits
    on this run and then carries every outcome its diff cannot reach (:func:`dev_lab.dev.forgecarry.docs_only`).
    A run of any ref but the integration branch whose sha the integration tip already CONTAINS is superseded by
    that tip (:func:`_landed`, user ruling 2026-11-07). :data:`REF_GONE` when the ref itself is gone and no live
    head carries the run (:func:`_ref_gone`).
    A STARTED run of the INTEGRATION branch (a job submitted) is never superseded (D111): it is the only verdict
    ``integrate promote`` can read, and the branch moves faster than one run finishes.
    """
    integration = _integration(root)
    if run.ref != integration and (landed := _landed(root, run.sha, integration)):
        return landed
    if _ref_gone(root, run):
        return REF_GONE
    if run.job_ids and run.ref == integration:
        return ''
    tip = tip_of(root, run.ref)
    moved = tip and tip != run.sha and coalesced(root, run.ref)
    return tip if moved and not (equivalent(root, run.sha, tip) or data_only(root, run.sha, tip)) else ''


def _integration(root: Path) -> str:
    """*root*'s integration branch."""
    return load_policy(root).integration


def _landed(root: Path, sha: str, integration: str) -> str:
    """The integration tip when it already contains *sha* and *sha*'s result does not carry there; else ``''``."""
    tip = _landed_in(root, sha, integration)
    return '' if not tip or equivalent(root, sha, tip) else tip


def _landed_in(root: Path, sha: str, integration: str) -> str:
    """The integration tip when it contains *sha* and is not *sha* itself; else ``''``."""
    tip = tip_of(root, integration)
    return tip if tip and tip != sha and contained(root, sha, tip) else ''


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
    reason = superseded_reason(REF_GONE, f'{run.ref} is gone and no live head carries its result')
    why = f'jobs {" ".join(ids) or "none"} cancelled'
    alarm(
        Alarm(RUN, run.repo_url, f'the cluster run of {run.sha[:12]} was orphaned', why, context=Context(sha=run.sha))
    )
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
    ``superseded by <tip>`` and dropped: one alarm.
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
    reason = superseded_reason(tip, f'{run.ref}: its slot goes to the tip')
    why = 'pending tasks withdrawn, ' + (
        f'tasks {" ".join(cut)} cancelled past their deadline' if cut else 'no started task cancelled'
    )
    alarm(
        Alarm(
            RUN,
            run.repo_url,
            f'the cluster run of {run.sha[:12]} was superseded by {tip[:12]}',
            why,
            context=Context(sha=run.sha),
        )
    )
    say(f'{tag}: {why} -- {reason}')
    forgerunpost.release(client, run, reason, say)
    drop(run)
    return None


def drain_settled(run: Run, *, cluster: Cluster, say: Callable[[str], None], tag: str) -> Run | None:
    """A run whose part was settled :data:`SUPERSEDED_BY` on the forge: its Slurm half, POSTING NOTHING.

    Its pending tasks are withdrawn and its started ones drain to their deadline (:func:`overdue`), past which
    each is cancelled alone. The run is kept while any task runs -- so the stray sweep never cancels it
    (:meth:`dev_lab.dev.forgeslurm.SlurmCluster.strays`) -- and dropped once none does. The settlement on the
    forge stands: nothing is re-claimed or re-posted.
    """
    started = cluster.withdraw(run)
    if not started:
        say(f'{tag}: settled superseded on the forge -- pending tasks withdrawn, nothing runs')
        drop(run)
        return None
    drain = cluster.started_tasks(run)
    if not run.superseded_at:
        run = forgerunpost.step(run, superseded_at=drain.now)
    late = overdue(drain, since=run.superseded_at)
    cut = cluster.cancel_tasks(run, late) if late else []
    if cut:
        say(f'{tag}: settled superseded on the forge -- past their deadline, tasks {" ".join(cut)} cancelled')
    left = [one.job_id for one in drain.tasks if one.job_id not in cut]
    if left or not drain.tasks:  # an unread task is never judged late: it drains
        say(f'{tag}: settled superseded on the forge -- draining jobs {" ".join(started)}')
        return run
    drop(run)
    return None


def settle_superseded(root: Path, client: Client, ref: str) -> list[tuple[str, str, str]]:
    """Settle every claim on *ref*'s earlier heads :data:`SUPERSEDED_BY` its tip; ``(sha, context, by)`` each.

    ``forge run supersede --ref <ref>``, the integrator's door: nobody posts a status by hand (user ruling
    2026-11-07). The earlier heads are *ref*'s first-parent history before its tip -- for any ref but the
    integration branch only its OWN commits (:func:`dev_lab.dev.forgecoalesce.earlier_tips`). A head the
    integration tip already contains is superseded by that tip, the ref's own tip too. Only a live or lapsed
    CLAIM (a ``pending`` part) is settled: a verdict stands, a run ``publishing`` its record finishes, and a live
    tip that has not landed is never touched. The owning host's next tick drains the run (:func:`drain_settled`).
    """
    integration = _integration(root)
    tip = tip_of(root, ref)
    if not tip:
        msg = f'{ref} has no tip on origin as last fetched: fetch, or name a live ref'
        raise ValueError(msg)
    since = '' if ref == integration else f'refs/remotes/origin/{integration}'
    landed = '' if ref == integration else _landed_in(root, tip, integration)
    heads = [(sha, landed or tip) for sha in earlier_tips(root, tip, since=since)]
    heads += [(tip, landed)] if landed else []
    settled = []
    for sha, by in heads:
        history = status_history(client, sha)
        for context in sorted({one.context for one in history if one.context.startswith(_PART_CONTEXT)}):
            last = [one for one in history if one.context == context][-1]
            holder = Claim.parse(last.description) if last.state == 'pending' else None
            if holder is None or holder.progress.startswith(PUBLISHING):
                continue
            why = f'settled by forge run supersede; was {holder.progress or "claimed"}'
            status_post(client, sha, context=context, state='error', description=superseded_reason(by, why))
            settled.append((sha, context, by))
    return settled


def overdue(drain: Draining, *, since: float) -> list[str]:
    """The started tasks of *drain* past their deadline: their limit after *since* or their start, the later.

    A task started just before supersession is never cut short below its own limit.
    """
    return [one.job_id for one in drain.tasks if drain.now > max(since, one.started_at) + one.limit_s]
