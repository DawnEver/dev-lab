"""THE REVIEW GATE: whether a head is reviewed, read as the trusted declaration says -- for every merge door.

dev-lab's merge, merge-ready and Break-Glass ask this one function; the declaration it reads is the base's
``[tool.dev_lab.review]`` (:func:`~dev_lab.dev.forgereview_declared.forge_review`), the verdicts are the forge's
(:mod:`~dev_lab.dev.reviewgate`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dev_lab.dev.forgereview_declared import JUDGE, forge_review
from dev_lab.dev.reviewgate import (
    app_missing,
    app_verdicts,
    forge_posted,
    head_reviews,
    judge_missing,
    status_gate,
)

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client
    from dev_lab.dev.reviewgate import Reviewed

__all__ = ['review_gate']


def review_gate(client: Client, head: str, *, base: str) -> Reviewed:
    """THE ONE GATE of whether *head* is reviewed, for the merge, merge-ready and Break-Glass alike.

    The mode is the TRUSTED declaration at *base* (:func:`forge_review`): a ``judge`` repo is reviewed when its
    declared ``judge_login`` approved *head* (:func:`~dev_lab.dev.reviewgate.judge_missing`) -- or, declaring
    ``judge_app``, when THAT App's check run approved it (:func:`~dev_lab.dev.reviewgate.app_missing`) -- a
    ``serve`` repo when the forge posted a ``tests/review`` success (:func:`~dev_lab.dev.reviewgate.review_missing`).
    """
    review = forge_review(client, base)
    if review.where == JUDGE and review.judge_app:
        runs = app_verdicts(client, head)
        return lambda statuses: app_missing(statuses, runs, head=head, app_id=review.judge_app)
    if review.where == JUDGE:
        reviews = head_reviews(client, head)
        return lambda statuses: judge_missing(statuses, reviews, head=head, judge=review.judge_login)
    return status_gate(forge_posted(client))
