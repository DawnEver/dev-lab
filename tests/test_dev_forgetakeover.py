"""An over-cap head is the integrator's takeover: reviewed over every slice, and released only by the door."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_dev_forgereview import FakeCommand, _forge, _output, _tick, _work

from dev_lab.dev.forgepulls import Marker, comment_upsert, marker
from dev_lab.dev.forgereview import PATHS_FIELD, RANGE_FIELD, REVIEW_CONTEXT, Review
from dev_lab.dev.forgereview_scope import OVER_CAP_TAKEOVER
from dev_lab.dev.forgestatus import status_list
from dev_lab.dev.forgetakeover import DOOR, RELEASED, TakeoverRefused, alarms, held, main, release, takeover
from dev_lab.dev.platformparts import HOLD_CONTEXT

_SLICED = Review(command=('reviewer', '--range', RANGE_FIELD, '--paths', PATHS_FIELD), max_diff_bytes=10)


def _latest(forge: object, sha: str, context: str) -> object:
    return next(one for one in status_list(forge, sha) if one.context == context)


def _held(tmp_path: Path) -> tuple[Path, object, int, str]:
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    _tick(work, forge, FakeCommand(), _SLICED)  # one file over max_diff_bytes: held for the integrator
    assert _latest(forge, head, HOLD_CONTEXT).state == 'pending'
    assert _latest(forge, head, REVIEW_CONTEXT).description.startswith(OVER_CAP_TAKEOVER)
    return work, forge, number, head


def test_the_held_wording_names_the_integrator_takeover_and_no_hand() -> None:
    assert 'integrator takeover' in OVER_CAP_TAKEOVER
    assert 'review takeover' in OVER_CAP_TAKEOVER
    assert 'by hand' not in OVER_CAP_TAKEOVER


def test_the_takeover_reviews_every_slice_unmetered_posts_and_releases(tmp_path: Path) -> None:
    work, forge, number, head = _held(tmp_path)
    command = FakeCommand()
    said = takeover(work, forge, _SLICED, head, base='integrate/main', host='box', run=command)
    ((argv, _),) = command.ran  # the one file over the slice cap is a slice of its own, read by the session
    assert argv[-1] == 'x.txt'
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


def test_a_head_that_is_not_held_is_refused(tmp_path: Path) -> None:
    work, head = _work(tmp_path)
    forge, _ = _forge(head)
    with pytest.raises(TakeoverRefused, match='no pending'):
        takeover(work, forge, _SLICED, head, base='integrate/main', host='box', run=FakeCommand())


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
    assert 'x.txt' in capsys.readouterr().out
    assert main(['takeover', head], cwd=work, client=forge, run=FakeCommand(), fetch=lambda _r, _n: None) == 0
    assert _latest(forge, head, HOLD_CONTEXT).state == 'success'
    assert main(['takeover', head], cwd=work, client=forge, run=FakeCommand(), fetch=lambda _r, _n: None) == 2
    assert fetched
