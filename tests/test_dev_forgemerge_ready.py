"""ONE MERGE DECISION ON BOTH FORGES: a workflow job posts it as ``tests/merge-ready``; GitHub merges natively on it."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from _forge_state import StateForge
from test_dev_forgemerge import _MANIFEST, _work

from dev_lab.dev import forgecli, forgemerge
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgecontexts import MERGE_READY_CONTEXT, NOT_PARTS
from dev_lab.dev.forgemerge import EXTERNAL, READY, judged, ready
from dev_lab.dev.forgemessages import MESSAGES_NOT_DECLARED
from dev_lab.dev.forgereview_claim import UNREVIEWED_STATUS
from dev_lab.dev.forgestatus import status_list, status_post
from dev_lab.dev.forgework import GITEA_ACTIONS_LOGIN, Client, PullRequest
from dev_lab.dev.lanepolicy import load_policy
from dev_lab.dev.reviewcap import unreviewed_line

_INTEGRATOR = "[tool.dev_lab.integrator]\nintegration = 'integrate/main'\n"

_GREEN = (
    ('tests/base', 'scope=full ran=3 hands=-'),
    ('tests/review', 'reviewed abc: advice 1 HIGH, 0 MEDIUM, 0 LOW; none blocks'),
    ('tests/security', 'nothing found'),
    ('session-branch', 'pr/x is declared'),
    ('pr-current', 'pr/x holds origin/integrate/main'),
)


def _pr(
    tmp_path: Path, *, base: str = 'integrate/main', manifest: str = _MANIFEST + _INTEGRATOR, green: bool = True
) -> tuple[Path, StateForge, int, str]:
    work, head = _work(tmp_path)
    (work / 'pyproject.toml').write_text(manifest, encoding='utf-8')
    forge = StateForge()
    number = forge.add_pull('pr/x', base, sha=head)
    for context, description in _GREEN if green else _GREEN[:2]:
        forge.login = GITEA_ACTIONS_LOGIN if context == 'tests/review' else 'a'  # the review job: null creator
        status_post(forge, head, context=context, state='success', description=description)
    forge.login = 'a'
    return work, forge, number, head


def _merge_ready(forge: StateForge, head: str) -> tuple[str, str]:
    found = next(one for one in status_list(forge, head) if one.context == MERGE_READY_CONTEXT)
    return found.state, found.description


def test_a_green_pr_is_posted_ready_once_and_a_stale_red_decision_is_never_read_as_a_condition(tmp_path: Path) -> None:
    work, forge, number, head = _pr(tmp_path)
    status_post(forge, head, context=MERGE_READY_CONTEXT, state='failure', description='waits on: an earlier run')
    said = ready(work, forge, number)
    no_row = f'{READY} ({MESSAGES_NOT_DECLARED})'  # this PR's repo declares no message row
    assert _merge_ready(forge, head) == ('success', no_row)
    assert said.endswith(f'success: {no_row}')
    assert MERGE_READY_CONTEXT in NOT_PARTS, 'the decision is never a part'


def test_a_pr_missing_a_condition_is_posted_failure_naming_it(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same PR with tests/security green is ready (the test above)."""
    work, forge, number, head = _pr(tmp_path, green=False)
    ready(work, forge, number)
    state, description = _merge_ready(forge, head)
    assert state == 'failure'
    assert description.startswith('waits on: its security check: tests/security is not yet judged')


def test_a_pr_into_another_branch_than_integration_is_never_ready(tmp_path: Path) -> None:
    work, forge, number, head = _pr(tmp_path, base='main')
    ready(work, forge, number)
    assert _merge_ready(forge, head) == ('failure', 'waits on: a PR into integrate/main, not main')


def test_the_merge_noun_is_the_forge_cli_door(tmp_path: Path) -> None:
    work, forge, number, head = _pr(tmp_path)
    assert forgecli.NOUNS['merge'] is forgemerge.main
    assert forgemerge.main(['ready', '--pr', str(number)], cwd=work, client=forge) == 0
    assert _merge_ready(forge, head)[0] == 'success'


class _Asked(Client):
    """A client answering each call from *answers* by ``METHOD path`` and recording what it was sent."""

    def __init__(self, forge: Forge, answers: dict[str, Any]) -> None:
        super().__init__(forge, 'T', sleep=lambda _s: None)
        self.answers, self.sent = answers, []

    def call(self, method: str, path: str, body: object = None, durable: object = None) -> object:
        del durable
        self.sent.append((method, path, body))
        return self.answers[f'{method} {path}']


