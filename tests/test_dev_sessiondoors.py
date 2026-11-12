"""SESSION-HEARS-ITS-PRS, the doors: the door that acts records, and a turn does not end with its PRs unwatched.

2026-11-12: a PostToolUse hook scraping the shell line missed a second ``forge pr create`` in one command, a
create whose output was piped through ``| tail -1``, and a push after ``cd`` into another repository -- each
silently. Each test below plants its control beside the refusal or record it asserts.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
from typing import TYPE_CHECKING

import pytest
from _forge_fake import git_out
from _forge_state import FORGE, StateForge

from dev_lab.dev import forgewatch, pushstop, sessionprs
from dev_lab.dev.forge import Forge
from dev_lab.dev.githooks.table import base_rows

if TYPE_CHECKING:
    from pathlib import Path

SHA = 'a' * 40
SESSION = 's1'


@pytest.fixture
def in_session(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv(sessionprs.SESSION_ENV, SESSION)
    return SESSION


def _hook(command: str, *, session: str = SESSION, cwd: str = '') -> str | None:
    payload = {'hook_event_name': 'PostToolUse', 'session_id': session, 'cwd': cwd,
               'tool_input': {'command': command}, 'tool_response': {'stdout': '', 'stderr': ''}}  # fmt: skip
    out = io.StringIO()

    with contextlib.redirect_stdout(out):
        assert sessionprs.main([], stdin=io.StringIO(json.dumps(payload))) == 0
    text = out.getvalue().strip()
    return json.loads(text)['hookSpecificOutput']['additionalContext'] if text else None


# ---------------------------------------------------------------------------------------------------- PR create


def test_two_creates_in_one_command_are_both_recorded_with_no_url_printed(in_session: str) -> None:
    forge = StateForge()
    first = forge.pr_create('a', '', head='pr/a', base='main', draft=False)
    second = forge.pr_create('b', '', head='pr/b', base='main', draft=False)
    keys = set(sessionprs.rows(in_session))
    assert keys == {f'{FORGE.identity}#{first.number}', f'{FORGE.identity}#{second.number}'}
    said = _hook('py -m dev_lab.dev.forge pr create --head pr/a ... && py -m dev_lab.dev.forge pr create | tail -1')
    assert said is not None
    assert sessionprs.watch_session_command(in_session) in said, 'the hook names the one watch to arm'


def test_a_create_outside_a_session_records_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    """PLANTED CONTROL: no CLAUDE_CODE_SESSION_ID (conftest removes it), so the same door writes no record."""
    StateForge().pr_create('a', '', head='pr/a', base='main', draft=False)
    assert sessionprs.rows(SESSION) == {}
    assert capsys.readouterr().err == '', 'no session is not a failure: nothing to say'


def test_a_create_whose_record_fails_says_so_and_still_opens_the_pr(
    in_session: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(*_a: object, **_k: object) -> None:
        said = 'home is read-only'
        raise PermissionError(said)

    monkeypatch.setattr(sessionprs, '_save', refuse)
    opened = StateForge().pr_create('a', '', head='pr/a', base='main', draft=False)
    assert opened.number, 'the PR is open either way'
    err = capsys.readouterr().err
    assert f'#{opened.number} NOT recorded for session {in_session}' in err
    assert 'home is read-only' in err


def test_an_invalid_session_id_is_said_not_swallowed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(sessionprs.SESSION_ENV, '../escape')
    StateForge().pr_create('a', '', head='pr/a', base='main', draft=False)
    assert 'is not a session id' in capsys.readouterr().err


# ---------------------------------------------------------------------------------------------------- push


def _repo(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    root.mkdir()
    git_out(root, 'init', '-q')
    git_out(root, 'remote', 'add', 'origin', f'https://f.example/o/{name}.git')
    return root


def _pre_push(root: Path, *lines: str) -> int:
    """What the family pre-push row runs, in the repository git is pushing (the runner's cwd is its root)."""
    return sessionprs.main(['--push', str(root)], stdin=io.StringIO(''.join(f'{line}\n' for line in lines)))


def test_a_push_after_cd_is_recorded_against_the_pushed_repo_never_the_shells_cwd(
    tmp_path: Path, in_session: str
) -> None:
    here, other = _repo(tmp_path, 'here'), _repo(tmp_path, 'other')
    assert _hook(f'cd {other} && git push origin pr/x', cwd=str(here)) is not None
    assert sessionprs.rows(in_session) == {}, 'the shell hook attributes nothing from its cwd'
    assert _pre_push(other, f'refs/heads/pr/x {SHA} refs/heads/pr/x {"0" * 40}') == 0
    (row,) = sessionprs.rows(in_session).values()
    assert row.forge == Forge('f.example', 'o', 'other')
    assert (row.branch, row.sha) == ('pr/x', SHA)


def test_a_deletion_and_a_push_outside_a_session_record_nothing(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same row records nothing without a session, nor for a deleted branch."""
    other = _repo(tmp_path, 'other')
    _pre_push(other, f'refs/heads/pr/x {SHA} refs/heads/pr/x {"0" * 40}')
    assert sessionprs.rows(SESSION) == {}
    os.environ[sessionprs.SESSION_ENV] = SESSION
    try:
        _pre_push(other, f'(delete) {"0" * 40} refs/heads/pr/x {SHA}')
    finally:
        del os.environ[sessionprs.SESSION_ENV]
    assert sessionprs.rows(SESSION) == {}


def test_a_push_to_a_remote_naming_no_forge_says_so(
    tmp_path: Path, in_session: str, capsys: pytest.CaptureFixture[str]
) -> None:
    bare = tmp_path / 'bare'
    bare.mkdir()
    git_out(bare, 'init', '-q')
    assert _pre_push(bare, f'refs/heads/pr/x {SHA} refs/heads/pr/x {"0" * 40}') == 0, 'the push goes through'
    assert f'push of pr/x in {bare} NOT recorded for session {in_session}' in capsys.readouterr().err


def test_the_family_pre_push_table_runs_the_session_row_on_every_branch() -> None:
    row = {raw['id']: raw for raw in base_rows()['pre-push']}['session-prs']
    assert row['run'] == ['python', '-m', 'dev_lab.dev.sessionprs', '--push']
    assert row['always_run']
    assert row['refs'] == '^refs/heads/'


# ---------------------------------------------------------------------------------------------------- the hook


@pytest.mark.usefixtures('in_session')
def test_a_push_or_create_leaving_no_open_pr_on_record_is_a_warning() -> None:
    said = _hook('git -C ../lab-commons push origin pr/y')
    assert said is not None
    assert 'WARNING' in said
    assert sessionprs.SESSION_ENV in said
    assert _hook('git status && ls') is None, 'PLANTED CONTROL: a command that neither pushes nor creates is silent'


# ---------------------------------------------------------------------------------------------------- the Stop


_FORGE = StateForge()


def _stop(session: str = SESSION) -> dict | None:
    out = io.StringIO()
    payload = {'hook_event_name': 'Stop', 'cwd': '', 'session_id': session}
    pushstop.main([], stdin=io.StringIO(json.dumps(payload)), processes=lambda: (), client=lambda _r: _FORGE,
                  clients=lambda _f: _FORGE, out=out)  # fmt: skip
    return json.loads(out.getvalue()) if out.getvalue().strip() else None


def test_an_open_session_pr_with_no_live_watch_blocks_every_stop_naming_the_monitor(in_session: str) -> None:
    _FORGE.pr_create('a', '', head='pr/a', base='main', draft=False)
    for _ in range(2):
        block = _stop()
        assert block is not None
        assert block['decision'] == 'block'
        assert sessionprs.watch_session_command(in_session) in block['reason']
    sessionprs.watch(in_session)
    assert _stop() is None, 'PLANTED CONTROL: a live watch lifts the refusal'
    sessionprs.watch(in_session, pid=2**22 + 7)  # a pid no process holds
    assert _stop() is not None, 'a marker whose process is gone is no watch'
    sessionprs.unwatch(in_session)
    assert _stop('other') is None, 'PLANTED CONTROL: a session with no open PR is never held'


def test_the_session_watch_holds_the_liveness_marker_while_it_runs_and_drops_it_after(in_session: str) -> None:
    _FORGE.pr_create('w', '', head='pr/w', base='main', draft=False)
    held: list[bool] = []

    def sleep(_s: float) -> None:
        held.append(sessionprs.watching(in_session))
        for pull in _FORGE.pulls.values():
            pull.update(state='closed', merged=True)

    assert not sessionprs.watching(in_session), 'PLANTED CONTROL: no watch, no marker'
    forgewatch.watch_session(in_session, clients=lambda _f: _FORGE, say=lambda _l: None, every_s=0,
                             deadline_s=60, clock=lambda: 0.0, sleep=sleep)  # fmt: skip
    assert held == [True]
    assert not sessionprs.watching(in_session), 'an ended watch leaves no marker'
