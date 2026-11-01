"""REVIEW-IS-REQUIRED: the ONE predicate of whether a head is reviewed -- for the merge and for Break-Glass alike.

User ruling 2026-10-31, "every PR must get a review". A head is reviewed when, and only when, its latest
:data:`~dev_lab.dev.forgecontexts.REVIEW_CONTEXT` is ``success`` and no
:data:`~dev_lab.dev.forgecontexts.HOLD_CONTEXT` is pending. Every other state -- absent, a claim still reviewing,
a takeover pending, an ``error``, a ``failure`` -- is not a review, and :func:`review_missing` names it. Nothing is
advisory: ai-lab #3 and dev-lab #5 were auto-merged with ``tests/review=error`` when an error was.

THE SUCCESS IS VERIFIED AT READ TIME FROM WHAT THE FORGE RECORDS (D11, #11 round 3, F-e4d5c529db40): the
``success`` counts only when the forge-recorded CREATOR of that status is the forge's own identity
(:func:`forge_creators`) -- the forge's own Actions job: GitHub's Actions bot, Gitea's Actions ghost. A status
a developer's or an agent's token posted never satisfies it, whatever environment the poster claimed: every
identity the local side asserts is forgeable by a same-user agent, the forge's record of who wrote is not.

The remedy for a head whose review could not run is :data:`RERUN`: the forge's own review, run again.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dev_lab.dev._forgebackends import GITEA, GITHUB
from dev_lab.dev.forgecontexts import HOLD_CONTEXT, REVIEW_CONTEXT

if TYPE_CHECKING:
    from collections.abc import Sequence

    from dev_lab.dev.forgestatus import CommitStatus

__all__ = ['RERUN', 'forge_creators', 'review_missing']

#: The remedy for a head with no forge-posted review: the forge reviews it again, never a session.
RERUN: Final = "re-run the forge's review of the head (the PR's review job)"


def forge_creators(*, github: bool) -> frozenset[str]:
    """The status creators the forge's own review job is recorded as: the forge's Actions identity, nothing else.

    GitHub records its Actions bot; Gitea records its Actions ghost, which its API answers as ``"creator": null``
    (read as ``''``). No repo declares it: the forge decides who its job is, a token holder cannot.
    """
    return frozenset({(GITHUB if github else GITEA).actions_status_creator})


def review_missing(statuses: Sequence[CommitStatus], creators: frozenset[str]) -> str | None:
    """Why the head *statuses* (newest first) describe is not reviewed, or ``None`` when it is.

    A ``success`` counts only when its forge-recorded creator is one of *creators* (:func:`forge_creators`).
    """
    latest: dict[str, CommitStatus] = {}
    for one in statuses:
        latest.setdefault(one.context, one)
    review, hold = latest.get(REVIEW_CONTEXT), latest.get(HOLD_CONTEXT)
    if review is None:
        return f'{REVIEW_CONTEXT} is not posted: {RERUN}'
    if review.state != 'success':
        return f'{REVIEW_CONTEXT} is {review.state}: {review.description}'
    if review.creator not in creators:
        return (
            f'{REVIEW_CONTEXT} success was posted by {review.creator or "an unrecorded login"}, not by the forge '
            f'({", ".join(sorted(one or "its Actions ghost" for one in creators))}): '
            f"only the forge's own review counts -- {RERUN}"
        )
    if hold is not None and hold.state != 'success':
        return f'{HOLD_CONTEXT} is {hold.state}: {hold.description}'
    return None
