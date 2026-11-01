"""DRAFT-UNTIL-READY (D53, user ruling 2026-11-01): a PR opens as a draft; only a ready PR is reviewed or merged.

The stateful fake forge (Gitea's shape) and a recording GitHub client: the evidence is what each forge was asked to
write. Every refusal has its planted control.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from _forge_state import StateForge
from test_dev_forgemerge_ready import _merge_ready, _pr
from test_dev_forgereview import _DECLARED, FakeCommand, _can, _forge, _work

from dev_lab.dev import forgedraft
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgedraft import STALE_DRAFT, alarms, mark_draft, mark_ready, opened_line
from dev_lab.dev.forgemerge import READY, ready
from dev_lab.dev.forgereview_command import Runner
from dev_lab.dev.forgeservesteps import raise_once
from dev_lab.dev.forgetakeover import review_run
from dev_lab.dev.forgework import ACTIONS_BOT, Client

_NOW = datetime(2026, 11, 1, 12, tzinfo=UTC)


class _Hub(Client):
    """A GitHub client recording every call and answering from *answers*."""

    def __init__(self, answers: dict[str, Any]) -> None:
        super().__init__(Forge('github.com', 'o', 'r'), 'T', sleep=lambda _s: None)
        self.answers, self.sent = answers, []

    def call(self, method: str, path: str, body: object = None, durable: object = None) -> object:
        del durable
        self.sent.append((method, path, body))
        return self.answers[f'{method} {path}']


def test_on_gitea_a_draft_is_the_wip_title_and_the_doors_move_it_both_ways() -> None:
    """Gitea 1.27 has no draft field: the door writes the prefix it reads. PLANTED CONTROL: ready reads ready."""
    forge = StateForge()
    number = forge.add_pull('pr/x', 'integrate/main', title='add x', sha='a' * 40)
    assert mark_draft(forge, number).draft
    assert forge.pulls[number]['title'] == 'WIP: add x'
    assert mark_draft(forge, number).title == 'WIP: add x', 'one prefix, never two'
    pull = mark_ready(forge, number)
    assert (pull.draft, pull.title) == (False, 'add x')


def test_on_github_the_doors_are_the_graphql_mutations_on_the_prs_node() -> None:
    hub = _Hub({'GET /repos/o/r/pulls/7': {'node_id': 'PR_n7'}, 'POST /graphql': {'data': {}}})
    hub.pr_view = lambda _n: None  # the answer's shape is the forge's; what was asked is the evidence
    mark_ready(hub, 7)
    mark_draft(hub, 7)
    queries = [body['query'] for method, path, body in hub.sent if (method, path) == ('POST', '/graphql')]
    assert ['markPullRequestReadyForReview' in queries[0], 'convertPullRequestToDraft' in queries[1]] == [True, True]
    assert {body['variables']['id'] for _, path, body in hub.sent if path == '/graphql'} == {'PR_n7'}


def test_pr_create_says_the_exact_next_step_for_a_draft() -> None:
    """PLANTED CONTROL: a PR opened ready says so, and names no door."""
    forge = StateForge()
    draft = forge.pr_create('add x', '', head='pr/x', base='integrate/main', draft=True)
    assert draft.draft
    assert opened_line(draft) == (
        f'opened #{draft.number} as a DRAFT: nothing reviews or merges it until '
        f'`python -m dev_lab.dev.forge pr ready {draft.number}`'
    )
    opened = forge.pr_create('add y', '', head='pr/y', base='integrate/main', draft=False)
    assert not opened.draft
    assert 'pr ready' not in opened_line(opened)


def test_merge_ready_refuses_a_draft_with_every_other_status_green(tmp_path: Path) -> None:
    """The draft's head shows WHY it waits (pending, naming the door). PLANTED CONTROL: marked ready, it is ready."""
    work, forge, number, head = _pr(tmp_path)
    mark_draft(forge, number)
    ready(work, forge, number)
    state, description = _merge_ready(forge, head)
    assert state == 'pending'
    assert description.startswith(f'draft: mark ready with `python -m dev_lab.dev.forge pr ready {number}`')
    mark_ready(forge, number)
    ready(work, forge, number)
    assert _merge_ready(forge, head) == ('success', READY)


def test_the_review_job_skips_a_draft_and_marking_ready_reviews_it(tmp_path: Path) -> None:
    """The Actions path (``review run``); the serve path is ``test_a_draft_is_skipped``. PLANTED CONTROL: ready runs."""
    work, head = _work(tmp_path)
    forge, number = _forge(head, draft=True)
    forge.login = ACTIONS_BOT  # a workflow job writes as the Actions bot: the forge itself
    command = FakeCommand()
    runner = Runner('runner-1', run=command, ready=_can)
    assert 'not reviewed' in review_run(work, forge, _DECLARED, number, base='integrate/main', runner=runner)
    assert command.ran == []
    forge.pulls[number]['draft'] = False  # what `forge pr ready` does on GitHub; its event re-runs this job
    review_run(work, forge, _DECLARED, number, base='integrate/main', runner=runner)
    assert len(command.ran) == 1


def _drafted(monkeypatch, age: timedelta) -> tuple[StateForge, int]:
    forge = StateForge()
    number = forge.add_pull('pr/x', 'integrate/main', title='WIP: add x', sha='a' * 40)
    monkeypatch.setattr(forgedraft, '_pushed', lambda _client, _sha: _NOW - age)
    return forge, number


def test_a_stale_draft_raises_one_integration_alarm_and_a_fresh_one_none(tmp_path: Path, monkeypatch) -> None:
    """PLANTED CONTROLS: a fresh draft raises nothing; the stale one pages once, not twice; a ready PR never."""
    forge, number = _drafted(monkeypatch, STALE_DRAFT - timedelta(minutes=1))
    assert alarms(tmp_path, forge, 'integrate/main', 'o/r', now=_NOW) == []
    forge, number = _drafted(monkeypatch, STALE_DRAFT + timedelta(minutes=1))
    (found,) = alarms(tmp_path, forge, 'integrate/main', 'o/r', now=_NOW)
    assert f'#{number}' in found.subject
    assert f'pr ready {number}' in found.body
    assert 'by a ' in found.body, 'names its author'
    paged: list[object] = []
    for _tick in range(2):
        raise_once(forge, 'integration', alarms(tmp_path, forge, 'integrate/main', 'o/r', now=_NOW), alarm=paged.append)
    assert len(paged) == 1
    mark_ready(forge, number)
    assert alarms(tmp_path, forge, 'integrate/main', 'o/r', now=_NOW) == []
