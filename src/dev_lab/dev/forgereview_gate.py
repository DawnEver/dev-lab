"""THE REVIEW READING: whether a head is reviewed, read as the trusted declaration says -- REPORTED, never waited on.

The review is ADVISORY on both forges (user rulings 2026-11-11/12): merge-ready names this function's answer as a
warning and merges anyway; nothing blocks on it. The answer is still READ, because it is also what ASKS for the
review (:mod:`dev_lab.dev.reviewturn` calls a head due only while its reading is not ``None``): a reading that is
always ``None`` never asks, and the judge, which reviews only a head called due, never reviews (D226, 2026-11-28).
The declaration it reads is the base's ``[tool.dev_lab.review]`` (:func:`~dev_lab.dev.forgereview_declared.
forge_review`), the verdicts are the forge's (:mod:`~dev_lab.dev.reviewgate`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dev_lab.dev._forgebackends import JUDGE_HOST, require_producer
from dev_lab.dev.forgepulls import pages
from dev_lab.dev.forgereview_declared import forge_review
from dev_lab.dev.reviewgate import (
    app_missing,
    app_verdicts,
    forge_posted,
    judge_missing,
    status_gate,
)
from dev_lab.dev.roles import HOST

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client
    from dev_lab.dev.reviewgate import Reviewed

__all__ = ['NO_JUDGE', 'review_gate']

#: The reading of a host-bound review whose trusted declaration names no judge (EVERY-WALL-TEACHES): the judge
#: stops at :func:`dev_lab.dev.forgereview_bundle.judge_pending` with no identity to post as, so no head is ever
#: judged; merge-ready names it on every ready head instead of merging silently unreviewed.
NO_JUDGE: Final = (
    'review is bound to a host (the judge), and {base}:pyproject.toml [tool.dev_lab.review] declares no judge '
    'identity, so no judge ever reviews it: declare judge_login = "<the judge\'s forge login>" (Gitea) or '
    'judge_app = <App id> (GitHub) there'
)


def review_gate(client: Client, *, base: str, by: str, number: int, head: str) -> Reviewed:
    """THE ONE READING of whether PR *number*'s *head* is reviewed, which merge-ready reports and never waits on.

    *by* is the kind the family binds ``review`` to (:mod:`dev_lab.dev.roles`): reviewed by ``ci`` or ``hpc``, a head
    is reviewed when the forge posted a ``tests/review`` success (:func:`~dev_lab.dev.reviewgate.review_missing`).
    Reviewed by a ``host`` (the judge), it is reviewed when the judge the TRUSTED declaration at *base* names
    approved *head*: its login's PR review (:func:`~dev_lab.dev.reviewgate.judge_missing`) or its App's check run
    (:func:`~dev_lab.dev.reviewgate.app_missing`); a declaration naming neither reads :data:`NO_JUDGE`.

    Raises:
        NotWired: review bound to a host on a forge that wires no judge host.
        DeclarationUnread: the declaration at *base* cannot be read (a ``ValueError``: the caller reports it).

    """
    if by != HOST:
        return status_gate(forge_posted(client))
    require_producer(client.backend, JUDGE_HOST, f'review bound to a host (a judge) for {base}')
    review = forge_review(client, base)
    if review.judge_app:
        runs = app_verdicts(client, head)
        return lambda statuses: app_missing(statuses, runs, head=head, app_id=review.judge_app)
    if review.judge_login:
        reviews = pages(client, f'{client.repo}/pulls/{number}/reviews', {})
        return lambda statuses: judge_missing(statuses, reviews, head=head, judge=review.judge_login)
    unnamed = NO_JUDGE.format(base=base)
    return lambda _statuses: unnamed
