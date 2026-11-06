"""``forge review``: a session's advisory takeover, the ``again`` request, and the doors' verbs."""

from __future__ import annotations

from pathlib import Path

import pytest
from _branch_repos import advance
from _forge_fake import git_out, run_git
from _forge_state import StateForge
from test_dev_forgereview import FakeCommand, _forge, _output, _work

from dev_lab.dev.forgepulls import Marker, marker
from dev_lab.dev.forgereview_declared import EMPTY_COMMAND_FIX, PATHS_FIELD, RANGE_FIELD, Review
from dev_lab.dev.forgestatus import status_list, status_post
from dev_lab.dev.forgetakeover import LEDGER_TITLE, TakeoverRefused, ledger_of, main, pull_for, takeover
from dev_lab.dev.forgework import GITEA_ACTIONS_LOGIN
from dev_lab.dev.labsession import ENV as SESSION_ENV
from dev_lab.dev.platformparts import REVIEW_CONTEXT
from dev_lab.dev.reviewgate import RERUN

_SLICED = Review(command=('reviewer', '--range', RANGE_FIELD, '--paths', PATHS_FIELD), max_diff_bytes=10)
_WHOLE = Review(command=('reviewer', '--range', RANGE_FIELD))


@pytest.fixture(autouse=True)
def _integrator_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """The takeover is a SESSION's review: it names its session, never an unset one (#11 round 2)."""
    monkeypatch.setenv(SESSION_ENV, 'S-integrator')


def _latest(forge: object, sha: str, context: str) -> object:
    return next(one for one in status_list(forge, sha) if one.context == context)


def _open(tmp_path: Path) -> tuple[Path, StateForge, int, str]:
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    return work, forge, number, head


def _no_review(forge: object, sha: str) -> bool:
    return all(one.context != REVIEW_CONTEXT for one in status_list(forge, sha))


def test_the_takeover_posts_an_advisory_review_and_no_status(tmp_path: Path) -> None:
    """D11: a session's review never satisfies the merge; it is posted as advice, every slice naming its paths."""
    work, forge, number, head = _open(tmp_path)
    command = FakeCommand()
    said = takeover(
        work, forge, _SLICED, head, pull=pull_for(forge, head), base='integrate/main', host='box', run=command
    )
    ((argv, _),) = command.ran  # the one file over the slice cap is a slice of its own, never a path-less review
    assert argv[-1] == 'x.py'
    (comment,) = forge.comments[number]
    assert marker(Marker.REVIEW, head) in comment['body']
    assert 'Takeover' in comment['body']
    assert _no_review(forge, head), 'no status: advisory'
    assert RERUN in said[-1]


def test_no_reviewer_returning_findings_posts_nothing(tmp_path: Path) -> None:
    work, forge, number, head = _open(tmp_path)
    dead = FakeCommand(_output(reviewers=(('correctness', 'exhausted'),)))
    with pytest.raises(TakeoverRefused, match='no reviewer returned findings'):
        takeover(work, forge, _SLICED, head, pull=pull_for(forge, head), base='integrate/main', host='box', run=dead)
    assert forge.comments[number] == []


