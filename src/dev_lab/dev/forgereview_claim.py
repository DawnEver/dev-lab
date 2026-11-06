"""A head's review CLAIM: who may take a head, the statuses a review that did not run leaves, and a host unable.

:mod:`dev_lab.dev.forgereview` claims a head (:data:`CLAIMED`) before it runs the command; every other host skips
it until the claim is released, goes stale, or the host posts :data:`HOST_UNABLE` -- a fact about the host, so the
head stays claimable. A claim posted by an Actions job names its run (:func:`claim_of`), and a claim whose run has
ENDED is free at once (:func:`run_ended`): a cancelled run never releases its claim -- the runner kills the job
without running a trap or an ``always()`` step it could post from -- so the forge's record of the run is the one
signal that survives a cancellation (2026-11-04, dev-lab #79: a claim held its head 10 h until it went stale).

A REVIEW THAT DID NOT RUN NEVER HOLDS THE MERGE (user ruling 2026-11-06): a failed attempt on the serve tick is
``error`` :data:`RETRYING` (claimable, so the next tick tries once more); a second failure, a failure in a review
job (it has no next tick), a missing review key or a reached cap is ``pending`` :data:`UNREVIEWED_STATUS`, and the
cause is recorded on the PR for the merge's waiver (:func:`dev_lab.dev.reviewcap.unreviewed_line`).
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

from dev_lab.dev.forgereview_batch import BATCH_PENDING
from dev_lab.dev.forgestatus import status_list
from dev_lab.dev.platformparts import REVIEW_CONTEXT
from dev_lab.dev.reviewgate import post_review

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from dev_lab.dev.forgestatus import CommitStatus
    from dev_lab.dev.forgework import Client, PullRequest

__all__ = [
    'CLAIMED', 'DESCRIPTION', 'HOST_UNABLE', 'RELEASED', 'RETRYING', 'UNREVIEWED_STATUS', 'claim_of', 'claimable',
    'latest_review', 'live_claim', 'retried', 'run_ended', 'unable',
]  # fmt: skip

#: The claim a host posts (``pending``) before it runs the command: every other host skips the head.
CLAIMED: Final = 'claimed by'

#: A claim given back by hand (``pending``): the head is free again at once.
RELEASED: Final = 'released by'

#: What an ``error`` says when THIS HOST cannot run the review (:class:`ReviewUnsupported`): a fact about the host,
#: not the head, so the head stays claimable -- by a capable host, or by this one once it is fixed.
HOST_UNABLE: Final = 'not reviewed: cannot run on host'

#: What an ``error`` opens with after a review attempt failed on the serve tick: the head is claimable, and the next
#: tick tries ONCE more (:func:`retried`).
RETRYING: Final = 'review attempt failed, retried once:'

#: What a ``pending`` status opens with when the review did not run and will not be retried: the merge waives it
#: from the cause recorded on the PR (:mod:`dev_lab.dev.reviewcap`).
UNREVIEWED_STATUS: Final = 'not reviewed, merges unreviewed:'

#: A commit-status description is short: every one posted is cut to this.
DESCRIPTION: Final = 240

_CLAIM: Final = re.compile(rf'^{CLAIMED} (?P<host>\S+) at (?P<at>\S+), reviewing(?: \(run (?P<run>\d+)\))?')


def _never(_run: str) -> bool:
    return False


def latest_review(client: Client, head: str) -> CommitStatus | None:
    """*head*'s latest :data:`REVIEW_CONTEXT` status, else ``None``."""
    return next((one for one in status_list(client, head) if one.context == REVIEW_CONTEXT), None)


def retried(client: Client, head: str) -> bool:
    """Whether a review attempt on *head* already failed once (a :data:`RETRYING` status in its history)."""
    return any(
        one.context == REVIEW_CONTEXT and one.state == 'error' and one.description.startswith(RETRYING)
        for one in status_list(client, head)
    )


def claim_of(host: str, at: datetime, env: Mapping[str, str] | None = None) -> str:
    """The :data:`CLAIMED` description *host* posts at *at*; inside an Actions job it names the job's run."""
    run = (os.environ if env is None else env).get('GITHUB_RUN_ID', '')
    named = f' (run {run})' if run.isdigit() else ''
    return f'{CLAIMED} {host} at {at.isoformat(timespec="seconds")}, reviewing{named}'


def run_ended(client: Client, env: Mapping[str, str] | None = None) -> Callable[[str], bool]:
    """Whether the Actions run a claim names has ended, read from *client*'s forge (``GET .../actions/runs/{id}``).

    This job's OWN run id is ended too: a re-run reuses the id, so its claim is an earlier, killed attempt's.
    A run the forge cannot answer for is NOT ended -- the claim then holds until it goes stale, as before.
    """
    own = (os.environ if env is None else env).get('GITHUB_RUN_ID', '')

    def ended(run: str) -> bool:
        if run == own:
            return True
        try:
            answer: Any = client.call('GET', f'{client.repo}/actions/runs/{run}')
        except OSError:
            return False
        if not isinstance(answer, dict):
            return False
        return bool(answer.get('conclusion')) or answer.get('status') == 'completed'

    return ended


def live_claim(status: CommitStatus | None, ended: Callable[[str], bool]) -> bool:
    """Whether *status* is a claim by an Actions run the forge records as still running: that run posts the verdict."""
    if status is None or status.state != 'pending' or (claim := _CLAIM.match(status.description)) is None:
        return False
    return bool(claim['run']) and not ended(claim['run'])


def claimable(
    status: CommitStatus | None, now: datetime, stale: timedelta, ended: Callable[[str], bool] = _never
) -> bool:
    """Whether a head whose review status is *status* may be claimed: none, a released, stale or ended claim.

    A head whose batch is pending (:data:`~dev_lab.dev.forgereview_batch.BATCH_PENDING`) is claimable at once: its
    state is on the PR, so whoever claims it resumes the batch, never resubmits it. A host that could not run the
    review (:data:`HOST_UNABLE`) is the host's fault, never the head's; a first failed attempt (:data:`RETRYING`) is
    tried once more. A claim is ended when the run it names has ended (*ended*, :func:`run_ended`).
    """
    if status is None or (status.state == 'error' and status.description.startswith((HOST_UNABLE, RETRYING))):
        return True
    if status.state != 'pending':
        return False
    if status.description.startswith((RELEASED, BATCH_PENDING)):
        return True
    if (claim := _CLAIM.match(status.description)) is None:
        return False  # not reviewed for good, or any other pending: not ours to take
    try:
        at = datetime.fromisoformat(claim['at'])
    except ValueError:
        return True  # an unreadable claim cannot hold a head forever
    return now - at >= stale or (bool(claim['run']) and ended(claim['run']))


def unable(client: Client, pull: PullRequest, host: str, why: str) -> str:
    """Post :data:`HOST_UNABLE` naming *host* and *why* on *pull*'s head (not again if it already says so); the line.

    The head stays claimable: another host, or this one once fixed, reviews it on a later tick.
    """
    head = pull.head_sha
    said = f'{HOST_UNABLE} {host}: {why}'[:DESCRIPTION]
    latest = latest_review(client, head)
    if latest is None or (latest.state, latest.description) != ('error', said):
        post_review(client, head, state='error', description=said)
    return f'#{pull.number} {head[:12]}: {said}'
