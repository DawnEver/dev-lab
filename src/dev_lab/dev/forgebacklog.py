"""REVIEW-BACKLOG: a ready PR waiting on ``tests/review`` past the declared bound pages once (2026-11-03 audit).

The 11-02/03 backlog went unseen. lab-commons' review job could not import its method, concluded without posting
``tests/review``, and every PR there waited while nothing paged; on Gitea the reviews came back ``exhausted``. Both
look the same from the forge: a ready head whose ``tests/review`` is absent or still ``pending`` long after its
push. That is the one signal read here, so it covers a job that never posted as well as one that waits on a cap.

ONE ``integration`` alarm per such head (:func:`alarms`), raised by the serve's integration step through
:func:`dev_lab.dev.forgeservesteps.raise_once`, which keeps one issue per alarm and pages once; a posted verdict or
a new head closes it. The bound is the repo's ``[tool.dev_lab.review] backlog`` (:func:`declared_wait`), a
duration, :data:`DEFAULT_WAIT` when undeclared. A draft is not waiting on a review (D53): it is never counted.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Final

from dev_lab.dev.forgealarm import INTEGRATION, Alarm, pull_context
from dev_lab.dev.forgecontexts import REVIEW_CONTEXT
from dev_lab.dev.forgedraft import pushed
from dev_lab.dev.forgepulls import pr_list
from dev_lab.dev.forgereview_declared import Review, load_review
from dev_lab.dev.forgestatus import status_list

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = ['DEFAULT_WAIT', 'alarms', 'declared_wait']

#: The bound when a repo declares none.
DEFAULT_WAIT: Final = Review().backlog_for
#: The verdicts that end a wait: anything else (absent, ``pending``) is still waiting.
_VERDICTS: Final = frozenset({'success', 'failure', 'error'})
#: How much of a pending status's description the alarm quotes.
_QUOTED: Final = 80


def declared_wait(root: Path) -> timedelta:
    """*root*'s ``[tool.dev_lab.review] backlog``, :data:`DEFAULT_WAIT` when it declares none."""
    return load_review(root).backlog_for


def alarms(client: Client, base: str, repo: str, *, now: datetime, wait: timedelta = DEFAULT_WAIT) -> list[Alarm]:
    """One ``integration`` alarm per ready PR into *base* whose head has waited on ``tests/review`` past *wait*."""
    out = []
    for pull in pr_list(client):
        if pull.base != base or pull.draft or not pull.head_sha:
            continue
        review = next((s for s in status_list(client, pull.head_sha) if s.context == REVIEW_CONTEXT), None)
        if review is not None and review.state in _VERDICTS:
            continue
        waited = now - pushed(client, pull.head_sha)
        if waited < wait:
            continue
        said = f'pending: {review.description[:_QUOTED]}' if review is not None else f'no {REVIEW_CONTEXT} posted'
        out.append(Alarm(
            INTEGRATION, repo, f'review backlog #{pull.number} {pull.head_sha[:12]}',
            f'#{pull.number} ({pull.title}) has waited {int(waited.total_seconds() // 3600)}h on {REVIEW_CONTEXT} '
            f'({said}). See why: `python -m dev_lab.dev.forge status list {pull.head_sha}`.',
            context=pull_context(pull),
        ))  # fmt: skip
    return out