def test_on_github_a_created_pr_asks_for_native_auto_merge_as_a_merge_commit_and_on_gitea_nothing() -> None:
    hub = _Asked(
        Forge('github.com', 'o', 'r'), {'GET /repos/o/r/pulls/7': {'node_id': 'PR_n7'}, 'POST /graphql': {'data': {}}}
    )
    assert 'auto-merge enabled' in forgemerge.auto_merge(hub, 7)
    method, path, body = hub.sent[-1]
    assert (method, path, body['variables']) == ('POST', '/graphql', {'id': 'PR_n7'})
    assert 'enablePullRequestAutoMerge' in body['query']
    assert 'mergeMethod: MERGE' in body['query']
    hub.answers['POST /graphql'] = {'errors': [{'message': 'Auto merge is not allowed for this repository'}]}
    assert 'NOT enabled -- Auto merge is not allowed' in forgemerge.auto_merge(hub, 7)
    tea = _Asked(Forge('forge.example.org', 'o', 'r'), {})
    assert 'serve tick merges it' in forgemerge.auto_merge(tea, 7)
    assert tea.sent == []


_CI_MERGER = f'[tool.dev_lab.ci."{forgemerge.CI_MERGER}"]\n'


def test_on_gitea_the_merge_job_merges_a_ready_pr_only_where_the_repo_declares_it(tmp_path: Path) -> None:
    """P3: Gitea's merge job runs the same decision and merges; PLANTED CONTROL: undeclared, the job only posts."""
    work, forge, number, head = _pr(tmp_path)
    ready(work, forge, number)
    assert forge.merges == [], 'undeclared: the serve tick merges it'
    (work / 'pyproject.toml').write_text(_MANIFEST + _INTEGRATOR + _CI_MERGER, encoding='utf-8')
    said = ready(work, forge, number)
    [(merged, body)] = forge.merges
    assert merged == number
    assert (body['Do'], body['head_commit_id'], body['delete_branch_after_merge']) == ('merge', head, True)
    assert said.endswith('; merged')


def test_with_no_pr_the_door_judges_every_open_pr_into_integration(tmp_path: Path) -> None:
    work, forge, _number, head = _pr(tmp_path)
    elsewhere = 'e' * 40
    forge.add_pull('pr/y', 'main', sha=elsewhere)
    assert forgemerge.main(['ready'], cwd=work, client=forge) == 0
    assert _merge_ready(forge, head)[0] == 'success'
    assert [one for one in status_list(forge, elsewhere) if one.context == MERGE_READY_CONTEXT] == []


_HUB = Forge('github.com', 'o', 'r')


def _hub_pr(tmp_path: Path, *, green: bool = True) -> tuple[Path, StateForge, int, str]:
    work, head = _work(tmp_path)
    (work / 'pyproject.toml').write_text(_MANIFEST + _INTEGRATOR, encoding='utf-8')
    forge = StateForge(_HUB)
    number = forge.add_pull('pr/x', 'integrate/main', sha=head)
    for context, description in _GREEN if green else _GREEN[:2]:
        forge.login = 'github-actions[bot]' if context == 'tests/review' else 'a'
        status_post(forge, head, context=context, state='success', description=description)
    forge.login = 'github-actions[bot]'
    return work, forge, number, head


def test_on_github_a_ready_pr_is_merged_by_the_job_posting_ready_pinned_to_the_judged_head(tmp_path: Path) -> None:
    """Issue #15: GitHub refuses auto-merge on an already-mergeable PR, so the job that posts ready merges it."""
    work, forge, number, head = _hub_pr(tmp_path)
    hub = _Asked(_HUB, {'GET /repos/o/r/pulls/7': {'node_id': 'PR_n7'},
                        'POST /graphql': {'errors': [{'message': 'Pull request is in unstable status'}]}})  # fmt: skip
    assert 'NOT enabled -- Pull request is in unstable status' in forgemerge.auto_merge(hub, 7)
    said = ready(work, forge, number)
    assert _merge_ready(forge, head) == ('success', f'{READY} ({MESSAGES_NOT_DECLARED})')  # no message row declared
    [(merged, body)] = forge.merges
    assert merged == number
    assert (body['sha'], body['merge_method']) == (head, 'merge')
    assert body['commit_title'] == f'chore(merge): pr/x into integrate/main (#{number})'
    assert 'Merged-Branch: pr/x' in body['commit_message']
    assert forge.deleted_refs == ['pr/x']
    assert 'merged' in said


