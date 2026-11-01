"""ONE MERGE DECISION ON BOTH FORGES: a workflow job posts it as ``tests/merge-ready``; GitHub merges natively on it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from _forge_state import StateForge
from test_dev_forgemerge import _MANIFEST, _work

from dev_lab.dev import forgecli, forgemerge
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgecontexts import MERGE_READY_CONTEXT, NOT_PARTS
from dev_lab.dev.forgemerge import READY, ready
from dev_lab.dev.forgestatus import status_list, status_post
from dev_lab.dev.forgework import GITEA_ACTIONS_LOGIN, Client, PullRequest

_INTEGRATOR = "[tool.dev_lab.integrator]\nintegration = 'integrate/main'\n"

_GREEN = (
    ('tests/base', 'scope=full ran=3 hands=-'),
    ('tests/review', 'review round 1: no blocking'),
    ('tests/security', 'nothing found'),
)


def _pr(
    tmp_path: Path, *, base: str = 'integrate/main', manifest: str = _MANIFEST + _INTEGRATOR, green: bool = True
) -> tuple[Path, StateForge, int, str]:
    work, head = _work(tmp_path)
    (work / 'pyproject.toml').write_text(manifest, encoding='utf-8')
    forge = StateForge()
    number = forge.add_pull('pr/x', base, sha=head)
    _, run = forge.add_run(head)
    for context, description in _GREEN if green else _GREEN[:2]:
        job = context == 'tests/review'  # the review job: null creator, naming its run at this head (D11)
        forge.login = GITEA_ACTIONS_LOGIN if job else 'a'
        status_post(
            forge, head, context=context, state='success', description=description, target_url=run if job else ''
        )
    forge.login = 'a'
    return work, forge, number, head


def _merge_ready(forge: StateForge, head: str) -> tuple[str, str]:
    found = next(one for one in status_list(forge, head) if one.context == MERGE_READY_CONTEXT)
    return found.state, found.description


def test_a_green_pr_is_posted_ready_once_and_a_stale_red_decision_is_never_read_as_a_condition(tmp_path: Path) -> None:
    work, forge, number, head = _pr(tmp_path)
    status_post(forge, head, context=MERGE_READY_CONTEXT, state='failure', description='waits on: an earlier run')
    said = ready(work, forge, number)
    assert _merge_ready(forge, head) == ('success', READY)
    assert said.endswith(f'success: {READY}')
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


@pytest.mark.parametrize('verb', ['ready'])
def test_the_merge_door_needs_a_pr(verb: str) -> None:
    with pytest.raises(SystemExit):
        forgemerge.main([verb])


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
    assert _merge_ready(forge, head) == ('success', READY)
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
