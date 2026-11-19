"""BATCHED REVIEW CALLS: the family's review commands make their model calls through the vendor's batch endpoint.

User ruling 2026-11-04: PR review model calls use the Message Batches API BY DEFAULT -- half the price, asynchronous
up to 24 h, usually minutes -- for every repo and host; ``[tool.dev_lab.review] batch = false`` keeps the
synchronous path (:data:`FAMILY_BATCH`). The method (ai-lab's ``ai_lab.batch``) does the batching; this module gives
it what a forge run must: a place its state survives in, and a budget it waits within.

* THE STATE LIVES ON THE PR (:func:`held_state`): one ``Marker.REVIEW_BATCH`` comment keyed by the head sha, read
  only from a TRUSTED author (the forge's own login and its Actions job; the judge host, its own login alone). It
  holds a seed and the batch ids the commands submitted -- no reply, no key -- so the next run of that head (a serve
  tick, a job re-run, a takeover, the judge's next tick) hands the same file to the same commands, and they resume
  polling those batches instead of resubmitting: no double spend.
* THE WAIT IS THE REVIEW'S OWN (:func:`within`): every command of a review shares ``batch_wait`` (one deadline, so a
  review of several slices never waits several times over); a command still waiting at the deadline exits
  :data:`~dev_lab.dev.forgereview_command.PENDING_EXIT`, raised as
  :class:`~dev_lab.dev.forgereview_command.ReviewPending`. The slices after it still SUBMIT (wait 0), so one more
  pass of polling settles all of them.
* NO FAKE VERDICT: a pending review posts no findings, no review comment and no verdict -- the head's review status is
  ``pending`` :data:`BATCH_PENDING` naming the batch, which the merge waits on and the next run may claim at once.
* THE TOTAL WAIT IS THE VENDOR'S expiry (24 h); past it the method answers each expired request synchronously or
  fails it, per ``on_expiry`` (:data:`ON_EXPIRY`, default :data:`FAMILY_ON_EXPIRY`).
"""

from __future__ import annotations

import contextlib
import json
import re
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons.temp import TEMP_PREFIX
from lab_commons.units import Q_

from dev_lab.dev.forgepulls import Marker, comment_list, comment_upsert, marker

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Sequence

    from dev_lab.dev.forgereview_declared import Review
    from dev_lab.dev.forgework import Client

__all__ = [
    'BATCH_FIELD',
    'BATCH_PENDING',
    'DEFAULT_BATCH_WAIT',
    'FAMILY_BATCH',
    'FAMILY_ON_EXPIRY',
    'NO_BATCH',
    'ON_EXPIRY',
    'WAIT_LEFT',
    'batch_args',
    'check_expiry',
    'held_state',
    'trusted_logins',
    'wait_of',
    'within',
]  # fmt: skip

#: Whether the family's review commands batch their model calls (user ruling 2026-11-04): ONE declared value; a repo
#: overrides it with ``batch = false``.
FAMILY_BATCH: Final = True

#: What an expired (24 h) or canceled batch request becomes: answered at once, or a failed reviewer.
ON_EXPIRY: Final = ('sync', 'fail')
FAMILY_ON_EXPIRY: Final = 'sync'

#: How long ONE review waits on its batches before it posts :data:`BATCH_PENDING` and ends: below the command's own
#: timeout, so a waiting command is never killed mid-poll.
DEFAULT_BATCH_WAIT: Final = '20 min'

#: Replaced by the batch flags (:func:`batch_args`) in the family's review, judge and bundle commands.
BATCH_FIELD: Final = '{batch}'

#: What :data:`BATCH_FIELD` becomes for a caller that keeps no state: it could not resume a batch, so it calls at once.
NO_BATCH: Final = ('--no-batch',)

#: Replaced when a command STARTS by the seconds left of its review's wait (:func:`within`).
WAIT_LEFT: Final = '{wait_left}'

#: What a ``pending`` review status opens with while a review's batch runs: the merge waits; the head is claimable.
BATCH_PENDING: Final = 'review batch pending, merge waits:'

_STATE: Final = re.compile(r'```json\n(?P<state>.*?)\n```', re.DOTALL)
_SAID: Final = (
    "The review's model calls of this head run as a vendor batch. This is their state -- the batch ids, no reply and "
    'no key -- so the next run resumes them instead of resubmitting.'
)


def check_expiry(value: str) -> None:
    """Refuse an ``on_expiry`` outside :data:`ON_EXPIRY`."""
    if value not in ON_EXPIRY:
        msg = f'on_expiry = {value!r} is not one of {ON_EXPIRY}'
        raise ValueError(msg)


def wait_of(review: Review) -> timedelta:
    """*review*'s ``batch_wait``; a bare number or a non-duration is refused naming it."""
    try:
        quantity = Q_(review.batch_wait)
    except Exception as bad:
        msg = f'batch_wait {review.batch_wait!r} is not a duration; write one such as "20 min"'
        raise ValueError(msg) from bad
    if not isinstance(quantity, Q_) or not quantity.check('[time]'):
        msg = f'batch_wait {review.batch_wait!r} is not a duration (it needs a unit); write one such as "20 min"'
        raise ValueError(msg)
    return timedelta(seconds=float(quantity.m_as('s')))


def batch_args(review: Review, state: Path) -> tuple[str, ...]:
    """What :data:`BATCH_FIELD` becomes for *review*: the batched flags over the *state* file, or :data:`NO_BATCH`."""
    if not review.batch:
        return NO_BATCH
    return ('--batch', '--batch-state', str(state), '--wait', WAIT_LEFT, '--on-expiry', review.on_expiry)


def within(
    run: Callable[..., str], deadline: datetime, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
) -> Callable[..., str]:  # fmt: skip
    """*run* with :data:`WAIT_LEFT` filled, as each command starts, by the whole seconds left until *deadline*."""

    def timed(argv: Sequence[str], *rest: object) -> str:
        left = str(max(0, int((deadline - clock()).total_seconds())))
        return run([left if arg == WAIT_LEFT else arg for arg in argv], *rest)

    return timed


def trusted_logins(client: Client) -> frozenset[str]:
    """Whose batch state a serve host or a review job reads: the forge's own login and its Actions job's."""
    return frozenset({client.whoami(), client.backend.actions_login})


def _stored(client: Client, number: int, head: str, trusted: Iterable[str]) -> str:
    line, allowed = marker(Marker.REVIEW_BATCH, head), set(trusted)
    for comment in comment_list(client, number):
        if comment.author in allowed and line in comment.body and (found := _STATE.search(comment.body)):
            return found['state']
    return ''


@contextlib.contextmanager
def held_state(client: Client, number: int, head: str, trusted: Iterable[str]) -> Iterator[Path]:
    """A state file for *head*'s review commands, seeded from the PR and written back to it when they changed it."""
    before = _stored(client, number, head, trusted)
    if before:
        json.loads(before)  # a stored state that is not JSON is refused here, never handed to a command
    with tempfile.TemporaryDirectory(prefix=f'{TEMP_PREFIX}review-batch-') as scratch:
        path = Path(scratch) / 'batch-state.json'
        if before:
            path.write_text(before + '\n', encoding='utf-8')
        try:
            yield path
        finally:
            after = path.read_text(encoding='utf-8').strip() if path.is_file() else ''
            if after and after != before.strip():
                comment_upsert(client, number, kind=Marker.REVIEW_BATCH, key=head,
                               text=f'{_SAID}\n\n```json\n{after}\n```')  # fmt: skip
