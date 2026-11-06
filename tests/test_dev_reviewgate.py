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
from dev_lab.dev.forgemerge import decide, judged
from dev_lab.dev.forgereview_declared import review_from
from dev_lab.dev.forgereview_gate import review_gate
from dev_lab.dev.forgestatus import CommitStatus, status_list, status_post
from dev_lab.dev.forgework import ACTIONS_BOT, GITEA, GITEA_ACTIONS_LOGIN
from dev_lab.dev.platformparts import HOLD_CONTEXT, REVIEW_CONTEXT
from dev_lab.dev.reviewgate import (
    forge_posted,
    github_posted,
    job_run_url,
    post_review,
    posted_verdicts,
    review_missing,
    status_gate,
)

_BASE = 'integrate/main'
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
    rest = (_status(*_SECURED), _status('tests/base', 'success', 'scope=full ran=3 hands=-'))  # parts gate the merge
    statuses = ((_status(REVIEW_CONTEXT, *review),) if review else ()) + rest
    assert review_missing(statuses, github_posted) is not None
    found = decide(
        work, policy, branch='pr/x', number=1, head=head, statuses=statuses, reviewed=status_gate(github_posted)
    )
    assert not found.ready
    (line,) = [one for one in found.missing if REVIEW_CONTEXT in one]
    assert (review[1] if review else 'not posted') in line
    ok = (_status(REVIEW_CONTEXT, 'success', 'review round 1: no blocking finding open'), *rest)
    assert review_missing(ok, github_posted) is None
    assert decide(
        work, policy, branch='pr/x', number=1, head=head, statuses=ok, reviewed=status_gate(github_posted)
    ).ready


@pytest.mark.parametrize('creator', ['maintainer', 'a', ''])
def test_a_success_a_user_posted_never_satisfies_the_gate(tmp_path: Path, creator: str) -> None:
    """D11, F-e4d5c529db40: a PAT with GITHUB_ACTIONS=true in its env still posts AS ITS USER, and the forge says so.

    PLANTED CONTROL: the same success created by github-actions[bot] satisfies it.
    """
    work, head = _work(tmp_path)
    policy = dataclasses.replace(_LANE_POLICY, pr_merges_since='0' * 40)
    forged = (_status(REVIEW_CONTEXT, 'success', 'review round 1: clean', creator), _status(*_SECURED))
    said = review_missing(forged, github_posted)
    assert said is not None
    assert 'not by the forge' in said
    assert not decide(
        work, policy, branch='pr/x', number=1, head=head, statuses=forged, reviewed=status_gate(github_posted)
    ).ready
    real = (_status(REVIEW_CONTEXT, 'success', 'review round 1: clean'), _status(*_SECURED))
    assert review_missing(real, github_posted) is None


def test_github_status_list_reads_the_creator_the_forge_recorded() -> None:
    """The combined endpoint carries no creator: the gate reads the LIST. PLANTED CONTROL: the bot's post counts."""
    forge, head = StateForge(Forge('github.com', 'o', 'r')), 'c' * 40
    forge.login = 'maintainer'
    status_post(forge, head, context=REVIEW_CONTEXT, state='success', description='looks fine to me')
    assert breakglass.unreviewed(forge, head, base=_BASE) is not None
    forge.login = ACTIONS_BOT
    status_post(forge, head, context=REVIEW_CONTEXT, state='success', description='review round 1: clean')
    assert breakglass.unreviewed(forge, head, base=_BASE) is None


def _gitea_review(forge: StateForge, head: str, *, login: str, url: str) -> str | None:
    forge.login = login
    status_post(
        forge, head, context=REVIEW_CONTEXT, state='success', description='review round 1: clean', target_url=url
    )
    return breakglass.unreviewed(forge, head, base=_BASE)


@pytest.mark.parametrize('creator', ['DawnEver', 'ServeBot', ACTIONS_BOT, GITEA_ACTIONS_LOGIN])
@pytest.mark.parametrize(
    'url', ['', 'https://forge.example.org/o/r/pulls/1', 'https://forge.example.org/x/y/actions/runs/9']
)
def test_on_gitea_a_success_counts_whoever_posted_it(creator: str, url: str) -> None:
    """User ruling 2026-11-06, "Gitea is safe; vetting is for GitHub": Gitea vets no poster, nor what it links.

    PLANTED CONTROL: the same success on a GitHub forge counts only when its Actions bot posted it.
    """
    forge, head = StateForge(), 'd' * 40
    assert _gitea_review(forge, head, login=creator, url=url) is None
    github = StateForge(Forge('github.com', 'o', 'r'))
    github.login = creator
    status_post(
        github, head, context=REVIEW_CONTEXT, state='success', description='review round 1: clean', target_url=url
    )
    said = breakglass.unreviewed(github, head, base=_BASE)
    assert (said is None) == (creator == ACTIONS_BOT)
    if said is not None:
        assert 'not by the forge' in said


