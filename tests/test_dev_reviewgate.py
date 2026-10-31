"""REVIEW-IS-REQUIRED: one predicate decides whether a head is reviewed, for the merge AND for Break-Glass.

ai-lab #3 and dev-lab #5 (2026-10-31, ~16:45Z) were auto-merged with ``tests/review=error``: the merge called an
``error`` and a takeover-pending review "advisory". Every state but a posted ``success`` (with no hold pending)
blocks and names itself.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from _forge_state import StateForge
from test_dev_forgereview import _LANE_POLICY, _status, _work

from dev_lab.dev import breakglass
from dev_lab.dev.forgemerge import decide
from dev_lab.dev.forgestatus import status_list, status_post
from dev_lab.dev.platformparts import HOLD_CONTEXT, REVIEW_CONTEXT
from dev_lab.dev.reviewgate import review_missing

_SECURED = ('tests/security', 'success', 'nothing found')


@pytest.mark.parametrize(
    'review',
    [
        None,
        ('error', 'the review command failed (OSError)'),
        ('pending', 'takeover pending: no reviewer could run (diff exhausted)'),
        ('pending', 'claimed by box at 2026-10-31T16:40:00, reviewing'),
        ('failure', '1 blocking finding open'),
    ],
)
def test_every_review_state_but_success_blocks_the_merge_and_names_itself(tmp_path: Path, review) -> None:
    """PLANTED CONTROL: the same head with a posted success review is ready."""
    work, head = _work(tmp_path)
    policy = dataclasses.replace(_LANE_POLICY, pr_merges_since='0' * 40)
    rest = (_status(*_SECURED),)
    statuses = ((_status(REVIEW_CONTEXT, *review),) if review else ()) + rest
    assert review_missing(statuses) is not None
    found = decide(work, policy, branch='pr/x', number=1, head=head, statuses=statuses)
    assert not found.ready
    (line,) = [one for one in found.missing if REVIEW_CONTEXT in one]
    assert (review[1] if review else 'not posted') in line
    ok = (_status(REVIEW_CONTEXT, 'success', 'review round 1: no blocking finding open'), *rest)
    assert review_missing(ok) is None
    assert decide(work, policy, branch='pr/x', number=1, head=head, statuses=ok).ready


def test_a_pending_hold_blocks_a_successful_review_until_released() -> None:
    held = (_status(HOLD_CONTEXT, 'pending', 'held'), _status(REVIEW_CONTEXT, 'success', 'reviewed'))
    assert 'held' in review_missing(held)
    released = (_status(HOLD_CONTEXT, 'success', 'released by box'), *held[1:])
    assert review_missing(released) is None


def test_break_glass_and_the_merge_read_the_one_predicate() -> None:
    """Single source: neither module keeps a review rule of its own."""
    forge, head = StateForge(), 'a' * 40
    status_post(forge, head, context=REVIEW_CONTEXT, state='error', description='the review command failed')
    assert breakglass.unreviewed(forge, head) == review_missing(status_list(forge, head))
