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
from dev_lab.dev.forgework import ACTIONS_BOT, GITEA, GITEA_ACTIONS_LOGIN
from dev_lab.dev.platformparts import HOLD_CONTEXT, REVIEW_CONTEXT
from dev_lab.dev.reviewgate import forge_posted, github_posted, job_run_url, review_missing

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
    assert review_missing(statuses, github_posted) is not None
    found = decide(work, policy, branch='pr/x', number=1, head=head, statuses=statuses, posted=github_posted)
    assert not found.ready
    (line,) = [one for one in found.missing if REVIEW_CONTEXT in one]
    assert (review[1] if review else 'not posted') in line
    ok = (_status(REVIEW_CONTEXT, 'success', 'review round 1: no blocking finding open'), *rest)
    assert review_missing(ok, github_posted) is None
    assert decide(work, policy, branch='pr/x', number=1, head=head, statuses=ok, posted=github_posted).ready


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
    assert not decide(work, policy, branch='pr/x', number=1, head=head, statuses=forged, posted=github_posted).ready
    real = (_status(REVIEW_CONTEXT, 'success', 'review round 1: clean'), _status(*_SECURED))
    assert review_missing(real, github_posted) is None


def test_github_status_list_reads_the_creator_the_forge_recorded() -> None:
    """The combined endpoint carries no creator: the gate reads the LIST. PLANTED CONTROL: the bot's post counts."""
    forge, head = StateForge(Forge('github.com', 'o', 'r')), 'c' * 40
    forge.login = 'maintainer'
    status_post(forge, head, context=REVIEW_CONTEXT, state='success', description='looks fine to me')
    assert breakglass.unreviewed(forge, head) is not None
    forge.login = ACTIONS_BOT
    status_post(forge, head, context=REVIEW_CONTEXT, state='success', description='review round 1: clean')
    assert breakglass.unreviewed(forge, head) is None


def _gitea_review(forge: StateForge, head: str, *, login: str, url: str) -> str | None:
    forge.login = login
    status_post(
        forge, head, context=REVIEW_CONTEXT, state='success', description='review round 1: clean', target_url=url
    )
    return breakglass.unreviewed(forge, head)


@pytest.mark.parametrize('creator', ['DawnEver', 'a', ACTIONS_BOT])
def test_on_gitea_a_named_user_never_counts_even_naming_this_heads_run(creator: str) -> None:
    """A user's token is recorded under its user; only the job token's post is null (measured 2026-11-01).

    PLANTED CONTROL: the job's null-creator success naming the same run counts.
    """
    forge, head = StateForge(), 'd' * 40
    _, run = forge.add_run(head)
    said = _gitea_review(forge, head, login=creator, url=run)
    assert said is not None
    assert creator in said
    assert _gitea_review(forge, head, login=GITEA_ACTIONS_LOGIN, url=run) is None


@pytest.mark.parametrize(
    ('repo', 'at', 'url'),
    [
        ('o/r', 'd', ''),  # no run named: a deleted user's status is null too (F-4708098a59c5)
        ('o/r', 'd', 'https://forge.example.org/o/r/pulls/1'),  # a link, not a run
        ('x/y', 'd', None),  # another repository's run
        ('o/r', 'e', None),  # this repository's run at another head
        ('o/r', 'd', 'https://forge.example.org/o/r/actions/runs/99'),  # a run the forge does not list
    ],
)
def test_on_gitea_a_null_creator_counts_only_naming_a_run_of_this_repo_at_this_head(repo, at, url) -> None:
    """A null creator is ambiguous (a deleted user's status is null too): the target must be this head's run.

    PLANTED CONTROL: the same null-creator success naming this repository's run at this head counts, relative or
    absolute (Gitea's own job status names its run by a relative path).
    """
    forge, head = StateForge(), 'd' * 40
    _, foreign = forge.add_run(at * 40, repo=repo)
    said = _gitea_review(forge, head, login=GITEA_ACTIONS_LOGIN, url=foreign if url is None else url)
    assert said is not None
    assert 'not by the forge' in said
    _, run = forge.add_run(head)
    assert _gitea_review(forge, head, login=GITEA_ACTIONS_LOGIN, url=run) is None
    relative = run.removeprefix('https://forge.example.org') + '/jobs/3'
    assert _gitea_review(forge, head, login=GITEA_ACTIONS_LOGIN, url=relative) is None


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
    assert forge_posted(github, 'c' * 40) is github_posted
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
    assert breakglass.unreviewed(forge, head) == review_missing(status_list(forge, head), forge_posted(forge, head))
