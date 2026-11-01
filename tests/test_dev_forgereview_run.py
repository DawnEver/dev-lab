"""ONE REVIEW ON BOTH FORGES: a workflow job reviews its event's PR through the same round the serve tick runs."""

from __future__ import annotations

import base64
import os
import re
from pathlib import Path

import pytest
from _forge_state import StateForge
from test_dev_forgereview import _DECLARED, FakeCommand, _can, _forge, _work

from dev_lab.dev import forgereview_scope, reviewgitauth
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgereview import NEEDS_MAINTAINER, REVIEW_CONTEXT
from dev_lab.dev.forgereview_command import Runner
from dev_lab.dev.forgereview_rounds import trusted_bodies
from dev_lab.dev.forgestatus import status_list
from dev_lab.dev.forgetakeover import held, main, review_run, runtimes_with
from dev_lab.dev.forgework import ACTIONS_BOT
from dev_lab.dev.platformparts import HOLD_CONTEXT
from dev_lab.dev.reviewgate import review_missing

_RUNNER = Runner('runner-1', ready=_can)


def _latest(forge: StateForge, sha: str, context: str) -> tuple[str, str] | None:
    found = next((one for one in status_list(forge, sha) if one.context == context), None)
    return None if found is None else (found.state, found.description)


def test_a_job_reviews_its_one_pr_through_the_round_the_tick_runs(tmp_path: Path) -> None:
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    forge.login = ACTIONS_BOT  # a workflow job writes as the Actions bot: the forge itself
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
    forge.login = ACTIONS_BOT
    command = FakeCommand()
    secretless = Runner('runner-1', run=command, ready=_can, secret=False)
    review_run(work, forge, _DECLARED, number, base='integrate/main', runner=secretless)
    assert command.ran == []
    assert _latest(forge, head, REVIEW_CONTEXT) == ('pending', NEEDS_MAINTAINER)
    assert _latest(forge, head, HOLD_CONTEXT) == ('pending', NEEDS_MAINTAINER)
    statuses = status_list(forge, head)
    assert review_missing(statuses, frozenset({ACTIONS_BOT})) is not None, 'a held head is never skipped into a merge'
    assert [pull.number for pull in held(forge, 'integrate/main')] == [number], 'the takeover door lists it'
    (tmp_path / 'control').mkdir()
    other_work, other_head = _work(tmp_path / 'control')
    control, other = _forge(other_head)
    control.login = ACTIONS_BOT
    review_run(
        other_work, control, _DECLARED, other, base='integrate/main', runner=Runner('r', run=command, ready=_can)
    )
    assert len(command.ran) == 1
    assert _latest(control, other_head, HOLD_CONTEXT) is None


def test_the_cli_reads_the_secret_from_the_named_variable(tmp_path: Path, monkeypatch) -> None:
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    forge.login = ACTIONS_BOT
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


def _cannot(_argv, _root: Path) -> str:
    return "unsupported: the review command cannot import 'ai_lab.review' on this host"


def test_a_job_whose_host_cannot_run_the_command_holds_the_head_and_fails(tmp_path: Path) -> None:
    """A job whose host cannot run the review holds the head and fails; it never exits 0 silent.

    lab-commons #11 and dev-lab #3 (2026-10-31): the job said "not reviewed on this host", exited 0 and posted
    nothing, so the head waited for a review no host would ever post. A job is the ONLY reviewer of its PR: it
    holds the head for the takeover door and fails. PLANTED CONTROL: the same PR on a capable runner holds nothing.
    """
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    forge.login = ACTIONS_BOT
    command = FakeCommand()
    assert main(['run', '--pr', str(number)], cwd=work, client=forge, run=command, ready=_cannot) == 2
    assert command.ran == []
    state, why = _latest(forge, head, HOLD_CONTEXT)
    assert state == 'pending'
    assert 'ai_lab.review' in why
    assert _latest(forge, head, REVIEW_CONTEXT)[0] == 'pending'
    assert [pull.number for pull in held(forge, 'integrate/main')] == [number], 'the takeover door lists it'
    (tmp_path / 'control').mkdir()
    other_work, other_head = _work(tmp_path / 'control')
    control, other = _forge(other_head)
    control.login = ACTIONS_BOT
    assert main(['run', '--pr', str(other)], cwd=other_work, client=control, run=command, ready=_can) == 0
    assert _latest(control, other_head, HOLD_CONTEXT) is None
    assert _latest(control, other_head, REVIEW_CONTEXT)[0] == 'success'