def test_on_github_a_red_decision_is_never_merged(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same PR with tests/security green is merged (the test above)."""
    work, forge, number, _head = _hub_pr(tmp_path, green=False)
    ready(work, forge, number)
    assert forge.merges == []


def test_on_github_a_head_moved_since_the_judgement_is_refused_by_the_forge_and_said(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work, forge, number, head = _hub_pr(tmp_path)
    original = forge.pr_view

    def moved(n: int) -> PullRequest:
        found = original(n)
        forge.pulls[n]['head']['sha'] = 'f' * 40  # a push lands between the judgement and the merge
        return found

    monkeypatch.setattr(forge, 'pr_view', moved)
    said = ready(work, forge, number)
    assert forge.merges == []
    assert forge.deleted_refs == []
    assert 'NOT merged' in said
    assert _merge_ready(forge, head)[0] == 'success'


def test_one_pr_whose_judgement_raises_never_stops_the_tick(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The second of three PRs raises: it is posted ``error`` naming why, the first and third are still judged."""
    work, forge, first, head = _pr(tmp_path)
    stuck = 'b' * 40
    second = forge.add_pull('pr/y', 'integrate/main', sha=stuck)
    third = forge.add_pull('pr/z', 'integrate/main', sha=head)
    judged, real = [], forgemerge.ready

    def flaky(root: Path, client: Client, number: int) -> str:
        judged.append(number)
        if number == second:
            raise subprocess.TimeoutExpired(['git', 'cat-file', '--batch'], 120)
        return real(root, client, number)

    monkeypatch.setattr(forgemerge, 'ready', flaky)
    assert forgemerge.main(['ready'], cwd=work, client=forge) == 2, 'a failed judgement still fails the tick'
    assert judged == [first, second, third]
    [said] = [one for one in status_list(forge, stuck) if one.context == MERGE_READY_CONTEXT]
    assert (said.state, said.description) == (
        'error',
        'could not be judged: `git cat-file --batch` timed out after 120 s',
    )
    assert _merge_ready(forge, head)[0] == 'success'


# --- INTERNAL-ONLY (user ruling 2026-11-05): only an internal PR is merged by the forge ----------------------------


def test_an_internal_pr_over_its_dollar_budget_merges_warned(tmp_path: Path) -> None:
    """The reviewing host's trusted record waives the review; the merge says it merged unreviewed."""
    work, forge, number, head = _hub_pr(tmp_path)
    status_post(forge, head, context='tests/review', state='pending', description=f'{UNREVIEWED_STATUS} budget')
    forge.issue_comment(number, unreviewed_line('review budget reached: 11.00/10.00 USD'))
    said = ready(work, forge, number)
    state, description = _merge_ready(forge, head)
    assert state == 'success'
    assert 'WARNED -- Unreviewed: review budget reached: 11.00/10.00 USD' in description
    [(merged, body)] = forge.merges
    assert merged == number
    assert 'Unreviewed: review budget reached: 11.00/10.00 USD' in body['commit_message']
    assert said.endswith('merged')


@pytest.mark.parametrize('record', ['trusted', 'none'])
def test_on_gitea_a_review_that_did_not_run_is_ready_warned_never_waiting_on_pending(
    tmp_path: Path, record: str
) -> None:
    """acme-consumer #5490 (2026-11-06): every reviewer was unsupported and the PR waited; it now merges Unreviewed.

    The Merge tick (an Actions job) posts ready, WARNED with the ``Unreviewed:`` line -- never a wait on the pending.
    PLANTED CONTROL: the same pending status with no trusted record is no waiver; it still holds.
    """
    work, forge, number, head = _pr(tmp_path)
    if record == 'trusted':
        forge.login = GITEA_ACTIONS_LOGIN
        forge.issue_comment(number, unreviewed_line('no reviewer returned findings (a unsupported)'))
    forge.login = 'a'
    status_post(forge, head, context='tests/review', state='pending', description=f'{UNREVIEWED_STATUS} x')
    forge.login = GITEA_ACTIONS_LOGIN
    ready(work, forge, number)
    state, description = _merge_ready(forge, head)
    if record == 'trusted':
        assert state == 'success'
        assert 'WARNED -- Unreviewed: no reviewer returned findings (a unsupported)' in description
    else:
        assert state == 'failure'
        assert description.startswith(f'waits on: its review: tests/review is pending: {UNREVIEWED_STATUS}')


def test_a_high_finding_never_holds_the_merge_and_a_security_one_does(tmp_path: Path) -> None:
    """User ruling 2026-11-06: findings are advice. PLANTED CONTROL: a security finding's failure holds the merge."""
    work, forge, number, head = _hub_pr(tmp_path)
    ready(work, forge, number)
    assert _merge_ready(forge, head)[0] == 'success', 'a success carrying HIGH advice is ready'
    (tmp_path / 'security').mkdir()
    work, forge, number, head = _hub_pr(tmp_path / 'security')
    status_post(forge, head, context='tests/review', state='failure', description='security finding(s) F-1')
    ready(work, forge, number)
    assert _merge_ready(forge, head)[0] == 'failure'
    assert forge.merges == []


def test_a_unreviewed_status_without_a_trusted_record_is_no_waiver(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same status, its record pasted by the PR author: the review still holds it."""
    work, forge, number, head = _hub_pr(tmp_path)
    status_post(forge, head, context='tests/review', state='pending', description=f'{UNREVIEWED_STATUS} budget')
    forge.login = 'a'
    forge.issue_comment(number, unreviewed_line('review budget reached: 11.00/10.00 USD'))
    forge.login = 'github-actions[bot]'
    ready(work, forge, number)
    assert _merge_ready(forge, head)[0] == 'failure'
    assert forge.merges == []


@pytest.mark.parametrize('how', ['non-writer', 'fork'])
def test_an_external_green_pr_is_never_merged_and_waits_on_a_maintainer(tmp_path: Path, how: str) -> None:
    """PLANTED CONTROL: the same green PR by the internal author merges (the GitHub ready test above)."""
    work, forge, number, head = _hub_pr(tmp_path)
    if how == 'fork':
        forge.pulls[number]['head']['repo'] = {'full_name': 'stranger/r'}
    else:
        forge.pulls[number]['user'] = {'login': 'stranger'}
    said = ready(work, forge, number)
    assert _merge_ready(forge, head) == ('pending', EXTERNAL)
    assert forge.merges == []
    assert said.endswith(f'pending: {EXTERNAL}')


@pytest.mark.parametrize('how', ['non-writer', 'fork'])
def test_gitea_vets_no_author_so_the_serve_tick_has_no_external_pr(tmp_path: Path, how: str) -> None:
    """Gitea is the private forge (user ruling 2026-11-06): nothing on it is external.

    Its Actions token cannot read team rosters, and every team writer's PR read as external. PLANTED CONTROL: the
    same PR on GitHub is external (the test above).
    """
    work, forge, number, head = _pr(tmp_path)
    if how == 'fork':
        forge.pulls[number]['head']['repo'] = {'full_name': 'stranger/r'}
    else:
        forge.pulls[number]['user'] = {'login': 'stranger'}
    found = judged(work, forge, load_policy(work), branch='pr/x', number=number, head=head)
    assert EXTERNAL not in found.missing
    assert found.ready


@pytest.mark.parametrize('poster', ['a', 'serve-host', 'github-actions[bot]'])
def test_on_gitea_a_review_success_counts_whoever_posted_it(tmp_path: Path, poster: str) -> None:
    """User ruling 2026-11-06, "Gitea is safe; vetting is for GitHub": an agent's or the serve's success counts.

    PLANTED CONTROL: the same success posted by the same non-bot login on GitHub waits on the review.
    """
    work, forge, number, head = _pr(tmp_path)
    forge.login = poster
    status_post(forge, head, context='tests/review', state='success', description='reviewed abc: advice; none blocks')
    assert judged(work, forge, load_policy(work), branch='pr/x', number=number, head=head).ready

    (tmp_path / 'hub').mkdir()
    hub_work, hub, hub_number, hub_head = _hub_pr(tmp_path / 'hub')
    hub.login = 'serve-host'
    status_post(hub, hub_head, context='tests/review', state='success', description='reviewed abc: advice; none blocks')
    found = judged(hub_work, hub, load_policy(hub_work), branch='pr/x', number=hub_number, head=hub_head)
    assert not found.ready
    assert any('tests/review' in one for one in found.missing)


def test_a_ready_status_without_a_message_row_says_messages_are_not_declared(tmp_path: Path) -> None:
    work, forge, number, head = _pr(tmp_path)
    ready(work, forge, number)
    state, description = _merge_ready(forge, head)
    assert state == 'success'
    assert description == f'{READY} ({MESSAGES_NOT_DECLARED})'