def test_the_job_names_its_own_run_as_the_forge_answers_it_and_nothing_outside_a_gitea_job() -> None:
    """The run's web URL is READ (its path is the run index on some releases, the id on others), never built.

    PLANTED CONTROL: without GITEA_ACTIONS, or on GitHub, there is no run to name.
    """
    forge, head = StateForge(), 'd' * 40
    run_id, run = forge.add_run(head)
    inside = {'GITEA_ACTIONS': 'true', 'GITHUB_RUN_ID': str(run_id)}
    assert job_run_url(forge, inside) == run
    assert job_run_url(forge, {'GITHUB_RUN_ID': str(run_id)}) == ''
    assert job_run_url(StateForge(Forge('github.com', 'o', 'r')), inside) == ''


def test_the_gitea_actions_login_is_the_one_gitea_reserves_for_its_actions_user() -> None:
    """Trusting comments by login is sound only because Gitea refuses that name to any account.

    Gitea ``models/user/user.go``: ``reservedUsernames`` ends ``"gitea-actions", // gitea builtin user (id: -2)``
    and ``IsUsableUsername`` refuses a reserved name; comments resolve their poster through ``GetPossibleUserByID``,
    which answers id -2 with that system user.
    """
    assert GITEA.actions_login == GITEA_ACTIONS_LOGIN == 'gitea-actions'


def test_on_github_a_null_creator_is_not_the_forge() -> None:
    """GitHub always names the creator: an unrecorded one is no forge identity there. PLANTED CONTROL: the bot."""
    github = StateForge(Forge('github.com', 'o', 'r'))
    assert forge_posted(github) is github_posted
    assert review_missing((_status(REVIEW_CONTEXT, 'success', 'clean', ''),), github_posted) is not None
    assert review_missing((_status(REVIEW_CONTEXT, 'success', 'clean'),), github_posted) is None


def test_a_pending_hold_blocks_a_successful_review_until_released() -> None:
    held = (_status(HOLD_CONTEXT, 'pending', 'held'), _status(REVIEW_CONTEXT, 'success', 'reviewed'))
    assert 'held' in review_missing(held, github_posted)
    released = (_status(HOLD_CONTEXT, 'success', 'released by box'), *held[1:])
    assert review_missing(released, github_posted) is None


def test_break_glass_and_the_merge_read_the_one_predicate() -> None:
    """Single source: neither module keeps a review rule of its own."""
    forge, head = StateForge(), 'a' * 40
    status_post(forge, head, context=REVIEW_CONTEXT, state='error', description='the review command failed')
    assert breakglass.unreviewed(forge, head, base=_BASE) == review_missing(
        status_list(forge, head), forge_posted(forge)
    )


def test_the_door_records_what_this_process_posted_and_nothing_outside_the_block() -> None:
    """dev-lab #38 F-9a36948d1771: the job's exit is read from the ONE posting door, never by sniffing the client.

    PLANTED CONTROL: a status posted around the door, and a post outside the block, are not recorded.
    """
    forge, head = StateForge(), 'f' * 40
    post_review(forge, head, state='success', description='outside')
    with posted_verdicts() as said:
        post_review(forge, head, state='pending', description='claimed')
        status_post(forge, head, context=REVIEW_CONTEXT, state='success', description='around the door')
        post_review(forge, head, state='failure', description='round 1')
    assert said == ['pending', 'failure']


# THE JUDGE MODE: a repo whose base declares ``where = "judge"`` is reviewed by its DECLARED judge's PR review.
_JUDGE_LOGIN = 'review-bot'
_JUDGED = f'[tool.dev_lab.review]\nwhere = "judge"\njudge_login = "{_JUDGE_LOGIN}"\n'


def _judge_repo(*, github: bool = False) -> tuple[StateForge, str, int]:
    forge = StateForge(Forge('github.com', 'o', 'r')) if github else StateForge()
    forge.pyproject_at[_BASE] = _JUDGED
    head = 'd' * 40
    return forge, head, forge.add_pull('pr/x', _BASE, sha=head)


