"""A head's review CLAIM: who may take a head, what stands on it already, and a host that cannot run the review.

:mod:`dev_lab.dev.forgereview` claims a head (:data:`CLAIMED`) before it runs the command; every other host skips
it until the claim is released, goes stale, or the host posts :data:`HOST_UNABLE` -- a fact about the host, so the
head stays claimable.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final

from dev_lab.dev.forgecarry import RUNNING, docs_only
from dev_lab.dev.forgestatus import status_list, status_post
from dev_lab.dev.platformparts import REVIEW_CONTEXT

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from dev_lab.dev.forgestatus import CommitStatus
    from dev_lab.dev.forgework import Client, PullRequest

__all__ = ['CLAIMED', 'DESCRIPTION', 'HOST_UNABLE', 'RELEASED', 'claimable', 'passed', 'standing', 'unable']

#: The claim a host posts (``pending``) before it runs the command: every other host skips the head.
CLAIMED: Final = 'claimed by'

#: A claim given back by hand (``pending``): the head is free again at once.
RELEASED: Final = 'released by'

#: What an ``error`` says when THIS HOST cannot run the review (:class:`ReviewUnsupported`): a fact about the host,
#: not the head, so the head stays claimable -- by a capable host, or by this one once it is fixed.
HOST_UNABLE: Final = 'not reviewed: cannot run on host'

_CLAIM: Final = re.compile(rf'^{CLAIMED} (?P<host>\S+) at (?P<at>\S+), reviewing')

#: A commit-status description is short: every one posted is cut to this.
DESCRIPTION: Final = 240


def claimable(status: CommitStatus | None, now: datetime, stale: timedelta) -> bool:
    """Whether a head whose review status is *status* may be claimed: none, a released or stale claim, or a host unable.

    A host that could not run the review (:data:`HOST_UNABLE`) is the host's fault, never the head's.
    """
    if status is None or (status.state, status.description.startswith(HOST_UNABLE)) == ('error', True):
        return True
    if status.state != 'pending':
        return False
    if status.description.startswith(RELEASED):
        return True
    if (claim := _CLAIM.match(status.description)) is None:
        return False  # takeover pending, or any other pending: not ours to take
    try:
        at = datetime.fromisoformat(claim['at'])
    except ValueError:
        return True  # an unreadable claim cannot hold a head forever
    return now - at >= stale


def standing(client: Client, now: datetime, stale: timedelta) -> Callable[[str], CommitStatus | str]:
    """A sha's review as :func:`dev_lab.dev.forgecarry.docs_only` reads it: posted, live claim, else none."""

    def stood(sha: str) -> CommitStatus | str:
        latest = next((one for one in status_list(client, sha) if one.context == REVIEW_CONTEXT), None)
        if latest is not None and latest.state == 'success':
            return latest
        return RUNNING if latest is not None and latest.state == 'pending' and not claimable(latest, now, stale) else ''

    return stood


def passed(root: Path, client: Client, head: str, now: datetime, stale: timedelta) -> str | None:
    """Why *head* is not reviewed now: ``''`` its own review is posted or held, else what carries; ``None``: review it.

    DOCS-ONLY-CARRIES: an earlier head's review stands (posted on *head*, no command run) or is still running.
    """
    latest = next((one for one in status_list(client, head) if one.context == REVIEW_CONTEXT), None)
    if not claimable(latest, now, stale):
        return ''
    carry = docs_only(root, head, standing(client, now, stale), data_waits=False)
    if carry is not None and carry.verdict is not None:
        why = f'{carry.hold}: the review of {carry.source[:12]} stands'[:DESCRIPTION]
        status_post(client, head, context=REVIEW_CONTEXT, state=carry.verdict.state, description=why,
                    target_url=carry.verdict.url)  # fmt: skip
    return None if carry is None else carry.hold


def unable(client: Client, pull: PullRequest, host: str, why: str) -> str:
    """Post :data:`HOST_UNABLE` naming *host* and *why* on *pull*'s head (not again if it already says so); the line.

    The head stays claimable: another host, or this one once fixed, reviews it on a later tick.
    """
    head = pull.head_sha
    said = f'{HOST_UNABLE} {host}: {why}'[:DESCRIPTION]
    latest = next((one for one in status_list(client, head) if one.context == REVIEW_CONTEXT), None)
    if latest is None or (latest.state, latest.description) != ('error', said):
        status_post(client, head, context=REVIEW_CONTEXT, state='error', description=said)
    return f'#{pull.number} {head[:12]}: {said}'