def test_the_door_plans_and_runs_the_takeover(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    work, forge, _, head = _open(tmp_path)
    sliced = (
        (work / 'pyproject.toml')
        .read_text(encoding='utf-8')
        .replace(
            "command = ['reviewer', '--range', '{range}', '--model', 'm']",
            "command = ['reviewer', '--range', '{range}', '--paths', '{paths}']\nmax_diff_bytes = 10",
        )
    )
    advance(work, 'integrate/main', 'pyproject.toml', sliced)  # a takeover acts on the base's review (review_at)
    fetched: list[int] = []
    assert main(['plan', head], cwd=work, client=forge, fetch=lambda _r, n: fetched.append(n)) == 0
    assert 'x.py' in capsys.readouterr().out
    assert main(['takeover', head], cwd=work, client=forge, run=FakeCommand(), fetch=lambda _r, _n: None) == 0
    assert _no_review(forge, head), 'advisory'
    assert fetched


def test_review_again_records_the_request_for_the_pr_head(tmp_path: Path) -> None:
    """``forge review again <pr>`` leaves ONE ``review-again`` marker keyed by the PR's head; nothing else moves.

    PLANTED CONTROL: before the request no comment carries the marker.
    """
    work, forge, number, head = _open(tmp_path)
    key = marker(Marker.REVIEW_AGAIN, head)
    assert not any(key in one['body'] for one in forge.comments.get(number, []))
    assert main(['again', str(number)], cwd=work, client=forge) == 0
    assert main(['again', str(number)], cwd=work, client=forge) == 0
    assert sum(key in one['body'] for one in forge.comments[number]) == 1, 'one request per head, upserted'
    assert _no_review(forge, head)


def test_the_retired_verbs_are_refused_by_the_parser(tmp_path: Path) -> None:
    """One-shot review (2026-11-06): no held, blocked or adjudicate verb, and no claim door, survives."""
    work, forge, _, _ = _open(tmp_path)
    for verb in (['held'], ['blocked'], ['adjudicate', '1']):
        with pytest.raises(SystemExit):
            main(verb, cwd=work, client=forge)


# --- the door must always be satisfiable (2026-10-31) ----------------------------------------------------


def _merged(tmp_path: Path) -> tuple[Path, object, int, str]:
    """``pr/x`` merged into ``integrate/main`` on origin, its PR closed, its review an ``error``: the head."""
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    run_git(work, 'checkout', '-q', '-B', 'landing', 'origin/integrate/main')
    run_git(work, 'merge', '-q', '--no-ff', '-m', 'chore(merge): pr/x', head)
    run_git(work, 'push', '-q', '--no-verify', 'origin', 'HEAD:refs/heads/integrate/main')
    run_git(work, 'fetch', '-q', 'origin')
    forge.pulls[number] |= {'state': 'closed'}
    status_post(forge, head, context=REVIEW_CONTEXT, state='error', description='the review command failed')
    return work, forge, number, head


def test_a_merged_prs_head_is_taken_over_over_its_own_change(tmp_path: Path) -> None:
    """ai-lab #3 / dev-lab #5: merged unreviewed, so the door must reach a CLOSED PR's head. PLANTED: x.py read."""
    work, forge, number, head = _merged(tmp_path)
    command = FakeCommand()
    takeover(work, forge, _WHOLE, head, pull=pull_for(forge, head), base='integrate/main', host='box', run=command)
    ((argv, _),) = command.ran
    base, _, tip = argv[-1].partition('..')
    assert tip == head
    assert 'x.py' in git_out(work, 'diff', '--name-only', f'{base}..{tip}'), 'the PR own change, not an empty range'
    assert _latest(forge, head, REVIEW_CONTEXT).state == 'error', 'advisory: the forge must re-run it'
    assert any(marker(Marker.REVIEW, head) in one['body'] for one in forge.comments[number])


def test_a_plain_break_glass_commit_is_taken_over_with_no_pr(tmp_path: Path) -> None:
    work, _ = _work(tmp_path)
    forge = StateForge()
    sha = advance(work, 'integrate/main', 'hot.py', 'x = 1\n', 'fix: hot\n\nBreak-Glass: forge down')
    command = FakeCommand()
    said = takeover(work, forge, _WHOLE, sha, pull=None, base='integrate/main', host='box', run=command)
    ((argv, _),) = command.ran
    assert argv[-1] == f'{git_out(work, "rev-parse", sha + "^")}..{sha}', 'its own change: from its parent'
    assert _no_review(forge, sha)
    assert sha[:12] in said[0]
    (issue,) = forge.titled(LEDGER_TITLE.format(sha=sha))
    assert any(marker(Marker.REVIEW, sha) in one['body'] for one in forge.comments[issue]), 'the findings persist'
    takeover(work, forge, _WHOLE, sha, pull=None, base='integrate/main', host='box', run=FakeCommand())
    assert forge.titled(LEDGER_TITLE.format(sha=sha)) == [issue], 'the same issue is reused, never a second one'


@pytest.mark.parametrize('poster', ['a', GITEA_ACTIONS_LOGIN])
def test_on_gitea_a_head_with_a_review_success_is_refused_whoever_posted_it(tmp_path: Path, poster: str) -> None:
    """User ruling 2026-11-06: Gitea vets no poster, so a user's success is as much the review as the job's.

    PLANTED CONTROL: the same head with its review an ``error`` is taken over (the two tests above).
    """
    work, forge, _, head = _merged(tmp_path)
    forge.login = poster
    status_post(forge, head, context=REVIEW_CONTEXT, state='success', description='reviewed')
    with pytest.raises(TakeoverRefused, match='already reviewed by the forge'):
        takeover(
            work, forge, _SLICED, head, pull=pull_for(forge, head), base='integrate/main', host='box', run=FakeCommand()
        )


def test_the_door_reads_the_repo_it_is_told_and_refuses_a_sha_it_lacks(tmp_path: Path) -> None:
    work, forge, _, head = _merged(tmp_path)
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    argv = ['takeover', head, '--repo', str(work)]
    assert main(argv, cwd=elsewhere, client=forge, run=FakeCommand(), fetch=lambda _r, _n: None) == 0
    assert any(marker(Marker.REVIEW, head) in one['body'] for comments in forge.comments.values() for one in comments)
    assert main(['takeover', 'f' * 40, '--repo', str(work)], cwd=elsewhere, client=forge, run=FakeCommand()) == 2


def test_the_takeover_in_a_repo_with_an_empty_command_names_the_same_fix(tmp_path: Path, capsys) -> None:
    work, forge, _, head = _merged(tmp_path)
    text = (work / 'pyproject.toml').read_text(encoding='utf-8')  # the base's declaration is what a takeover reads
    empty = text.replace("command = ['reviewer', '--range', '{range}', '--model', 'm']", 'command = []')
    advance(work, 'integrate/main', 'pyproject.toml', empty)
    (work / 'pyproject.toml').write_text(text, encoding='utf-8')
    assert main(['takeover', head], cwd=work, client=forge, run=FakeCommand(), fetch=lambda _r, _n: None) == 2
    assert EMPTY_COMMAND_FIX in capsys.readouterr().err


def test_the_pr_of_a_head_is_the_open_one_else_the_highest_number() -> None:
    """Round 1 F-dd9b6c166939: the forge's list order never decides. PLANTED: the open #1 beats the closed #3."""
    forge, sha = StateForge(), 'b' * 40
    for number_state in ('closed', 'closed'):
        forge.pulls[forge.add_pull('pr/x', 'integrate/main', sha=sha)] |= {'state': number_state}
    assert pull_for(forge, sha[:12]).number == max(forge.pulls)
    opened = StateForge()
    first = opened.add_pull('pr/x', 'integrate/main', sha=sha)
    later = opened.add_pull('pr/y', 'integrate/main', sha=sha)
    opened.pulls[later] |= {'state': 'closed'}
    assert pull_for(opened, sha).number == first
    assert pull_for(StateForge(), sha) is None


def test_a_head_the_checkout_lacks_is_fetched_through_its_pr_before_it_is_resolved(tmp_path: Path) -> None:
    """Round 1 F-edf20b5c6972: the forge is asked first, the PR fetched, then the sha resolved."""
    work, forge, _, _ = _merged(tmp_path)
    other = tmp_path / 'other'
    run_git(tmp_path, 'clone', '-q', str(tmp_path / 'origin.git'), str(other))
    unseen = advance(other, 'pr/y', 'y.py', 'y = 1\n')
    number = forge.add_pull('pr/y', 'integrate/main', title='add y', sha=unseen)
    fetched: list[int] = []

    def fetch(root: Path, pr: int) -> None:
        fetched.append(pr)
        run_git(root, 'fetch', '-q', 'origin', 'pr/y')

    assert main(['takeover', unseen[:12]], cwd=work, client=forge, run=FakeCommand(), fetch=fetch) == 0
    assert fetched == [number]
    assert any(marker(Marker.REVIEW, unseen) in one['body'] for one in forge.comments[number])


def test_a_ledger_issue_is_only_one_the_forge_itself_opened(tmp_path: Path) -> None:
    """F-7fbe6eafaadf (security): a squatter's issue, or a PR, titled like the ledger is never the ledger.

    Else anyone could open "review of commit <sha>" first and post a fake review there. PLANTED CONTROL: the
    forge's own issue of that title is found and reused.
    """
    work, _ = _work(tmp_path)
    forge = StateForge()
    sha = advance(work, 'integrate/main', 'hot.py', 'x = 1\n', 'fix: hot\n\nBreak-Glass: forge down')
    title = LEDGER_TITLE.format(sha=sha)
    squatter = forge.add_issue(title, 'fake ledger', user={'login': 'mallory'})
    pull = forge.add_issue(title, 'a PR, as the GitHub issues API lists one', user={'login': forge.login},
                           pull_request={'url': 'https://forge.example.org/o/r/pulls/1'})  # fmt: skip
    ledger = ledger_of(forge, sha, 'integrate/main')
    assert ledger.number not in {squatter, pull}
    assert forge.issues_by_number[ledger.number]['user']['login'] == forge.login
    assert ledger_of(forge, sha, 'integrate/main').number == ledger.number, 'the forge own issue is reused'


def test_the_offline_verbs_name_the_integration_without_asking_the_forge(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """dev-lab #40: ``plan``/``takeover`` read the default branch from ``origin/HEAD``, never ``GET /repos``.

    PLANTED control: no ``origin/HEAD`` refuses.
    """
    work, forge, _, head = _open(tmp_path)
    forge.default_branch = ''
    run_git(work, 'symbolic-ref', 'refs/remotes/origin/HEAD', 'refs/remotes/origin/integrate/main')
    assert main(['plan', head], cwd=work, client=forge, fetch=lambda _r, _n: None) == 0
    assert 'x.py' in capsys.readouterr().out
    run_git(work, 'symbolic-ref', '--delete', 'refs/remotes/origin/HEAD')
    assert main(['plan', head], cwd=work, client=forge, fetch=lambda _r, _n: None) == 2, 'no origin/HEAD refuses'
    assert 'origin/HEAD' in capsys.readouterr().err
