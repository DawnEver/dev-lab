"""THE FORGE'S REVIEW JOB: ``forge review run --pr N`` reviews the one PR its event names, and how the job exits.

* :func:`review_run` -- :func:`~dev_lab.dev.forgereview.review_pull` on that PR alone; a host that cannot run the
  command records the PR unreviewed (it merges with an ``Unreviewed:`` line) and fails the job.
* :func:`job_exit` -- ``0`` only when the head is reviewed by what this job did, or by a run the gate counts
  (dev-lab #30): Gitea's gate reads the run's conclusion (:mod:`dev_lab.dev.reviewgate`).

The CLI that runs them is :mod:`dev_lab.dev.forgetakeover`'s ``main``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dev_lab.dev.forgepulls import pr_list
from dev_lab.dev.forgereview import HostCannot, review_pull, unreviewed
from dev_lab.dev.forgereview_batch import BATCH_PENDING
from dev_lab.dev.forgereview_claim import UNREVIEWED_STATUS, live_claim, run_ended
from dev_lab.dev.forgereview_declared import JUDGE
from dev_lab.dev.forgestatus import status_list
from dev_lab.dev.platformparts import REVIEW_CONTEXT
from dev_lab.dev.reviewgate import forge_posted, review_missing

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from dev_lab.dev.forgereview_command import Runner
    from dev_lab.dev.forgereview_declared import Review
    from dev_lab.dev.forgework import Client, PullRequest

__all__ = ['HOST_CANNOT', 'batch_pending', 'job_exit', 'resume_batches', 'review_run']

#: The unreviewed cause when the job's host cannot run the review command.
HOST_CANNOT: Final = 'the review job cannot run the review command'


def review_run(root: Path, client: Client, review: Review, number: int, *, base: str, runner: Runner) -> str:
    """:func:`review_pull` on PR *number* alone -- what a GitHub workflow job runs for its event's PR; the line.

    The job is the ONLY reviewer of its PR, so a host that cannot run the command is never silent: the PR is
    recorded unreviewed (:func:`~dev_lab.dev.forgereview.unreviewed`, it never holds the merge) and
    :class:`~dev_lab.dev.forgereview.HostCannot` is raised, so the job fails visibly.
    """
    pull = client.pr_view(number)
    if pull.base != base or pull.draft or not pull.head_sha:
        return f'#{number}: not reviewed -- only an open, non-draft PR into {base} is'
    if review.where == JUDGE:  # one mode per repo: the judge host reviews it from a bundle
        return f'#{number}: not reviewed here -- {base} declares where = "{JUDGE}"'
    try:
        return review_pull(root, client, review, pull, runner) or _stood(client, pull.head_sha, number)
    except HostCannot as cannot:
        raise HostCannot(unreviewed(client, pull, f'{HOST_CANNOT}: {cannot}')) from cannot


def batch_pending(client: Client, base: str) -> tuple[PullRequest, ...]:
    """Every open, non-draft PR into *base* whose head's review is a pending batch (:data:`BATCH_PENDING`)."""
    return tuple(
        pull for pull in pr_list(client)
        if pull.base == base and not pull.draft and pull.head_sha and _batch_waits(client, pull.head_sha)
    )  # fmt: skip


def resume_batches(
    root: Path, client: Client, review: Review, *, base: str, runner: Runner, fetch: Callable[[Path, int], object]
) -> list[str]:  # fmt: skip
    """Resume the review of every :func:`batch_pending` head from the batch state on its PR; the lines said.

    What the scheduled job runs (``forge review run --batch-pending``): a pending batch never waits for a human. The
    state comment names the batches, so the round polls them and never resubmits; a head still pending stays so.
    """
    said = []
    for pull in batch_pending(client, base):
        fetch(root, pull.number)
        said.append(review_run(root, client, review, pull.number, base=base, runner=runner))
    return said


def _batch_waits(client: Client, head: str) -> bool:
    latest = next((one for one in status_list(client, head) if one.context == REVIEW_CONTEXT), None)
    return latest is not None and latest.state == 'pending' and latest.description.startswith(BATCH_PENDING)


def _settled_pending(client: Client, head: str) -> bool:
    latest = next((one for one in status_list(client, head) if one.context == REVIEW_CONTEXT), None)
    return latest is not None and latest.description.startswith((BATCH_PENDING, UNREVIEWED_STATUS))


def _stood(client: Client, head: str, number: int) -> str:
    """What stands on *head* when :func:`review_pull` did nothing: a claim by another run, else its review."""
    latest = next((one for one in status_list(client, head) if one.context == REVIEW_CONTEXT), None)
    if latest is not None and latest.state == 'pending':
        return f'#{number} {head[:12]}: claimed by another run, which posts the verdict ({latest.description})'
    return f'#{number} {head[:12]}: already reviewed'


def job_exit(
    client: Client, number: int, posted: Sequence[str], *, base: str, ended: Callable[[str], bool] | None = None
) -> int:
    """The review job's exit: ``0`` only when the PR's head is reviewed by what this job did (dev-lab #30).

    *posted* is what this job's :func:`~dev_lab.dev.reviewgate.post_review` calls posted, in order
    (:func:`~dev_lab.dev.reviewgate.posted_verdicts`): its LAST state decides, so a run FAILS unless it posted
    success. A job that posted none (a head whose counted review stands, a PR it does not review) exits ``0`` only
    when the gate itself counts the head's review, or when another Actions run still running holds the head's claim
    (:func:`live_claim`, *ended* defaulting to :func:`run_ended`): that run posts the verdict.

    A BATCH STILL RUNNING is no failure: a job that left the head ``pending`` :data:`BATCH_PENDING` exits ``0`` on
    either forge -- the status alone holds the merge, and the scheduled resume (:func:`resume_batches`) settles it.
    Nor is a review that did not run (``pending`` :data:`UNREVIEWED_STATUS`): the PR merges ``Unreviewed``.
    """
    pull = client.pr_view(number)
    if pull.base != base:  # not a PR into the trusted integration: never reviewed, so never a success
        return 1
    if posted:
        if posted[-1] == 'pending' and _settled_pending(client, pull.head_sha):
            return 0  # pending is not failure: a batch still running, or a review that merges unreviewed
        return 0 if posted[-1] == 'success' else 1
    head = pull.head_sha
    latest = next((one for one in status_list(client, head) if one.context == REVIEW_CONTEXT), None) if head else None
    if live_claim(latest, run_ended(client) if ended is None else ended):
        return 0
    return 0 if head and review_missing(status_list(client, head), forge_posted(client)) is None else 1
