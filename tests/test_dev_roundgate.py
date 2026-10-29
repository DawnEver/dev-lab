"""ROUND-ENDS-GREEN: a session's round ends only when every head it pushed is green, or watched while pending."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from _branch_repos import clone_pair, commit
from _forge_fake import git_out, run_git
from _forge_state import StateForge

from dev_lab.dev import handback, roundgate
from dev_lab.dev.forgestatus import status_post
from dev_lab.dev.roundgate import pushed_heads, refusal, watched

SESSION = 'sess-0123456789'


def _pushed(tmp_path: Path, *, trailer: str = SESSION, branch: str = 'pr/x') -> tuple[Path, str]:
    _, work = clone_pair(tmp_path)
    run_git(work, 'checkout', '-q', '-B', branch, 'origin/main')
    (work / 'f.txt').write_text('f\n', encoding='utf-8')
    run_git(work, 'add', 'f.txt')
    run_git(work, 'commit', '-q', '-m', f'feat: f\n\nLab-Session: {trailer}')
    run_git(work, 'push', '-q', '--no-verify', 'origin', f'HEAD:refs/heads/{branch}')
    run_git(work, 'fetch', '-q', 'origin')
    return work, git_out(work, 'rev-parse', 'HEAD')


def _post(forge: StateForge, sha: str, state: str) -> None:
    status_post(forge, sha, context='tests/base', state=state, description='scope=full ran=1 hands=-')


def test_a_head_is_this_session_s_when_its_origin_tip_carries_the_session_trailer(tmp_path: Path) -> None:
    """PLANTED CONTROL: another session's tip, and an unpushed commit of this session, are not its heads."""
    work, head = _pushed(tmp_path)
    assert pushed_heads(work, SESSION) == {'pr/x': head}
    assert pushed_heads(work, 'another-session') == {}
    commit(work, 'g.txt', 'g\n')  # local only: never pushed, so no head of the round
    assert pushed_heads(work, SESSION) == {'pr/x': head}


def test_a_red_head_refuses_the_end_of_the_round_naming_it(tmp_path: Path) -> None:
    work, head = _pushed(tmp_path)
    forge = StateForge()
    _post(forge, head, 'failure')
    said = refusal(work, SESSION, forge, processes=lambda: ())
    assert said is not None
    assert 'ROUND-ENDS-GREEN' in said
    assert head[:12] in said
    assert 'red' in said


def test_a_pending_head_needs_a_live_background_watch_and_green_ends_the_round(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same pending head with a live `forge watch <sha>` process ends the round."""
    work, head = _pushed(tmp_path)
    forge = StateForge()
    _post(forge, head, 'pending')
    said = refusal(work, SESSION, forge, processes=lambda: ())
    assert said is not None
    assert f'-m dev_lab.dev.forge watch {head}' in said
    assert 'IN THE BACKGROUND' in said
    watching = (f'C:/x/.venv/Scripts/python.exe -m dev_lab.dev.forge watch {head} --deadline-minutes 120',)
    assert refusal(work, SESSION, forge, processes=lambda: watching) is None
    assert watched(head, ['python -m dev_lab.dev.forge watch ' + head[:12]]), 'a short sha is the same watch'
    assert not watched(head, ['python -m dev_lab.dev.forge status list ' + head])
    _post(forge, head, 'success')
    assert refusal(work, SESSION, forge, processes=lambda: ()) is None
    nothing = StateForge()
    assert refusal(work, SESSION, nothing, processes=lambda: ()) is not None, 'no status yet is pending, not green'


def test_a_session_without_an_id_or_without_pushed_heads_is_never_held(tmp_path: Path) -> None:
    work, head = _pushed(tmp_path)
    forge = StateForge()
    _post(forge, head, 'failure')
    assert refusal(work, '', forge, processes=lambda: ()) is None
    assert refusal(work, 'someone-else-0001', forge, processes=lambda: ()) is None


def test_the_stop_hook_blocks_once_with_the_round_gate_s_reason(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(handback, 'round_refusal', lambda _cwd: 'ROUND-ENDS-GREEN: pr/x is red')
    payload = {'cwd': str(tmp_path), 'last_assistant_message': 'done'}
    assert handback.main([], stdin=io.StringIO(json.dumps(payload))) == 0
    assert json.loads(capsys.readouterr().out) == {'decision': 'block', 'reason': 'ROUND-ENDS-GREEN: pr/x is red'}
    again = {**payload, 'stop_hook_active': True}
    assert handback.main([], stdin=io.StringIO(json.dumps(again))) == 0
    assert capsys.readouterr().out == ''


def test_the_round_gate_fails_open_when_the_forge_cannot_answer(tmp_path: Path, monkeypatch) -> None:
    work, _ = _pushed(tmp_path)
    monkeypatch.setenv('LAB_SESSION', SESSION)

    def unreachable(_root: Path) -> object:
        msg = 'no forge'
        raise OSError(msg)

    monkeypatch.setattr(roundgate, 'client_for', unreachable)
    assert roundgate.for_session(work) is None


@pytest.mark.parametrize('state', ['error', 'failure'])
def test_an_errored_part_is_red_too(tmp_path: Path, state: str) -> None:
    work, head = _pushed(tmp_path)
    forge = StateForge()
    _post(forge, head, state)
    assert 'red' in (refusal(work, SESSION, forge, processes=lambda: ()) or '')


def test_a_waiting_merge_decision_and_an_advisory_review_error_are_not_red(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same head with a blocking review (``failure``) is red."""
    work, head = _pushed(tmp_path)
    forge = StateForge()
    _post(forge, head, 'success')
    status_post(forge, head, context='tests/merge-ready', state='failure', description='waits on: its review')
    status_post(forge, head, context='tests/review', state='error', description='not reviewed: advisory')
    assert refusal(work, SESSION, forge, processes=lambda: ()) is None
    status_post(forge, head, context='tests/review', state='failure', description='round 1: 1 blocking')
    assert 'tests/review' in (refusal(work, SESSION, forge, processes=lambda: ()) or '')
