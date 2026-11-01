"""REVIEW-IS-REQUIRED: one predicate decides whether a head is reviewed, for the merge AND for Break-Glass.

ai-lab #3 and dev-lab #5 (2026-10-31, ~16:45Z) were auto-merged with ``tests/review=error``: the merge called an
``error`` and a takeover-pending review "advisory". Every state but a posted ``success`` (with no hold pending)
blocks and names itself. D11 (#11 round 3): that success counts only when the FORGE recorded its own identity as
the status's creator -- a user's token posting it, whatever environment it claimed, never satisfies the gate.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from _forge_state import StateForge
from test_dev_forgereview import _LANE_POLICY, _work

from dev_lab.dev import breakglass
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgemerge import decide
from dev_lab.dev.forgestatus import CommitStatus, status_list, status_post
from dev_lab.dev.forgework import ACTIONS_BOT, GITEA_ACTIONS_LOGIN
from dev_lab.dev.platformparts import HOLD_CONTEXT, REVIEW_CONTEXT
from dev_lab.dev.reviewgate import forge_creators, review_missing

_BOTS = frozenset({ACTIONS_BOT})
_SECURED = ('tests/security', 'success', 'nothing found')


def _status(context: str, state: str, description: str, creator: str = ACTIONS_BOT) -> CommitStatus:
    return CommitStatus(context, state, description, '', 1, creator)


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
    """PLANTED CONTROL: the same head with a forge-posted success review is ready."""
    work, head = _work(tmp_path)
    policy = dataclasses.replace(_LANE_POLICY, pr_merges_since='0' * 40)
    rest = (_status(*_SECURED),)
    statuses = ((_status(REVIEW_CONTEXT, *review),) if review else ()) + rest
    assert review_missing(statuses, _BOTS) is not None
    found = decide(work, policy, branch='pr/x', number=1, head=head, statuses=statuses, github=True)
    assert not found.ready
    (line,) = [one for one in found.missing if REVIEW_CONTEXT in one]
    assert (review[1] if review else 'not posted') in line
    ok = (_status(REVIEW_CONTEXT, 'success', 'review round 1: no blocking finding open'), *rest)
    assert review_missing(ok, _BOTS) is None
    assert decide(work, policy, branch='pr/x', number=1, head=head, statuses=ok, github=True).ready


@pytest.mark.parametrize('creator', ['maintainer', 'a', ''])
def test_a_success_a_user_posted_never_satisfies_the_gate(tmp_path: Path, creator: str) -> None:
    """D11, F-e4d5c529db40: a PAT with GITHUB_ACTIONS=true in its env still posts AS ITS USER, and the forge says so.

    PLANTED CONTROL: the same success created by github-actions[bot] satisfies it.
    """
    work, head = _work(tmp_path)
    policy = dataclasses.replace(_LANE_POLICY, pr_merges_since='0' * 40)
    forged = (_status(REVIEW_CONTEXT, 'success', 'review round 1: clean', creator), _status(*_SECURED))
    said = review_missing(forged, _BOTS)
    assert said is not None
    assert 'not by the forge' in said
    assert not decide(work, policy, branch='pr/x', number=1, head=head, statuses=forged, github=True).ready
    real = (_status(REVIEW_CONTEXT, 'success', 'review round 1: clean'), _status(*_SECURED))
    assert review_missing(real, _BOTS) is None


def test_github_status_list_reads_the_creator_the_forge_recorded() -> None:
    """The combined endpoint carries no creator: the gate reads the LIST. PLANTED CONTROL: the bot's post counts."""
    forge, head = StateForge(Forge('github.com', 'o', 'r')), 'c' * 40
    forge.login = 'maintainer'
    status_post(forge, head, context=REVIEW_CONTEXT, state='success', description='looks fine to me')
    assert breakglass.unreviewed(forge, head) is not None
    forge.login = ACTIONS_BOT
    status_post(forge, head, context=REVIEW_CONTEXT, state='success', description='review round 1: clean')
    assert breakglass.unreviewed(forge, head) is None


@pytest.mark.parametrize('creator', ['DawnEver', 'a', ACTIONS_BOT])
def test_on_gitea_only_the_actions_ghost_counts_and_a_named_user_never_does(creator: str) -> None:
    """Gitea records a job-token status as its Actions ghost and answers ``"creator": null`` (measured 2026-11-01).

    PLANTED CONTROL: DawnEver's success on the same head refuses; the null-creator success is the forge's.
    """
    assert forge_creators(github=False) == frozenset({''})
    forge, head = StateForge(), 'd' * 40
    forge.login = creator
    status_post(forge, head, context=REVIEW_CONTEXT, state='success', description='review round 1: clean')
    said = breakglass.unreviewed(forge, head)
    assert said is not None
    assert creator in said
    forge.login = GITEA_ACTIONS_LOGIN  # the job token: Gitea records the status as its Actions ghost
    status_post(forge, head, context=REVIEW_CONTEXT, state='success', description='review round 1: clean')
    assert breakglass.unreviewed(forge, head) is None


def test_on_github_a_null_creator_is_not_the_forge() -> None:
    """GitHub always names the creator: an unrecorded one is no forge identity there. PLANTED CONTROL: the bot."""
    assert forge_creators(github=True) == frozenset({ACTIONS_BOT})
    assert review_missing((_status(REVIEW_CONTEXT, 'success', 'clean', ''),), forge_creators(github=True)) is not None
    assert review_missing((_status(REVIEW_CONTEXT, 'success', 'clean'),), forge_creators(github=True)) is None


def test_a_pending_hold_blocks_a_successful_review_until_released() -> None:
    held = (_status(HOLD_CONTEXT, 'pending', 'held'), _status(REVIEW_CONTEXT, 'success', 'reviewed'))
    assert 'held' in review_missing(held, _BOTS)
    released = (_status(HOLD_CONTEXT, 'success', 'released by box'), *held[1:])
    assert review_missing(released, _BOTS) is None


def test_break_glass_and_the_merge_read_the_one_predicate() -> None:
    """Single source: neither module keeps a review rule of its own."""
    forge, head = StateForge(), 'a' * 40
    status_post(forge, head, context=REVIEW_CONTEXT, state='error', description='the review command failed')
    assert breakglass.unreviewed(forge, head) == review_missing(status_list(forge, head), forge_creators(github=False))
