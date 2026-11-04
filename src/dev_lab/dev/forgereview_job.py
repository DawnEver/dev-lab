"""THE FORGE'S REVIEW JOB: ``forge review run --pr N`` reviews the one PR its event names, and how the job exits.

* :func:`review_run` -- :func:`~dev_lab.dev.forgereview.review_pull` on that PR alone, then rules on its pending
  claims; a host that cannot run the command holds the head and fails the job.
* :func:`job_exit` -- ``0`` only when the head is reviewed by what this job did, or by a run the gate counts
  (dev-lab #30): Gitea's gate reads the run's conclusion (:mod:`dev_lab.dev.reviewgate`).

The CLI that runs them is :mod:`dev_lab.dev.forgetakeover`'s ``main``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dev_lab.dev.forgereview import HostCannot, hold, review_pull
from dev_lab.dev.forgereview_claim import live_claim, run_ended
from dev_lab.dev.forgereview_declared import JUDGE
from dev_lab.dev.forgereview_dispose import adjudicate_thread
from dev_lab.dev.forgereview_judge import identity, pending
from dev_lab.dev.forgereview_rounds import trusted_bodies
from dev_lab.dev.forgestatus import status_list
from dev_lab.dev.platformparts import REVIEW_CONTEXT
from dev_lab.dev.reviewgate import forge_posted, review_missing

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from dev_lab.dev.forgereview_command import Runner
    from dev_lab.dev.forgereview_declared import Review
    from dev_lab.dev.forgework import Client

__all__ = ['HOST_CANNOT', 'job_exit', 'review_run']

#: What the hold says when the job's host cannot run the review command: the forge's review is re-run.
HOST_CANNOT: Final = 'the review job cannot run the review command'


def review_run(root: Path, client: Client, review: Review, number: int, *, base: str, runner: Runner) -> str:
    """:func:`review_pull` on PR *number* alone -- what a GitHub workflow job runs for its event's PR; the line.

    The job is the ONLY reviewer of its PR, so a host that cannot run the command is never silent: the head is held
    until the forge's review is re-run, and :class:`~dev_lab.dev.forgereview.HostCannot` is raised (the job fails).

    The same run then RULES on every claim still pending on the PR (:func:`adjudicate_thread`, as the job's own
    identity): GitHub runs an ``issue_comment`` workflow only from the default branch, so ``review-claims.yml``
    cannot rule on a PR whose fix it carries (#11) -- the PR's own ``pull_request`` job can.
    """
    pull = client.pr_view(number)
    if pull.base != base or pull.draft or not pull.head_sha:
        return f'#{number}: not reviewed -- only an open, non-draft PR into {base} is'
    if review.where == JUDGE:  # one mode per repo: the judge host reviews it from a bundle
        return f'#{number}: not reviewed here -- {base} declares where = "{JUDGE}"'
    try:
        said = review_pull(root, client, review, pull, runner) or _stood(client, pull.head_sha, number)
    except HostCannot as cannot:
        raise HostCannot(hold(client, pull, f'{HOST_CANNOT}: {cannot}')) from cannot
    if not pending(trusted_bodies(client, number, review.reviewers)):
        return said
    ruled = adjudicate_thread(
        root, client, review, number, base=base, adjudicator=identity(client, runner.host, serving=runner.serving),
        run=runner.run, runtimes=runner.runtimes,
    )  # fmt: skip
    return '; '.join([said, *ruled])


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

    Gitea's gate counts a review only when the base's ``pull_request_target`` run concluded success
    (:mod:`dev_lab.dev.reviewgate`), so a run must FAIL unless it posted success. *posted* is what this job's
    :func:`~dev_lab.dev.reviewgate.post_review` calls posted, in order
    (:func:`~dev_lab.dev.reviewgate.posted_verdicts`): its LAST state decides. A job that posted none (a head whose
    counted review stands, a PR it does not review) exits ``0`` only when the gate itself counts the head's review,
    or when another Actions run still running holds the head's claim (:func:`live_claim`, *ended* defaulting to
    :func:`run_ended`): that run posts the verdict, and its conclusion is the one the gate reads.
    """
    pull = client.pr_view(number)
    if pull.base != base:  # not a PR into the trusted integration: never reviewed, so never a success
        return 1
    if posted:
        return 0 if posted[-1] == 'success' else 1
    head = pull.head_sha
    latest = next((one for one in status_list(client, head) if one.context == REVIEW_CONTEXT), None) if head else None
    if live_claim(latest, run_ended(client) if ended is None else ended):
        return 0
    return 0 if head and review_missing(status_list(client, head), forge_posted(client, head, base=base)) is None else 1
