"""REVIEW IS THE LAST GATE (2026-11-05; M8 2026-11-06): the one review runs at the first MERGE-READY head.

The merge decision (``reviewturn.review_turn``) is the one that asks: WAITS naming what is missing, else DUE; the
review (``forgereview.review_pull``) runs only on DUE, so a head that cannot merge yet costs no model call, and a
push asks for nothing. The one-shot review has no rounds: each test counts command runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _branch_repos import advance
from _forge_state import StateForge
from test_dev_forgereview import _DECLARED, FakeCommand, _can, _work

from dev_lab.dev.ciworkflows import workflows
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgeheadgate import GATES
from dev_lab.dev.forgemerge import Decision, ready
from dev_lab.dev.forgereview_claim import DUE, WAITS
from dev_lab.dev.forgereview_command import Runner
from dev_lab.dev.forgereview_job import review_run
from dev_lab.dev.forgestatus import status_list, status_post
from dev_lab.dev.forgework import ACTIONS_BOT
from dev_lab.dev.labsession import ENV as SESSION_ENV
from dev_lab.dev.platformparts import REVIEW_CONTEXT
from dev_lab.dev.reviewturn import REVIEW_DUE_SAID, REVIEW_LABEL, review_turn

_BASE = 'integrate/main'
_PARTS = 'scope=full ran=3 hands=-'


@pytest.fixture(autouse=True)
def _outside_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('GITEA_ACTIONS', raising=False)
    monkeypatch.delenv(SESSION_ENV, raising=False)  # the forge reviews, never this session


def _pr(tmp_path: Path, *, parts: str = 'success') -> tuple[Path, StateForge, int, str]:
    work, head = _work(tmp_path)
    forge = StateForge()
    number = forge.add_pull('pr/x', _BASE, title='add x', sha=head)
    _settle(forge, head, parts=parts)
    return work, forge, number, head


def _settle(forge: StateForge, head: str, *, parts: str = 'success') -> None:
    status_post(forge, head, context='tests/base', state=parts, description=_PARTS)
    status_post(forge, head, context='tests/security', state='success', description='nothing found')
    for gate in GATES:  # the push-row gates, met
        status_post(forge, head, context=gate, state='success', description='holds')


def _review(forge: StateForge, head: str) -> tuple[str, str] | None:
    found = next((one for one in status_list(forge, head) if one.context == REVIEW_CONTEXT), None)
    return None if found is None else (found.state, found.description)


def _run(work: Path, forge: StateForge, number: int, command: FakeCommand) -> str:
    forge.login = ACTIONS_BOT  # the review is the forge's own job, never a session's
    try:
        return review_run(work, forge, _DECLARED, number, base=_BASE, runner=Runner('r', run=command, ready=_can))
    finally:
        forge.login = 'a'


def test_a_red_test_head_waits_unreviewed_and_spends_nothing(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same PR with its parts green is called due and reviewed (the test below)."""
    work, forge, number, head = _pr(tmp_path, parts='failure')
    said = ready(work, forge, number)
    state, why = _review(forge, head)
    assert (state, why.startswith(WAITS)) == ('pending', True), why
    assert 'its test parts' in why
    assert REVIEW_DUE_SAID not in said
    command = FakeCommand()
    assert 'not reviewed' in _run(work, forge, number, command)
    assert command.ran == [], 'no model call'
    assert forge.labeled == [], 'nothing asks for the review'


def test_a_conflicting_head_waits_unreviewed(tmp_path: Path) -> None:
    work, forge, number, _ = _pr(tmp_path)
    advance(work, _BASE, 'x.py', 'integration wrote it first\n')
    head = forge.pulls[number]['head']['sha']
    ready(work, forge, number)
    assert 'a clean merge' in _review(forge, head)[1]
    command = FakeCommand()
    _run(work, forge, number, command)
    assert command.ran == []


def test_a_merge_ready_head_is_called_due_and_reviewed_exactly_once(tmp_path: Path) -> None:
    work, forge, number, head = _pr(tmp_path)
    assert ready(work, forge, number).endswith(REVIEW_DUE_SAID)
    assert _review(forge, head) == ('pending', DUE)
    assert forge.labeled == [(number, REVIEW_LABEL)], "Gitea: the label's event starts review.yml"
    ready(work, forge, number)
    assert forge.labeled == [(number, REVIEW_LABEL)], 'asked once per head'
    command = FakeCommand()
    _run(work, forge, number, command)
    _run(work, forge, number, command)
    assert len(command.ran) == 1, 'reviewed once'
    assert _review(forge, head)[0] == 'success'
    ready(work, forge, number)
    assert _review(forge, head)[0] == 'success', 'the decision never overwrites the verdict'


