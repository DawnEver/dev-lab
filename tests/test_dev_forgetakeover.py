"""A head whose review could not run is the integrator's takeover: reviewed, and released only by the door."""

from __future__ import annotations

from pathlib import Path

import pytest
from _branch_repos import advance
from _forge_fake import git_out, run_git
from _forge_state import StateForge
from test_dev_forgereview import FakeCommand, _forge, _output, _work

from dev_lab.dev.forgepulls import Marker, comment_upsert, marker
from dev_lab.dev.forgereview import (
    EMPTY_COMMAND_FIX,
    NEEDS_MAINTAINER,
    PATHS_FIELD,
    RANGE_FIELD,
    REVIEW_CONTEXT,
    Review,
)
from dev_lab.dev.forgereview_command import Runner
from dev_lab.dev.forgestatus import status_list, status_post
from dev_lab.dev.forgetakeover import DOOR, RELEASED, TakeoverRefused, alarms, held, main, release, review_run, takeover
from dev_lab.dev.platformparts import HOLD_CONTEXT

_SLICED = Review(command=('reviewer', '--range', RANGE_FIELD, '--paths', PATHS_FIELD), max_diff_bytes=10)


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


def test_the_takeover_reviews_the_head_posts_and_releases(tmp_path: Path) -> None:
    work, forge, number, head = _held(tmp_path)
    command = FakeCommand()
    said = takeover(work, forge, _SLICED, head, base='integrate/main', host='box', run=command)
    ((argv, _),) = command.ran  # the one file over the slice cap: one whole-range review, no paths (D123)
    assert argv[-1] == '--paths'
    (comment,) = forge.comments[number]
    assert marker(Marker.REVIEW, head) in comment['body']
    assert _latest(forge, head, REVIEW_CONTEXT).state == 'success'
    hold = _latest(forge, head, HOLD_CONTEXT)
    assert (hold.state, hold.description) == ('success', f'{RELEASED} by box')
    assert RELEASED in said[-1]
    assert held(forge, 'integrate/main') == ()


def test_the_release_is_refused_without_a_findings_comment_for_the_sha(tmp_path: Path) -> None:
    """PLANTED control: the same release with the comment posted succeeds."""
    _, forge, number, head = _held(tmp_path)
    with pytest.raises(TakeoverRefused, match='no findings comment'):
        release(forge, head, host='box')
    assert _latest(forge, head, HOLD_CONTEXT).state == 'pending'
    comment_upsert(forge, number, kind=Marker.REVIEW, key='0' * 40, text=f'{marker(Marker.REVIEW, "0" * 40)}\nother')
    with pytest.raises(TakeoverRefused, match='no findings comment'):
        release(forge, head, host='box')  # a comment for ANOTHER sha is not this head's record
    comment_upsert(forge, number, kind=Marker.REVIEW, key=head, text=f'{marker(Marker.REVIEW, head)}\nfindings')
    release(forge, head, host='box')
    assert _latest(forge, head, HOLD_CONTEXT).state == 'success'


def test_an_open_head_with_no_review_and_no_hold_is_taken_over(tmp_path: Path) -> None:
    """A missing review is enough: the door no longer needs a hold to exist (2026-10-31)."""
    work, head = _work(tmp_path)
    forge, _ = _forge(head)
    said = takeover(work, forge, _SLICED, head, base='integrate/main', host='box', run=FakeCommand())
    assert len(said) == 1, 'no hold to release'
    assert _latest(forge, head, REVIEW_CONTEXT).state == 'success'


def test_no_reviewer_returning_findings_posts_nothing_and_the_hold_stands(tmp_path: Path) -> None:
    work, forge, number, head = _held(tmp_path)
    dead = FakeCommand(_output(reviewers=(('correctness', 'exhausted'),)))
    with pytest.raises(TakeoverRefused, match='no reviewer returned findings'):
        takeover(work, forge, _SLICED, head, base='integrate/main', host='box', run=dead)
    assert forge.comments[number] == []
    assert _latest(forge, head, HOLD_CONTEXT).state == 'pending'


