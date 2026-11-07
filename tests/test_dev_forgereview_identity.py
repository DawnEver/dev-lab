"""WHO REVIEWS: only the forge posts ``tests/review``, and no session reviews a head it authored.

#11 round 2 (F-e97824b7b801). The stateful fake forge and real git; every refusal has its planted control.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from _branch_repos import advance
from _forge_state import StateForge
from _review_doubles import _doc, _state
from test_dev_forgereview import FakeCommand, _forge, _tick, _work

from dev_lab.dev._deny_status_row import STATUS_VIA_DOORS
from dev_lab.dev.forgereview_claim import DUE
from dev_lab.dev.forgereview_identity import Identity, ReviewerRefused, identity, ruling, self_review
from dev_lab.dev.forgestatus import status_list
from dev_lab.dev.forgework import ACTIONS_BOT
from dev_lab.dev.labsession import ENV as SESSION_ENV
from dev_lab.dev.platformparts import REVIEW_CONTEXT


def test_the_ci_identity_is_the_tokens_login_never_a_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Actions bot login is CI whatever the env says. PLANTED CONTROL: a developer login with a CI-looking env."""
    forge = StateForge()
    monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    monkeypatch.delenv(SESSION_ENV, raising=False)
    assert not identity(forge, 'box').ci, 'a variable never makes a developer the forge'
    forge.login = ACTIONS_BOT
    assert identity(forge, 'runner').ci
    forge.login = 'a'
    assert identity(forge, 'box', serving=True).ci, 'the serve process passes it from its own code path'


@pytest.mark.parametrize(
    'who', [Identity('a', 'box', 'S-author'), Identity('b', 'host2', 'S-third'), Identity('a', 'box')]
)
def test_only_the_forge_posts_a_review(who: Identity) -> None:
    """A session -- the author, a third one, an unset LAB_SESSION -- is refused. PLANTED CONTROL: the CI identity."""
    with pytest.raises(ReviewerRefused, match="the forge's review comes only from the forge"):
        ruling(who, 'reviewing #1')
    ruling(Identity('forge', 'ci', ci=True), 'reviewing #1')


def test_an_unset_session_may_not_self_review_and_the_ci_identity_may() -> None:
    """Fail closed: '' is no identity, never one 'different' from the author's. PLANTED CONTROL: the CI identity."""
    authors = frozenset({'S-author'})
    with pytest.raises(ReviewerRefused, match='names no session'):
        self_review(Identity('a', 'box'), authors, 'reviewing #1')
    with pytest.raises(ReviewerRefused, match='authored this head'):
        self_review(Identity('a', 'box', 'S-author'), authors, 'reviewing #1')
    self_review(Identity(ACTIONS_BOT, 'runner', ci=True), authors, 'reviewing #1')
    self_review(Identity('b', 'host2', 'S-other'), authors, 'reviewing #1')


def test_a_review_run_by_the_head_author_session_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The review is independent: nothing is posted. PLANTED CONTROL: the forge itself reviews the same head."""
    work, _ = _work(tmp_path)
    head = advance(work, 'pr/x', 'x.py', 'x\nz\n', message='feat: x\n\nLab-Session: S-author')
    forge, _ = _forge(head)
    monkeypatch.setenv(SESSION_ENV, 'S-author')
    command = FakeCommand(_doc())
    (said,) = _tick(work, forge, command)
    assert 'authored this head' in said
    assert command.ran == []
    reviewed = [one for one in status_list(forge, head) if one.context == REVIEW_CONTEXT]
    assert [one.description for one in reviewed] == [DUE], 'nothing is posted past the DUE'
    monkeypatch.delenv(SESSION_ENV)
    _tick(work, forge, FakeCommand(_doc()))
    assert _state(forge, head)[0] == 'success'


@pytest.mark.parametrize('context', ['tests/review', 'tests/review-hold'])
def test_a_raw_status_post_on_either_review_context_is_refused_to_agents(context: str) -> None:
    """PLANTED control: a post on a part context, and the review-again door, are permitted."""
    pattern = re.compile(STATUS_VIA_DOORS['pattern'])
    assert pattern.search(f'python -m dev_lab.dev.forge status post abc --context {context} --state success')
    assert not pattern.search('python -m dev_lab.dev.forge status post abc --context tests/fast --state success')
    assert not pattern.search('python -m dev_lab.dev.forge review again 7')
