"""A REVIEW THAT STANDS, OR IS ASKED AGAIN: what a PR's head gets from the forge's review with NO model call.

:mod:`dev_lab.dev.forgereview` reviews a PR once; every later head gets the standing verdict (:func:`stands`). A
session moves it by asking: ``forge review again <pr>`` (:func:`ask_again`, honoured by :func:`asked_again`)
re-reviews a head, and ``forge review carry <pr>`` (:func:`carry`) disposes of a finding a continuation PR carries
(LANDED-BRANCH-CONTINUES, :mod:`dev_lab.dev.branchreview`), which re-posts the held verdict (:func:`restands`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dev_lab.dev.branchreview import dispose
from dev_lab.dev.forgepulls import Marker, comment_list, comment_upsert, marker
from dev_lab.dev.forgereview_advice import CARRIED_HOLD, verdict
from dev_lab.dev.forgereview_claim import DESCRIPTION
from dev_lab.dev.reviewgate import post_review

if TYPE_CHECKING:
    from dev_lab.dev.branchreview import Carried
    from dev_lab.dev.forgereview_advice import Record
    from dev_lab.dev.forgereview_declared import Review
    from dev_lab.dev.forgestatus import CommitStatus
    from dev_lab.dev.forgework import Client, PullRequest

__all__ = ['ask_again', 'asked_again', 'carry', 'restands', 'stands']


def ask_again(client: Client, number: int, head: str, who: str) -> str:
    """Record *who*'s request to review PR *number* again at *head*; the forge's next review run honours it."""
    comment_upsert(client, number, kind=Marker.REVIEW_AGAIN, key=head,
                   text=f'Review asked again at `{head[:12]}` by {who}.')  # fmt: skip
    return f'#{number} {head[:12]}: review asked again; the next review run reviews this head'


def carry(client: Client, review: Review, number: int, finding: str, *, state: str, reason: str, who: str) -> str:
    """Record *who*'s disposition of *finding*, carried by continuation PR *number*; the line said.

    The branch's review record takes it (:func:`~dev_lab.dev.branchreview.dispose`, which refuses an unknown id and a
    deferral with no reason), and ONE comment per finding says it on the PR: on GitHub that comment starts the
    review-again job, on Gitea the serve's next tick reads the record; either re-posts the verdict
    (:func:`restands`) without a model call.
    """
    pull = client.pr_view(number)
    said = dispose(client, pull, finding, state=state, reason=reason, reviewers=review.reviewers)
    text = f'Carried finding `{finding}` {state} by {who}' + (f': {reason.strip()}' if reason.strip() else '.')
    comment_upsert(client, number, kind=Marker.REVIEW_CARRY, key=finding, text=text)
    return f'{said}; the next review run re-posts the verdict'


def asked_again(client: Client, number: int, head: str) -> bool:
    """Whether a session asked (:func:`ask_again`) to review PR *number* again at *head*."""
    key = marker(Marker.REVIEW_AGAIN, head)
    return any(key in comment.body for comment in comment_list(client, number))


def _standing(record: Record, pull: PullRequest, carry: Carried | None) -> tuple[str, str]:
    """``(state, description)`` of *record*'s verdict standing on *pull*'s head, *carry*'s open findings counted."""
    state, said = verdict(record, pull.number, carry.open if carry else ())
    return state, f'review of {record.head[:12]} stands: {said}'[:DESCRIPTION]


def stands(client: Client, pull: PullRequest, record: Record, carry: Carried | None = None) -> str:
    """Post *record*'s verdict on *pull*'s head, naming the head it reviewed: nothing runs. The line said.

    A continuation's *carry* still open holds it (:func:`~dev_lab.dev.forgereview_advice.verdict`).
    """
    state, why = _standing(record, pull, carry)
    post_review(client, pull.head_sha, state=state, description=why)
    return f'#{pull.number} {pull.head_sha[:12]}: {why}'


def restands(
    client: Client, pull: PullRequest, record: Record | None, carry: Carried | None, latest: CommitStatus | None
) -> str | None:
    """Re-post a verdict a carried finding's disposition changed (``forge review carry``); ``None`` when unchanged.

    A head held at ``failure`` by :data:`~dev_lab.dev.forgereview_advice.CARRIED_HOLD` is settled, so no review runs
    on it again; once its carried findings are resolved or deferred its standing verdict moves -- no model call.
    """
    if record is None or latest is None or latest.state != 'failure' or CARRIED_HOLD not in latest.description:
        return None
    if _standing(record, pull, carry) == (latest.state, latest.description):
        return None
    return stands(client, pull, record, carry)
