"""The STEPS one ``forge serve`` tick runs after its rounds: issue-kept alarms, cleanup, hygiene, retention, relock.

Each step is failure-contained -- a forge or disk failure is said or alarmed, never raised into the tick --
so one broken step never stops the others (:func:`dev_lab.dev.forgeserve.serve` calls them in order).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from lab_commons.hpc.account import ClusterAccount

from dev_lab.dev import forgeship, retention
from dev_lab.dev.breakglass import notices as break_glass
from dev_lab.dev.forgealarm import INTEGRATION, ISSUE_KINDS, RUN, STARVED, STORAGE, Alarm
from dev_lab.dev.forgeclaim import forge_now
from dev_lab.dev.forgehosts import HostCard
from dev_lab.dev.forgeintegration import alarms as sync_alarms
from dev_lab.dev.forgeintegration import tick as integration_tick
from dev_lab.dev.forgepulls import ListingIncomplete, pr_list
from dev_lab.dev.forgequeue import forge_queue, unadmitted
from dev_lab.dev.forgereview import step as review_step
from dev_lab.dev.forgeroute import reconcile
from dev_lab.dev.forgescarce import red_alarms as scarce_red
from dev_lab.dev.forgeschedule import load_schedule, starved_alarms
from dev_lab.dev.forgestatus import status_list
from dev_lab.dev.forgetidy import load_hygiene
from dev_lab.dev.forgetidy import tidy as issue_tidy
from dev_lab.dev.forgework import Client, ForgeCallFailed
from dev_lab.dev.integrator import observe
from dev_lab.dev.lanepolicy import load_policy
from dev_lab.dev.relock import carry

__all__ = ['hygiene', 'prompt', 'raise_once', 'relock', 'retain_storage', 'starved', 'tidy_runs']


def raise_once(built: Client, kind: str, alarms: Sequence[Alarm], *, alarm: Callable[[Alarm], object]) -> None:
    """Keep ONE forge issue per alarm of *kind* (``<kind>: <subject>``) and page only where it was written.

    Any host may raise these; :func:`dev_lab.dev.forgeroute.reconcile` finds the issue by its title, so
    N hosts deriving the same rows write one issue, the host that creates or changes it pages, and a row
    no longer derived closes its issue. A kind outside :data:`~dev_lab.dev.forgealarm.ISSUE_KINDS` is refused.
    """
    if kind not in ISSUE_KINDS:
        msg = f'{kind!r} is not an issue-kept alarm kind {ISSUE_KINDS} (dev_lab.dev.forgealarm.ISSUE_KINDS)'
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
    host: str,
) -> None:
    """The integrator's prompts, every child's behind/conflict report and a red scarce part, one issue per row.

    A forge or fetch failure is said, not raised -- and then NO row is reconciled, so a partial derivation
    never closes an issue it merely failed to see.
    """
    try:
        found = observe(root, repo, statuses=lambda sha: status_list(built, sha))
        policy = load_policy(root)
        ticked = integration_tick(root, built, policy, host=host)  # the host claims each auto-sync
        for line in ticked.lines:
            say(f'[serve] integration: {line}')
        review_step(root, built, policy=policy, say=say, host=host)  # advisory: the review host follows the integrator
        glass = break_glass(root, policy, repo)
        red = scarce_red(root, policy.integration, repo, lambda sha: status_list(built, sha))
        raise_once(
            built,
            INTEGRATION,
            [*found, *sync_alarms(ticked.said, policy, repo, now=forge_now(built)), *glass, *red],
            alarm=alarm,
        )
    except (ForgeCallFailed, ListingIncomplete, OSError, ValueError) as failed:
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


def relock(
    root: Path, repo: str, built: Client, *, say: Callable[[str], None], alarm: Callable[[Alarm], object]
) -> None:
    """Keep integration's lock at the newest resolution through one relock PR (:func:`dev_lab.dev.relock.carry`).

    Only where the forge merges PRs into integration (``pr_merges_since`` declared): there the relock lands like
    any other PR, and nowhere else would it land by itself. A failure alarms; the next tick tries afresh.
    """
    policy = load_policy(root)
    if not policy.pr_merges_since:
        return
    try:
        pulls = [pull for pull in pr_list(built) if pull.base == policy.integration]
        say(f'[serve] relock: {carry(root, policy, pulls=lambda: pulls, create=built.pr_create)}')
    except (ForgeCallFailed, ListingIncomplete, OSError) as failed:
        alarm(Alarm(INTEGRATION, repo, f'the {policy.integration} lock could not be relocked', str(failed)))
