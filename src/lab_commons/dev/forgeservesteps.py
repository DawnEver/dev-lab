"""The STEPS one ``forge serve`` tick runs after its rounds: issue-kept alarms, cleanup, hygiene, retention.

Each step is failure-contained -- a forge or disk failure is said or alarmed, never raised into the tick --
so one broken step never stops the others (:func:`lab_commons.dev.forgeserve.serve` calls them in order).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from lab_commons.dev import forgeship, retention
from lab_commons.dev.breakglass import notices as break_glass
from lab_commons.dev.forgealarm import INTEGRATION, ISSUE_KINDS, RUN, STARVED, STORAGE, Alarm
from lab_commons.dev.forgeclaim import forge_now
from lab_commons.dev.forgehosts import HostCard
from lab_commons.dev.forgeintegration import alarms as sync_alarms
from lab_commons.dev.forgeintegration import tick as integration_tick
from lab_commons.dev.forgepulls import ListingIncomplete
from lab_commons.dev.forgequeue import forge_queue, unadmitted
from lab_commons.dev.forgeroute import reconcile
from lab_commons.dev.forgeschedule import load_schedule, starved_alarms
from lab_commons.dev.forgestatus import status_list
from lab_commons.dev.forgetidy import load_hygiene
from lab_commons.dev.forgetidy import tidy as issue_tidy
from lab_commons.dev.forgework import Client, ForgeCallFailed
from lab_commons.dev.integrator import observe
from lab_commons.dev.lanepolicy import load_policy
from lab_commons.hpc.account import ClusterAccount

__all__ = ['hygiene', 'prompt', 'raise_once', 'retain_storage', 'starved', 'tidy_runs']


def raise_once(built: Client, kind: str, alarms: Sequence[Alarm], *, alarm: Callable[[Alarm], object]) -> None:
    """Keep ONE forge issue per alarm of *kind* (``<kind>: <subject>``) and page only where it was written.

    Any host may raise these; :func:`lab_commons.dev.forgeroute.reconcile` finds the issue by its title, so
    N hosts deriving the same rows write one issue, the host that creates or changes it pages, and a row
    no longer derived closes its issue. A kind outside :data:`~lab_commons.dev.forgealarm.ISSUE_KINDS` is refused.
    """
    if kind not in ISSUE_KINDS:
        msg = f'{kind!r} is not an issue-kept alarm kind {ISSUE_KINDS} (lab_commons.dev.forgealarm.ISSUE_KINDS)'
        raise ValueError(msg)
    by_title = {f'{kind}: {one.subject}': one for one in alarms}
    for done in reconcile(built, f'{kind}: ', {title: one.body for title, one in by_title.items()}):
        if done.action in {'created', 'updated'} and done.area in by_title:
            alarm(by_title[done.area])


def starved(
    root: Path,
    repo: str,
    built: Client,
    cards: Sequence[HostCard],
    *,
    say: Callable[[str], None],
    alarm: Callable[[Alarm], object],
) -> None:
    """A ``starved`` issue for each part NO host admits, read across every card; any host may raise it."""
    schedule = load_schedule(root)
    try:
        queue, _ = forge_queue(root, built, cards, now=forge_now(built), schedule=schedule)
        found = starved_alarms([item for item in queue if unadmitted(item.blocked)], schedule, repo)
        raise_once(built, STARVED, found, alarm=alarm)
    except ForgeCallFailed as failed:
        say(f'[serve] the starved parts were not raised: {failed}')


def prompt(
    root: Path,
    repo: str,
    built: Client,
    *,
    say: Callable[[str], None],
    alarm: Callable[[Alarm], object],
) -> None:
    """The integrator's prompts and every child's behind/conflict report, one issue per row.

    A forge or fetch failure is said, not raised -- and then NO row is reconciled, so a partial derivation
    never closes an issue it merely failed to see.
    """
    try:
        found = observe(root, repo, statuses=lambda sha: status_list(built, sha))
        policy = load_policy(root)
        ticked = integration_tick(root, built, policy)
        for line in ticked.lines:
            say(f'[serve] integration: {line}')
        glass = break_glass(root, policy, repo)
        raise_once(built, INTEGRATION, [*found, *sync_alarms(ticked.said, policy, repo), *glass], alarm=alarm)
    except (ForgeCallFailed, ListingIncomplete, OSError) as failed:
        say(f'[serve] the integration queue was not derived: {failed}')


def tidy_runs(
    root: Path,
    client: Callable[[Path], Client],
    repo: str,
    *,
    seat: ClusterAccount | None,
    say: Callable[[str], None],
    alarm: Callable[[Alarm], object],
) -> None:
    """On a cluster -- one artefact writer -- clean its own account's runs each tick; a failure only alarms."""
    if seat is None:
        return
    try:
        forgeship.tidy(root, client(root), account=seat.account, say=say)
    except (OSError, ValueError) as why:
        alarm(Alarm(RUN, repo, 'the artefact cleanup failed', str(why)))


def hygiene(root: Path, built: Client, *, say: Callable[[str], None]) -> None:
    """The repo's issue hygiene, on any host every tick (idempotent: a raced close is a no-op); a failure is said."""
    try:
        for line in issue_tidy(built, load_hygiene(root)):
            say(f'[serve] tidy: {line}')
    except (ForgeCallFailed, ListingIncomplete, ValueError) as failed:
        say(f'[serve] the issue hygiene did not run: {failed}')


def retain_storage(
    root: Path,
    repo: str,
    retain: Callable[..., retention.Freed | None],
    *,
    cluster: bool,
    who: str,
    say: Callable[[str], None],
    alarm: Callable[[Alarm], object],
) -> None:
    """The retention pass; a failure, or usage still over the pressure line after it, alarms."""
    try:
        done = retain(root, cluster=cluster, say=say)
    except (OSError, ValueError) as why:
        alarm(Alarm(RUN, repo, f'the storage retention pass failed on {who}', str(why)))
        return
    if done is not None and done.over:
        body = done.alarm or f'freed {done.freed_bytes} bytes and {done.freed_files} files; still over pressure'
        alarm(Alarm(STORAGE, repo, f'{who} storage is still near its quota', body))
