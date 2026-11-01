"""A head whose review could not run is the integrator's takeover: reviewed, and released only by the door."""

from __future__ import annotations

from pathlib import Path

import pytest
from _branch_repos import advance
from _forge_fake import git_out, run_git
from _forge_state import StateForge
from test_dev_forgereview import JUDGE, FakeCommand, _forge, _output, _work

from dev_lab.dev.forgepulls import Marker, marker
from dev_lab.dev.forgereview import (
    EMPTY_COMMAND_FIX,
    NEEDS_MAINTAINER,
    PATHS_FIELD,
    RANGE_FIELD,
    REVIEW_CONTEXT,
    Review,
)
from dev_lab.dev.forgereview_command import Runner
from dev_lab.dev.forgereview_dispose import adjudicate_thread, dispose
from dev_lab.dev.forgereview_judge import Identity
from dev_lab.dev.forgestatus import status_list, status_post
from dev_lab.dev.forgetakeover import (
    LEDGER_TITLE,
    TakeoverRefused,
    alarms,
    held,
    ledger_of,
    main,
    pull_for,
    review_run,
    takeover,
)
from dev_lab.dev.forgework import GITEA_ACTIONS_LOGIN
from dev_lab.dev.labsession import ENV as SESSION_ENV
from dev_lab.dev.platformparts import HOLD_CONTEXT
from dev_lab.dev.reviewgate import RERUN

_SLICED = Review(judge=JUDGE, command=('reviewer', '--range', RANGE_FIELD, '--paths', PATHS_FIELD), max_diff_bytes=10)


@pytest.fixture(autouse=True)
def _integrator_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """The takeover is a SESSION's emergency review: it names its session, never an unset one (#11 round 2)."""
    monkeypatch.setenv(SESSION_ENV, 'S-integrator')


def _latest(forge: object, sha: str, context: str) -> object:
    return next(one for one in status_list(forge, sha) if one.context == context)


def _held(tmp_path: Path) -> tuple[Path, object, int, str]:
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    secretless = Runner('runner-1', run=FakeCommand(), ready=lambda _a, _r: None, secret=False)
    review_run(work, forge, _SLICED, number, base='integrate/main', runner=secretless)  # held for a maintainer
    assert _latest(forge, head, HOLD_CONTEXT).state == 'pending'
    assert _latest(forge, head, REVIEW_CONTEXT).description == NEEDS_MAINTAINER
    return work, forge, number, head


def _no_review(forge: object, sha: str) -> bool:
    return all(one.context != REVIEW_CONTEXT for one in status_list(forge, sha))


def test_the_takeover_posts_an_advisory_review_and_releases_nothing(tmp_path: Path) -> None:
    """D11: a session's review never satisfies the merge; the hold waits for the forge's own review."""
    work, forge, number, head = _held(tmp_path)
    command = FakeCommand()
    said = takeover(
        work, forge, _SLICED, head, pull=pull_for(forge, head), base='integrate/main', host='box', run=command
    )
    ((argv, _),) = command.ran  # the one file over the slice cap: one whole-range review, no paths (D123)
    assert argv[-1] == '--paths'
    (comment,) = forge.comments[number]
    assert marker(Marker.REVIEW, head) in comment['body']
    assert 'Emergency takeover' in comment['body']
    assert _latest(forge, head, REVIEW_CONTEXT).state == 'pending', 'no status: advisory'
    assert _latest(forge, head, HOLD_CONTEXT).state == 'pending', 'nothing released'
    assert RERUN in said[-1]
    assert [pull.number for pull in held(forge, 'integrate/main')] == [number]


def test_an_open_head_with_no_review_and_no_hold_is_taken_over(tmp_path: Path) -> None:
    """A missing review is enough: the door no longer needs a hold to exist (2026-10-31)."""
    work, head = _work(tmp_path)
    forge, _ = _forge(head)
    said = takeover(
        work, forge, _SLICED, head, pull=pull_for(forge, head), base='integrate/main', host='box', run=FakeCommand()
    )
    assert 'advisory' in said[0]
    assert _no_review(forge, head)


def test_no_reviewer_returning_findings_posts_nothing_and_the_hold_stands(tmp_path: Path) -> None:
    work, forge, number, head = _held(tmp_path)
    dead = FakeCommand(_output(reviewers=(('correctness', 'exhausted'),)))
    with pytest.raises(TakeoverRefused, match='no reviewer returned findings'):
        takeover(work, forge, _SLICED, head, pull=pull_for(forge, head), base='integrate/main', host='box', run=dead)
    assert forge.comments[number] == []
    assert _latest(forge, head, HOLD_CONTEXT).state == 'pending'


def test_every_held_head_is_an_integrator_prompt_naming_the_rerun(tmp_path: Path) -> None:
    """A takeover clears no prompt. PLANTED control: once the forge releases the hold, the prompt is gone."""
    work, forge, _, head = _held(tmp_path)
    (alarm,) = alarms(forge, 'integrate/main', 'o/r')
    assert alarm.kind == 'integration'
    assert RERUN in alarm.body
    takeover(
        work, forge, _SLICED, head, pull=pull_for(forge, head), base='integrate/main', host='box', run=FakeCommand()
    )
    assert len(alarms(forge, 'integrate/main', 'o/r')) == 1
    status_post(forge, head, context=HOLD_CONTEXT, state='success', description='released: review reviewed this head')
    assert alarms(forge, 'integrate/main', 'o/r') == []


