"""ONE RETRY POLICY PER OWNER CLASS: whether a released part is claimed again (W5, dev-lab#644).

A release names its owner (:class:`~dev_lab.dev.producer.Owner`, ``class=<owner>``). Before W5 only a
:data:`~dev_lab.dev.producer.RETRYABLE` text reopened a claim, so a part refusal settled for good
and held the sha unsettled until a human re-ran it. Now the CLASS decides, from :data:`RETRIES`: ``code`` is never
retried (it is the author's red), a part refusal until its limit, and a class with no retries reopens only when its
release says :data:`~dev_lab.dev.producer.RETRYABLE` (no room, no network) -- a supersession or a deterministic
environment defect settles, never spinning every tick.
:func:`dev_lab.dev.forgeclaim.assess` reads :func:`requeued`; the merge never waits on a non-code class
(:mod:`dev_lab.dev.forgemergewaits`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dev_lab.dev.producer import RETRYABLE, Owner, owner_of

if TYPE_CHECKING:
    from collections.abc import Sequence

    from dev_lab.dev.forgestatus import CommitStatus

__all__ = ['RETRIES', 'requeued']

#: How many releases of each class are requeued on one context of one sha beyond a RETRYABLE one. THE ONE TABLE.
RETRIES: Final[dict[Owner, int]] = {
    Owner.CODE: 0,
    Owner.ENVIRONMENT: 0,
    Owner.PART_REFUSAL: 3,
    Owner.SCHEDULING: 0,
    Owner.VENDOR_LICENCE: 0,
    Owner.NETWORK: 0,
    Owner.STATUS_PUBLISHING: 0,
}


def requeued(history: Sequence[CommitStatus]) -> bool:
    """Whether the last of *history* (one context's posts, oldest first) is a release the next tick claims again.

    A :data:`RETRYABLE` release always is; otherwise its class decides (:data:`RETRIES`), counting every release of
    that class in *history*: ``code`` and an unowned ``error`` never are, a bounded class until its limit.
    """
    if not history or history[-1].state != 'error':
        return False
    last = history[-1]
    if last.description.startswith(RETRYABLE):
        return True
    owner = owner_of(last.state, last.description)
    if owner is None:
        return False
    limit = RETRIES[owner]
    spent = sum(1 for one in history if one.state == 'error' and owner_of(one.state, one.description) is owner)
    return spent <= limit