def _gate(forge: StateForge, head: str) -> str | None:
    return review_gate(forge, head, base=_BASE)(status_list(forge, head))


@pytest.mark.parametrize('github', [False, True])
def test_a_judge_repo_is_reviewed_by_its_declared_judge_approving_this_head(*, github: bool) -> None:
    """PLANTED CONTROL for the waits below: the declared judge's APPROVED at this head passes, on either forge."""
    forge, head, number = _judge_repo(github=github)
    assert _gate(forge, head) is not None  # no review yet: waits
    forge.add_review(number, login=_JUDGE_LOGIN, state='APPROVED', commit=head)
    assert _gate(forge, head) is None
    assert breakglass.unreviewed(forge, head, base=_BASE) is None


@pytest.mark.parametrize(
    ('login', 'commit', 'later'),
    [
        (_JUDGE_LOGIN, 'e' * 40, None),  # approved an older head
        ('someone-else', 'd' * 40, None),  # approved by a login that is not the declared judge
        (_JUDGE_LOGIN, 'd' * 40, 'REQUEST_CHANGES'),  # the judge changed its mind after approving
    ],
)
def test_a_judge_repo_waits_on_any_approval_but_the_declared_judge_s_latest_at_this_head(
    login: str, commit: str, later: str | None
) -> None:
    forge, head, number = _judge_repo()
    forge.add_review(number, login=login, state='APPROVED', commit=commit)
    if later:
        forge.add_review(number, login=_JUDGE_LOGIN, state=later, commit=head)
    assert _gate(forge, head) is not None
    assert breakglass.unreviewed(forge, head, base=_BASE) is not None


def test_a_judge_repo_ignores_a_forged_tests_review_success() -> None:
    """A tests/review success, even the forge's own, is no review where the judge reviews."""
    forge, head, _ = _judge_repo()
    status_post(forge, head, context=REVIEW_CONTEXT, state='success', description='clean')
    assert _gate(forge, head) is not None


def test_a_pending_hold_still_blocks_a_judge_approved_head() -> None:
    forge, head, number = _judge_repo()
    forge.add_review(number, login=_JUDGE_LOGIN, state='APPROVED', commit=head)
    status_post(forge, head, context=HOLD_CONTEXT, state='pending', description='held')
    assert 'held' in _gate(forge, head)


def test_a_serve_repo_is_unaffected_by_a_judge_approval() -> None:
    """The serve gate is the one it was: an APPROVED review alone does not pass it; the forge's success does."""
    forge, head = StateForge(), 'a' * 40
    number = forge.add_pull('pr/x', _BASE, sha=head)
    forge.add_review(number, login=_JUDGE_LOGIN, state='APPROVED', commit=head)
    assert _gate(forge, head) == review_missing(status_list(forge, head), forge_posted(forge))
    assert _gate(forge, head) is not None


def test_a_judge_declaration_without_a_judge_login_is_refused() -> None:
    with pytest.raises(ValueError, match='judge_login'):
        review_from('[tool.dev_lab.review]\nwhere = "judge"\n', 'x')
    forge, head, _ = _judge_repo()
    forge.pyproject_at[_BASE] = '[tool.dev_lab.review]\nwhere = "judge"\n'
    with pytest.raises(ValueError, match='judge_login'):
        _gate(forge, head)
    with pytest.raises(ValueError, match='judge_login'):  # Break-Glass's forge_unreviewed names it as a reason
        breakglass.unreviewed(forge, head, base=_BASE)


@pytest.mark.parametrize('flag', ['dismissed', 'stale'])
def test_a_dismissed_or_stale_approval_does_not_pass_the_judge_gate(flag: str) -> None:
    """PLANTED CONTROL: the same approval, standing, passes (above)."""
    forge, head, number = _judge_repo()
    forge.add_review(number, login=_JUDGE_LOGIN, state='APPROVED', commit=head)
    forge.reviews[number][-1][flag] = True
    assert _gate(forge, head) is not None


def test_a_judge_base_without_a_login_is_the_merge_s_wait_never_its_crash(tmp_path: Path) -> None:
    work, head = _work(tmp_path)
    forge = StateForge()
    forge.pyproject_at[_LANE_POLICY.integration] = '[tool.dev_lab.review]\nwhere = "judge"\n'
    number = forge.add_pull('pr/x', _LANE_POLICY.integration, sha=head)
    found = judged(work, forge, _LANE_POLICY, branch='pr/x', number=number, head=head)
    assert any('judge_login' in line for line in found.missing)