def test_the_door_lists_held_heads_and_runs_the_takeover(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    work, forge, _, head = _held(tmp_path)
    (work / 'pyproject.toml').write_text(
        (work / 'pyproject.toml')
        .read_text(encoding='utf-8')
        .replace(
            "command = ['reviewer', '--range', '{range}', '--model', 'm']",
            "command = ['reviewer', '--range', '{range}', '--paths', '{paths}']\nmax_diff_bytes = 10",
        ),
        encoding='utf-8',
    )
    fetched: list[int] = []
    assert main(['held'], cwd=work, client=forge) == 1
    assert RERUN in capsys.readouterr().out
    assert main(['plan', head], cwd=work, client=forge, fetch=lambda _r, n: fetched.append(n)) == 0
    assert 'x.py' in capsys.readouterr().out
    assert main(['takeover', head], cwd=work, client=forge, run=FakeCommand(), fetch=lambda _r, _n: None) == 0
    assert _latest(forge, head, HOLD_CONTEXT).state == 'pending', 'advisory: the hold stands'
    assert fetched


# --- the emergency door must always be satisfiable (2026-10-31) ----------------------------------------


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
    review = Review(judge=JUDGE, command=('reviewer', '--range', RANGE_FIELD))
    takeover(work, forge, review, head, pull=pull_for(forge, head), base='integrate/main', host='box', run=command)
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
    review = Review(judge=JUDGE, command=('reviewer', '--range', RANGE_FIELD))
    said = takeover(work, forge, review, sha, pull=None, base='integrate/main', host='box', run=command)
    ((argv, _),) = command.ran
    assert argv[-1] == f'{git_out(work, "rev-parse", sha + "^")}..{sha}', 'its own change: from its parent'
    assert _no_review(forge, sha)
    assert sha[:12] in said[0]


def test_a_head_the_forge_reviewed_is_refused_and_a_users_success_is_not_that(tmp_path: Path) -> None:
    """PLANTED CONTROL for the two above: the door runs only where the FORGE's review is missing (D11)."""
    work, forge, _, head = _merged(tmp_path)
    status_post(forge, head, context=REVIEW_CONTEXT, state='success', description='reviewed')  # written by login a
    said = takeover(  # a's success is a user's, not the forge's
        work, forge, _SLICED, head, pull=pull_for(forge, head), base='integrate/main', host='box', run=FakeCommand()
    )
    assert 'advisory' in said[0]
    forge.login = GITEA_ACTIONS_LOGIN  # the review job: null creator, naming its run at this head
    status_post(forge, head, context=REVIEW_CONTEXT, state='success', description='reviewed',
                target_url=forge.add_run(head)[1])  # fmt: skip
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
    manifest = work / 'pyproject.toml'
    text = manifest.read_text(encoding='utf-8')
    manifest.write_text(text.replace("command = ['reviewer', '--range', '{range}', '--model', 'm']", 'command = []'),
                        encoding='utf-8')  # fmt: skip
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


def test_a_bare_commits_blocking_finding_is_disposed_in_its_ledger_issue(tmp_path: Path) -> None:
    """Round 1 F-4b489c18d9ab: a PR-less head's findings persist in ONE issue; a claim there is ADJUDICATED.

    PLANTED control: the claim alone moves nothing; only the forge's ruling posts a status.
    """
    work, _ = _work(tmp_path)
    forge = StateForge()
    sha = advance(work, 'integrate/main', 'x.py', 'x\n', 'fix: hot\n\nBreak-Glass: forge down')
    review = Review(judge=JUDGE, command=('reviewer', '--range', RANGE_FIELD))
    takeover(
        work,
        forge,
        review,
        sha,
        pull=None,
        base='integrate/main',
        host='box',
        run=FakeCommand(_output(severity='HIGH')),
    )
    assert _no_review(forge, sha), 'advisory: the takeover posts no status'
    (issue,) = forge.titled(LEDGER_TITLE.format(sha=sha))
    assert any(marker(Marker.REVIEW, sha) in one['body'] for one in forge.comments[issue]), 'the findings persist'
    claimant = Identity('a', 'box', 'S-claimant')
    dispose(forge, issue, 'F-0123456789ab', 'a false positive: x is the documented escape', by=claimant)
    assert _no_review(forge, sha), 'a claim moves no status'
    judge = FakeCommand(rulings={'F-0123456789ab': ('false-positive', 'x.py documents the escape')})
    adjudicate_thread(work, forge, review, issue, base='integrate/main', adjudicator=Identity('forge', 'ci', ci=True),
                      run=judge, runtimes={})  # fmt: skip
    assert _latest(forge, sha, REVIEW_CONTEXT).state == 'success'
    # the same issue is reused, never a second one
    status_post(forge, sha, context=REVIEW_CONTEXT, state='error', description='re-run')
    takeover(work, forge, review, sha, pull=None, base='integrate/main', host='box', run=FakeCommand())
    assert forge.titled(LEDGER_TITLE.format(sha=sha)) == [issue]


def test_a_ledger_issue_is_only_one_the_forge_itself_opened(tmp_path: Path) -> None:
    """F-7fbe6eafaadf (security): a squatter's issue, or a PR, titled like the ledger is never the ledger.

    Else anyone could open "review of commit <sha>" first and post a fake round or ruling there. PLANTED CONTROL:
    the forge's own issue of that title is found and reused.
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