def test_a_new_push_supersedes_and_waits_again(tmp_path: Path) -> None:
    work, forge, number, first = _pr(tmp_path)
    ready(work, forge, number)
    pushed = advance(work, 'pr/x', 'y.py', 'y\n')
    forge.pulls[number]['head']['sha'] = pushed
    command = FakeCommand()
    _run(work, forge, number, command)
    assert command.ran == [], 'a push asks for nothing'
    assert _review(forge, first) == ('pending', DUE), 'the superseded head is never reviewed'
    ready(work, forge, number)
    assert _review(forge, pushed)[1].startswith(WAITS), 'its parts are not yet posted'
    _settle(forge, pushed)
    ready(work, forge, number)
    assert _review(forge, pushed) == ('pending', DUE)
    assert forge.labeled[-1] == (number, REVIEW_LABEL)
    assert forge.issue_labels[number] == [1], 'the label re-applied, never doubled'
    _run(work, forge, number, command)
    assert len(command.ran) == 1


def test_inside_a_gitea_actions_job_the_decision_leaves_the_asking_to_a_serve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gitea starts no workflow for its Actions user's event: inside its job the decision posts no DUE.

    A DUE posted there would start nothing and stop a serve from asking.
    PLANTED CONTROL: outside Actions the same head is called due (the test above).
    """
    work, forge, number, head = _pr(tmp_path)
    monkeypatch.setenv('GITEA_ACTIONS', 'true')
    assert REVIEW_DUE_SAID in ready(work, forge, number)
    assert _review(forge, head) is None
    assert forge.labeled == []


def test_the_tick_is_what_starts_the_review_on_both_forges(tmp_path: Path) -> None:
    hub, tea = tmp_path / 'hub', tmp_path / 'tea'
    hub.mkdir()
    tea.mkdir()
    (hub / 'pyproject.toml').write_text('[tool.dev_lab.ci."merge-tick.yml"]\n', encoding='utf-8')
    (tea / 'pyproject.toml').write_text('[tool.dev_lab.ci."review.yml"]\n', encoding='utf-8')
    rendered = workflows(hub)
    ci, tick, gitea = rendered['ci.yml'], rendered['merge-tick.yml'], workflows(tea)['review.yml']
    assert ci['jobs']['review']['needs'] == ['merge-ready'], 'GitHub: the decision, then the review'
    assert "needs.merge-ready.outputs.due == 'true'" in ci['jobs']['review']['if']
    assert 'review' not in ci['jobs']['merge-ready']['needs']
    assert REVIEW_DUE_SAID in ' '.join(step.get('run', '') for step in ci['jobs']['merge-ready']['steps'])
    assert tick['jobs']['review']['needs'] == ['merge-tick']
    assert 'forge review run --due' in ' '.join(step.get('run', '') for step in tick['jobs']['review']['steps'])
    assert gitea['on'] == {'pull_request_target': {'types': ['labeled']}}, 'a push starts no Gitea review'
    assert REVIEW_LABEL in gitea['jobs']['review']['if']
    assert REVIEW_LABEL == 'review-due'


def test_a_head_whose_pr_holds_its_review_is_never_reviewed_again_when_called_due(tmp_path: Path) -> None:
    """One-shot: a later merge-ready head gets the standing verdict; only ``forge review again`` re-asks."""
    work, forge, number, _ = _pr(tmp_path)
    ready(work, forge, number)
    command = FakeCommand()
    _run(work, forge, number, command)
    assert len(command.ran) == 1
    pushed = advance(work, 'pr/x', 'x.py', 'z\n')  # the same size: under REVIEW_AGAIN_GROWTH, no growth re-review
    forge.pulls[number]['head']['sha'] = pushed
    _settle(forge, pushed)
    ready(work, forge, number)
    assert _review(forge, pushed) == ('pending', DUE)
    _run(work, forge, number, command)
    assert len(command.ran) == 1, 'the standing review stands: no second model call'
    assert _review(forge, pushed)[0] == 'success'


def test_on_github_a_users_success_is_no_review_and_the_decision_still_calls_it_due() -> None:
    """dev-lab #38 at the last gate: GitHub counts its Actions bot's review alone, so a token's success asks again.

    PLANTED CONTROL: the bot's own success stands; on Gitea the same user's success counts and stands.
    """
    decision = Decision(others=(), message='m', review='not reviewed')
    for host, poster, said in (
        ('github.com', 'a', REVIEW_DUE_SAID),
        ('github.com', ACTIONS_BOT, ''),
        ('forge.example.org', 'a', ''),
    ):
        forge = StateForge(Forge(host, 'o', 'r'))
        number = forge.add_pull('pr/x', _BASE, title='add x', sha='c' * 40)
        forge.login = poster
        status_post(forge, 'c' * 40, context=REVIEW_CONTEXT, state='success', description='clean')
        forge.login = ACTIONS_BOT
        assert review_turn(forge, number, 'c' * 40, decision, env={}) == said, (host, poster)