@pytest.mark.parametrize(('job_session', 'state'), [('', 'success'), ('S-claimant', 'failure')])
def test_the_pull_request_job_rules_on_every_pending_claim_of_its_pr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, job_session: str, state: str
) -> None:
    """#11 deadlock: an issue_comment workflow runs only from the default branch, so a PR's own job must rule.

    The next pull_request run adjudicates the pending claim through the same judge, as the Actions bot.
    PLANTED CONTROL: a run carrying the claimant's own session still refuses to rule on its claim.
    """
    from test_dev_forgereview_rounds import _REVIEW, _doc, _finding  # noqa: PLC0415

    from dev_lab.dev.forgereview_dispose import dispose  # noqa: PLC0415
    from dev_lab.dev.forgereview_judge import Identity  # noqa: PLC0415
    from dev_lab.dev.labsession import ENV as SESSION_ENV  # noqa: PLC0415

    work, head = _work(tmp_path)
    forge = StateForge(Forge('github.com', 'o', 'r'))  # as #11: the job writes as the Actions bot
    number = forge.add_pull('pr/x', 'integrate/main', title='add x', sha=head)
    forge.login = ACTIONS_BOT
    monkeypatch.delenv(SESSION_ENV, raising=False)
    found = FakeCommand(_doc(_finding('F-x', severity='HIGH', file='x.py', anchor='x')))
    review_run(work, forge, _REVIEW, number, base='integrate/main', runner=Runner('r', run=found, ready=_can))
    assert _latest(forge, head, REVIEW_CONTEXT)[0] == 'failure'
    forge.login = 'mallory'  # PLANTED: a claim whose named login is not its forge-recorded author is never read
    dispose(forge, number, 'F-x', 'a false positive: the guard is upstream', by=Identity('a', 'box', 'S-claimant'))
    forge.login = ACTIONS_BOT
    assert 'refused' not in review_run(
        work, forge, _REVIEW, number, base='integrate/main', runner=Runner('r', run=found, ready=_can)
    )
    assert _latest(forge, head, REVIEW_CONTEXT)[0] == 'failure', 'nothing pending to rule on'
    forge.comments[number] = [c for c in forge.comments[number] if c['user']['login'] != 'mallory']
    forge.login = 'a'  # the claimant writes its own claim: the forge records it as a's
    dispose(forge, number, 'F-x', 'a false positive: the guard is upstream', by=Identity('a', 'box', 'S-claimant'))
    forge.login = ACTIONS_BOT
    if job_session:
        monkeypatch.setenv(SESSION_ENV, job_session)
    judge = FakeCommand(rulings={'F-x': ('false-positive', 'x.py:1 is guarded upstream')})
    said = review_run(work, forge, _REVIEW, number, base='integrate/main', runner=Runner('r', run=judge, ready=_can))
    assert _latest(forge, head, REVIEW_CONTEXT)[0] == state
    assert ('may not adjudicate it' in said) is bool(job_session)


class _EnvCommand(FakeCommand):
    """A FakeCommand recording the environment a real reviewer subprocess would inherit at each run."""

    def __init__(self) -> None:
        super().__init__()
        self.envs: list[dict[str, str]] = []

    def __call__(self, argv, root):  # noqa: ANN204 -- FakeCommand's own signature
        self.envs.append(dict(os.environ))
        return super().__call__(argv, root)


