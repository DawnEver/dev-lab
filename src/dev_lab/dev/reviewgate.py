"""REVIEW-IS-REQUIRED: the ONE predicate of whether a head is reviewed -- for the merge and for Break-Glass alike.

User ruling 2026-10-31, "every PR must get a review". A head is reviewed when, and only when, its latest
:data:`~dev_lab.dev.forgecontexts.REVIEW_CONTEXT` is ``success`` and no
:data:`~dev_lab.dev.forgecontexts.HOLD_CONTEXT` is pending. Every other state -- absent, a claim still reviewing,
a takeover pending, an ``error``, a ``failure`` -- is not a review, and :func:`review_missing` names it. Nothing is
advisory: ai-lab #3 and dev-lab #5 were auto-merged with ``tests/review=error`` when an error was.

The remedy for a head whose review could not run is the takeover door (``forge review takeover <sha>``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dev_lab.dev.forgecontexts import HOLD_CONTEXT, REVIEW_CONTEXT

if TYPE_CHECKING:
    from collections.abc import Sequence

    from dev_lab.dev.forgestatus import CommitStatus

__all__ = ['review_missing', 'reviewed']


def review_missing(statuses: Sequence[CommitStatus]) -> str | None:
    """Why the head *statuses* (newest first) describe is not reviewed, or ``None`` when it is."""
    latest: dict[str, CommitStatus] = {}
    for one in statuses:
        latest.setdefault(one.context, one)
    review, hold = latest.get(REVIEW_CONTEXT), latest.get(HOLD_CONTEXT)
    if review is None:
        return f'{REVIEW_CONTEXT} is not posted: run `forge review takeover <sha>` if the review cannot run'
    if review.state != 'success':
        return f'{REVIEW_CONTEXT} is {review.state}: {review.description}'
    if hold is not None and hold.state != 'success':
        return f'{HOLD_CONTEXT} is {hold.state}: {hold.description}'
    return None


def reviewed(statuses: Sequence[CommitStatus]) -> bool:
    """Whether the head *statuses* describe carries a posted, successful review and no pending hold."""
    return review_missing(statuses) is None
