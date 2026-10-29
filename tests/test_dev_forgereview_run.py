"""ONE REVIEW ON BOTH FORGES: a workflow job reviews its event's PR through the same round the serve tick runs."""

from __future__ import annotations

from pathlib import Path

import pytest
from _forge_state import StateForge
from test_dev_forgereview import _DECLARED, FakeCommand, _can, _forge, _work

from dev_lab.dev.forge import Forge
from dev_lab.dev.forgemerge import review_blocks, review_hold
from dev_lab.dev.forgereview import NEEDS_MAINTAINER, REVIEW_CONTEXT
from dev_lab.dev.forgereview_command import Runner
from dev_lab.dev.forgereview_rounds import trusted_bodies
from dev_lab.dev.forgestatus import status_list
from dev_lab.dev.forgetakeover import held, main, review_run, runtimes_with
from dev_lab.dev.forgework import ACTIONS_BOT
from dev_lab.dev.platformparts import HOLD_CONTEXT

_RUNNER = Runner('runner-1', ready=_can)


def _latest(forge: StateForge, sha: str, context: str) -> tuple[str, str] | None:
    found = next((one for one in status_list(forge, sha) if one.context == context), None)
    return None if found is None else (found.state, found.description)


def test_a_job_reviews_its_one_pr_through_the_round_the_tick_runs(tmp_path: Path) -> None:
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    command = FakeCommand()
    said = review_run(
        work, forge, _DECLARED, number, base='integrate/main', runner=Runner('runner-1', run=command, ready=_can)
    )
    assert said.startswith(f'#{number} {head[:12]}')
    assert len(command.ran) == 1
    assert _latest(forge, head, REVIEW_CONTEXT)[0] == 'success'
    again = review_run(
        work, forge, _DECLARED, number, base='integrate/main', runner=Runner('runner-1', run=command, ready=_can)
    )
    assert 'already reviewed' in again
    assert len(command.ran) == 1, 'one review per head, whoever triggers it'
    elsewhere = review_run(work, forge, _DECLARED, number, base='main', runner=_RUNNER)
    assert 'not reviewed' in elsewhere, 'only a PR into the PR base is reviewed'


def test_a_job_without_the_review_secret_holds_the_head_for_a_maintainer(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same PR with the secret present runs the command and holds nothing."""
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    command = FakeCommand()
    secretless = Runner('runner-1', run=command, ready=_can, secret=False)
    review_run(work, forge, _DECLARED, number, base='integrate/main', runner=secretless)
    assert command.ran == []
    assert _latest(forge, head, REVIEW_CONTEXT) == ('pending', NEEDS_MAINTAINER)
    assert _latest(forge, head, HOLD_CONTEXT) == ('pending', NEEDS_MAINTAINER)
    statuses = status_list(forge, head)
    assert review_hold(statuses) is not None
    assert review_blocks(statuses) is not None, 'a held head is never skipped into a merge'
    assert [pull.number for pull in held(forge, 'integrate/main')] == [number], 'the takeover door lists it'
    (tmp_path / 'control').mkdir()
    other_work, other_head = _work(tmp_path / 'control')
    control, other = _forge(other_head)
    review_run(
        other_work, control, _DECLARED, other, base='integrate/main', runner=Runner('r', run=command, ready=_can)
    )
    assert len(command.ran) == 1
    assert _latest(control, other_head, HOLD_CONTEXT) is None


def test_the_cli_reads_the_secret_from_the_named_variable(tmp_path: Path, monkeypatch) -> None:
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    monkeypatch.delenv('REVIEW_KEY', raising=False)
    assert main(['run', '--pr', str(number), '--secret-env', 'REVIEW_KEY'], cwd=work, client=forge) == 0
    assert _latest(forge, head, HOLD_CONTEXT) == ('pending', NEEDS_MAINTAINER)


def test_a_runtime_given_on_the_command_line_fills_the_host_value_a_runner_lacks() -> None:
    assert runtimes_with({'ai_lab': {'python': 'a'}}, ['ai_lab.python=b', 'x.y=z']) == {
        'ai_lab': {'python': 'b'},
        'x': {'y': 'z'},
    }
    with pytest.raises(ValueError, match=r'NAME.KEY=VALUE'):
        runtimes_with({}, ['ai_lab=python'])


def test_on_github_the_job_bots_comments_are_trusted_and_on_gitea_they_are_not() -> None:
    """PLANTED CONTROL: the same bot-authored ledger on a gitea forge is never read."""
    for forge, trusted in ((StateForge(Forge('github.com', 'o', 'r')), True), (StateForge(), False)):
        number = forge.add_pull('pr/x', 'main', sha='c' * 40)
        forge.comments[number] = []
        forge.login = ACTIONS_BOT
        forge.issue_comment(number, 'the ledger')
        forge.login = 'maintainer'
        forge.issue_comment(number, 'a disposition')
        assert ('the ledger' in ' '.join(trusted_bodies(forge, number))) is trusted
        assert any('a disposition' in body for body in trusted_bodies(forge, number))
