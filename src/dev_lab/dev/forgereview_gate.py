"""THE REVIEW GATE: whether a head is reviewed, read as the trusted declaration says -- for every merge door.

dev-lab's merge, merge-ready and Break-Glass ask this one function; the declaration it reads is the base's
``[tool.dev_lab.review]`` (:func:`~dev_lab.dev.forgereview_declared.forge_review`), the verdicts are the forge's
(:mod:`~dev_lab.dev.reviewgate`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dev_lab.dev._forgebackends import ADVISORY, JUDGE_HOST, require_producer
from dev_lab.dev.forgereview_declared import JUDGE, forge_review
from dev_lab.dev.reviewgate import (
    forge_posted,
    status_gate,
)

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client
    from dev_lab.dev.reviewgate import Reviewed

__all__ = ['review_gate']


def review_gate(client: Client, *, base: str) -> Reviewed:
    """THE ONE GATE of whether a head is reviewed, for the merge, merge-ready and Break-Glass alike.

    The mode is the TRUSTED declaration at *base* (:func:`forge_review`): a ``serve`` repo is reviewed when the forge
    posted a ``tests/review`` success (:func:`~dev_lab.dev.reviewgate.review_missing`). A ``judge`` repo's verdict is
    ADVISORY (:data:`~dev_lab.dev._forgebackends.ADVISORY`, user ruling 2026-11-11): posted as information on Gitea,
    never a merge condition on either forge, so its gate never waits.

    Raises:
        NotWired: a ``judge`` declaration on a forge that wires no judge host (GitHub: Actions alone, 2026-11-11).

    """
    review = forge_review(client, base)
    if review.where == JUDGE:
        require_producer(client.backend, JUDGE_HOST, f'[tool.dev_lab.review] where = "{JUDGE}" at {base}')
        if JUDGE_HOST in ADVISORY:  # posted as information, never waited on (user ruling 2026-11-11)
            return lambda _statuses: None
    return status_gate(forge_posted(client))