_TOKEN = 'tok-secret-123'  # noqa: S105 -- a planted value the scan looks for
_HEADER = 'Authorization: basic ' + base64.b64encode(f'x-access-token:{_TOKEN}'.encode()).decode()


def _forge_env(monkeypatch) -> None:
    monkeypatch.setattr(reviewgitauth, '_held', {})
    monkeypatch.setenv('FAMILY_READ_TOKEN', _TOKEN)
    monkeypatch.setenv('GITHUB_TOKEN', 'job-token')
    monkeypatch.setenv('GITHUB_SERVER_URL', 'https://forge.example')
    monkeypatch.setenv('GIT_CONFIG_COUNT', '1')
    monkeypatch.setenv('GIT_CONFIG_KEY_0', 'http.https://forge.example/.extraHeader')
    monkeypatch.setenv('GIT_CONFIG_VALUE_0', _HEADER)


def _leaks(env: dict[str, str]) -> list[str]:
    """The variables carrying the planted token, the job token or a GIT_CONFIG_* header slot."""
    slot = re.compile(r'GIT_CONFIG_(COUNT|KEY_\d+|VALUE_\d+)')
    return [k for k, v in env.items() if _TOKEN in v or v == 'job-token' or slot.fullmatch(k)]


def test_the_reviewer_inherits_no_forge_token_and_the_doors_git_carries_it(tmp_path: Path, monkeypatch) -> None:
    """F-5a82981c5f22. PLANTED CONTROL: without --git-token-env (the old door) the reviewer inherits every one."""
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    forge.login = ACTIONS_BOT
    _forge_env(monkeypatch)
    monkeypatch.setenv('REVIEW_KEY', 'k')
    gits: list[dict[str, str] | None] = []
    real = forgereview_scope._door.run

    def spy(argv, **kw):  # noqa: ANN202, ANN003
        if argv[0] == 'git':
            gits.append(kw.get('env'))
        return real(argv, **kw)

    monkeypatch.setattr(forgereview_scope._door, 'run', spy)
    command = _EnvCommand()
    argv = ['run', '--pr', str(number), '--secret-env', 'REVIEW_KEY']
    assert main([*argv, '--git-token-env', 'FAMILY_READ_TOKEN', '--git-token-env', 'GITHUB_TOKEN'],
                cwd=work, client=forge, run=command, ready=_can) == 0  # fmt: skip
    assert command.envs, 'the reviewer ran'
    assert all(not _leaks(env) for env in command.envs), [_leaks(env) for env in command.envs]
    assert gits, 'the door ran git'
    assert all(env is not None and env['GIT_CONFIG_VALUE_0'] == _HEADER for env in gits), 'the git calls carry it'
    assert all(env['GIT_CONFIG_KEY_0'] == 'http.https://forge.example/.extraHeader' for env in gits)

    (tmp_path / 'control').mkdir()
    other_work, other_head = _work(tmp_path / 'control')
    control, other = _forge(other_head)
    control.login = ACTIONS_BOT
    _forge_env(monkeypatch)
    leaky = _EnvCommand()
    assert main(['run', '--pr', str(other), '--secret-env', 'REVIEW_KEY'],
                cwd=other_work, client=control, run=leaky, ready=_can) == 0  # fmt: skip
    assert leaky.envs
    assert all(_leaks(env) for env in leaky.envs), 'PLANTED CONTROL: the old door leaks the token'


def test_no_token_holds_no_header_and_git_inherits(monkeypatch) -> None:
    monkeypatch.setattr(reviewgitauth, '_held', {})
    env = {'GITHUB_SERVER_URL': 'https://forge.example', 'GIT_CONFIG_COUNT': '1'}
    assert reviewgitauth.take(['FAMILY_READ_TOKEN'], env) is False
    assert env == {'GITHUB_SERVER_URL': 'https://forge.example'}
    assert reviewgitauth.git_env() is None