def test_every_held_head_is_an_integrator_prompt_naming_the_door(tmp_path: Path) -> None:
    """PLANTED control: once released, the prompt is no longer derived."""
    work, forge, _, head = _held(tmp_path)
    (alarm,) = alarms(forge, 'integrate/main', 'o/r')
    assert alarm.kind == 'integration'
    assert DOOR.format(sha=head) in alarm.body
    takeover(work, forge, _SLICED, head, base='integrate/main', host='box', run=FakeCommand())
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
    assert DOOR.format(sha=head) in capsys.readouterr().out
    assert main(['plan', head], cwd=work, client=forge, fetch=lambda _r, n: fetched.append(n)) == 0
    assert 'x.py' in capsys.readouterr().out
    assert main(['takeover', head], cwd=work, client=forge, run=FakeCommand(), fetch=lambda _r, _n: None) == 0
    assert _latest(forge, head, HOLD_CONTEXT).state == 'success'
    assert main(['takeover', head], cwd=work, client=forge, run=FakeCommand(), fetch=lambda _r, _n: None) == 2
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
    takeover(work, forge, Review(command=('reviewer', '--range', RANGE_FIELD)), head, base='integrate/main',
             host='box', run=command)  # fmt: skip
    ((argv, _),) = command.ran
    base, _, tip = argv[-1].partition('..')
    assert tip == head
    assert 'x.py' in git_out(work, 'diff', '--name-only', f'{base}..{tip}'), 'the PR own change, not an empty range'
    assert _latest(forge, head, REVIEW_CONTEXT).state == 'success'
    assert any(marker(Marker.REVIEW, head) in one['body'] for one in forge.comments[number])


def test_a_plain_break_glass_commit_is_taken_over_with_no_pr(tmp_path: Path) -> None:
    work, _ = _work(tmp_path)
    forge = StateForge()
    sha = advance(work, 'integrate/main', 'hot.py', 'x = 1\n', 'fix: hot\n\nBreak-Glass: forge down')
    command = FakeCommand()
    said = takeover(work, forge, Review(command=('reviewer', '--range', RANGE_FIELD)), sha, base='integrate/main',
                    host='box', run=command)  # fmt: skip
    ((argv, _),) = command.ran
    assert argv[-1] == f'{git_out(work, "rev-parse", sha + "^")}..{sha}', 'its own change: from its parent'
    assert _latest(forge, sha, REVIEW_CONTEXT).state == 'success'
    assert sha[:12] in said[0]


def test_an_already_reviewed_head_is_refused(tmp_path: Path) -> None:
    """PLANTED CONTROL for the two above: the door runs only where the review is missing."""
    work, forge, _, head = _merged(tmp_path)
    status_post(forge, head, context=REVIEW_CONTEXT, state='success', description='reviewed')
    with pytest.raises(TakeoverRefused, match='already reviewed'):
        takeover(work, forge, _SLICED, head, base='integrate/main', host='box', run=FakeCommand())


def test_the_door_reads_the_repo_it_is_told_and_refuses_a_sha_it_lacks(tmp_path: Path) -> None:
    work, forge, _, head = _merged(tmp_path)
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    argv = ['takeover', head, '--repo', str(work)]
    assert main(argv, cwd=elsewhere, client=forge, run=FakeCommand(), fetch=lambda _r, _n: None) == 0
    assert _latest(forge, head, REVIEW_CONTEXT).state == 'success'
    assert main(['takeover', 'f' * 40, '--repo', str(work)], cwd=elsewhere, client=forge, run=FakeCommand()) == 2


def test_the_takeover_in_a_repo_with_an_empty_command_names_the_same_fix(tmp_path: Path, capsys) -> None:
    work, forge, _, head = _merged(tmp_path)
    manifest = work / 'pyproject.toml'
    text = manifest.read_text(encoding='utf-8')
    manifest.write_text(text.replace("command = ['reviewer', '--range', '{range}', '--model', 'm']", 'command = []'),
                        encoding='utf-8')  # fmt: skip
    assert main(['takeover', head], cwd=work, client=forge, run=FakeCommand(), fetch=lambda _r, _n: None) == 2
    assert EMPTY_COMMAND_FIX in capsys.readouterr().err
