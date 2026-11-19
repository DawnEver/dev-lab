"""TASK-HEARS-ITS-FORGE-EVENTS through ONE machine hearer (dev-lab#581, D79).

A harness ``Monitor`` dies after 30 minutes, so a session waiting on a long PR was refused at every stop. One
watcher per machine polls every session's PRs, appends each change to the session's inbox and beats; a session is
heard while the beat is fresh and covers its open PRs. Each test plants its control.
"""

from __future__ import annotations

import io
import json
import os
from types import SimpleNamespace

import pytest
from _forge_state import FORGE, StateForge

from dev_lab.dev import forgefeed, sessionprs, taskbinding
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgestatus import status_post

SHA = 'a' * 40


@pytest.fixture(autouse=True)
def _no_declared_repositories(monkeypatch: pytest.MonkeyPatch) -> None:
    """The PR-status tests hear no repository listing: the machine file's ``[repos]`` is never this box's."""
    monkeypatch.setattr(forgefeed, '_forges', list)


def _open(forge: StateForge, session: str = 's1', branch: str = 'pr/x') -> str:
    number = forge.add_pull(branch, 'main', sha=SHA)
    assert sessionprs.record_pr(session, FORGE, number, branch=branch, sha=SHA)
    return f'{FORGE.identity}#{number}'


def test_one_poll_delivers_each_change_to_its_own_sessions_inbox_once() -> None:
    forge = StateForge()
    key = _open(forge, 's1')
    other = _open(forge, 's2', 'pr/y')
    status_post(forge, SHA, context='tests/base', state='failure', description='boom')
    forgefeed.poll_once(clients=lambda _f: forge, now=100.0)
    forgefeed.poll_once(clients=lambda _f: forge, now=200.0)
    mine = forgefeed.take_unread('s1')
    assert len(mine) == 1
    assert mine[0].startswith(key)
    assert 'failure' in mine[0]
    assert other not in ''.join(mine), "PLANTED CONTROL: another session's PR never reaches this inbox"
    assert forgefeed.take_unread('s1') == [], 'a read event is not surfaced again'


def test_the_beat_hears_a_session_only_while_fresh_live_and_covering(monkeypatch: pytest.MonkeyPatch) -> None:
    forge = StateForge()
    _open(forge)
    assert not forgefeed.heard('s1', now=0.0), 'PLANTED CONTROL: no beat, nothing heard'
    with forgefeed.held() as mine:
        assert mine
        forgefeed.poll_once(clients=lambda _f: forge, now=1000.0)
        assert forgefeed.heard('s1', now=1000.0 + forgefeed.FRESH_S - 1)
        assert not forgefeed.heard('s1', now=1000.0 + forgefeed.FRESH_S + 1), 'PLANTED CONTROL: a stale beat'
        _open(forge, 's1', 'pr/later')
        assert not forgefeed.heard('s1', now=1001.0), 'PLANTED CONTROL: a PR the last poll did not cover'
        forgefeed.poll_once(clients=lambda _f: forge, now=1002.0)
        assert forgefeed.heard('s1', now=1003.0)
    monkeypatch.setattr(forgefeed, 'still_the_same_process', lambda _pid, _created: False)
    assert not forgefeed.heard('s1', now=1003.0), 'PLANTED CONTROL: a dead watcher does not hear'


def test_the_watcher_is_a_singleton_and_a_dead_holders_lock_is_taken_over(monkeypatch: pytest.MonkeyPatch) -> None:
    with forgefeed.held() as first:
        assert first
        assert forgefeed.running()
        with forgefeed.held() as second:
            assert not second, 'PLANTED CONTROL: a live holder keeps the lock'
    assert not forgefeed.running()
    with forgefeed.held() as first:
        assert first
        monkeypatch.setattr(forgefeed, 'still_the_same_process', lambda _pid, _created: False)
        with forgefeed.held() as taken:
            assert taken, 'a dead holder (crashed watcher) is taken over'


def test_start_detaches_only_when_no_watcher_runs(monkeypatch: pytest.MonkeyPatch, tmp_path: os.PathLike) -> None:
    started: list[list[str]] = []
    monkeypatch.setattr(forgefeed, 'detach_argv', lambda _root, args: started.append(args))
    assert forgefeed.ensure(tmp_path)
    assert started == [['-m', 'dev_lab.dev.forgefeed', 'run']]
    with forgefeed.held():
        assert not forgefeed.ensure(tmp_path), 'PLANTED CONTROL: a running watcher is not started twice'
    assert len(started) == 1


def test_run_polls_until_it_yields_its_venv() -> None:
    forge = StateForge()
    _open(forge)
    status_post(forge, SHA, context='tests/base', state='failure', description='boom')
    polls = iter(['', '', 'venv update pending'])
    code = forgefeed.run(clients=lambda _f: forge, every_s=0, sleep=lambda _s: None, yielding=lambda: next(polls))
    assert code == forgefeed.YIELDED
    assert len(forgefeed.take_unread('s1')) == 1
    assert not forgefeed.running(), 'the lock is released on exit'


def test_the_prompt_hook_surfaces_unread_events_once(capsys: pytest.CaptureFixture[str]) -> None:
    forge = StateForge()
    key = _open(forge)
    payload = json.dumps({'hook_event_name': 'UserPromptSubmit', 'session_id': 's1'})
    assert forgefeed.main(['inbox'], stdin=io.StringIO(payload)) == 0
    assert capsys.readouterr().out == '', 'PLANTED CONTROL: an empty inbox says nothing'
    status_post(forge, SHA, context='tests/base', state='failure', description='boom')
    forgefeed.poll_once(clients=lambda _f: forge, now=1.0)
    assert forgefeed.main(['inbox'], stdin=io.StringIO(payload)) == 0
    said = json.loads(capsys.readouterr().out)['hookSpecificOutput']
    assert said['hookEventName'] == 'UserPromptSubmit'
    assert key in said['additionalContext']
    assert forgefeed.main(['inbox'], stdin=io.StringIO(payload)) == 0
    assert capsys.readouterr().out == ''


# --- D81: one issues-since read per repository, routed to tasks by inline label ----------------------------------

HOST = 'forge.example'


class RepoForge:
    """One repository's ``issues`` listing; it counts every request and answers 304 to a matching ETag."""

    def __init__(self, rows: list[dict], *, name: str = 'r', etag: str = 'v1') -> None:
        """*rows* is what ``issues?since=`` returns; *etag* the version the forge reports for it."""
        self.forge = Forge(HOST, 'o', name)
        self.backend = SimpleNamespace(api_root='/api/v1')
        self.repo = f'/api/v1/repos/o/{name}'
        self.rows, self.etag = rows, etag
        self.calls: list[str] = []

    def call_conditional(self, method: str, path: str, etag: str = '') -> tuple[int, str, object]:
        assert method == 'GET'
        assert path.startswith(f'{self.repo}/issues?'), 'only the repository listing is ever read'
        self.calls.append(path)
        if etag and etag == self.etag:
            return 304, etag, None
        return 200, self.etag, self.rows

    def call(self, method: str, path: str, body: object = None, durable: object = None) -> object:
        msg = f'no other read is made: {method} {path}'
        raise AssertionError(msg)


def _row(number: int, updated: str, labels: tuple[str, ...] = (), *, pull: bool = False) -> dict:
    row = {
        'number': number,
        'title': f'thread {number}',
        'updated_at': updated,
        'labels': [{'name': n} for n in labels],
    }
    return row | ({'pull_request': {}} if pull else {})


def _bind(session: str, slug: str, ledger: os.PathLike) -> None:
    path = taskbinding.binding_path(session)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {'session': session, 'task': f'{slug}@abc', 'ledger': {'path': str(ledger)}}
    path.write_text(json.dumps(record), encoding='utf-8')


def _hear(*forges: RepoForge) -> tuple[str, ...]:
    by = {f.forge: f for f in forges}
    return forgefeed.hear_feed(lambda f: by[f], list(by))


def test_one_read_per_repository_whatever_the_number_of_subscribed_issues(tmp_path: os.PathLike) -> None:
    _bind('s1', 'alpha', tmp_path)
    rows = [_row(n, f'2026-11-18T10:{n:02d}:00Z', ('task:alpha',)) for n in range(1, 31)]
    one, two = RepoForge(rows), RepoForge([], name='q')
    _hear(one, two)
    assert (len(one.calls), len(two.calls)) == (1, 1), 'one request per repository per tick, labels inline'
    per_issue_shape = len(rows)  # the retired shape read every subscribed issue (or its labels) each tick
    assert len(one.calls) + len(two.calls) < per_issue_shape, 'PLANTED CONTROL: per-issue reads fail this bound'
    assert len(forgefeed.take_unread('s1')) == len(rows)


def test_a_labelled_thread_reaches_its_tasks_sessions_and_an_unlabelled_one_reaches_none(tmp_path: os.PathLike) -> None:
    _bind('s1', 'alpha', tmp_path)
    _bind('s2', 'beta', tmp_path)
    _hear(
        RepoForge([_row(3, '2026-11-18T10:00:00Z', ('task:alpha', 'bug')), _row(4, '2026-11-18T10:01:00Z', ('bug',))])
    )
    said = forgefeed.take_unread('s1')
    assert any('#3 ' in line for line in said)
    assert not any('#4 ' in line for line in said), 'PLANTED CONTROL: an unlabelled thread is routed nowhere'
    assert forgefeed.take_unread('s2') == [], 'PLANTED CONTROL: a task the labels do not name hears nothing'


def test_the_cursor_resumes_per_repository_and_a_thread_at_the_cursor_is_not_heard_twice(
    tmp_path: os.PathLike,
) -> None:
    _bind('s1', 'alpha', tmp_path)
    forge = RepoForge([_row(3, '2026-11-18T10:00:00Z', ('task:alpha',))])
    _hear(forge)
    assert 'since=' not in forge.calls[0], 'PLANTED CONTROL: the first read has no cursor'
    forge.etag = 'v2'  # the forge answers again, with the same row at the cursor
    _hear(forge)
    assert forge.calls[-1].endswith('&since=2026-11-18T10:00:00Z')
    assert forgefeed.cursor(forge.forge) == '2026-11-18T10:00:00Z'
    assert len([line for line in forgefeed.take_unread('s1') if '#3 ' in line]) == 1, 'not heard again at the cursor'


def test_a_304_to_the_stored_etag_costs_nothing(tmp_path: os.PathLike) -> None:
    _bind('s1', 'alpha', tmp_path)
    forge = RepoForge([_row(3, '2026-11-18T10:00:00Z', ('task:alpha',))])
    _hear(forge)
    forgefeed.take_unread('s1')
    _hear(forge)
    assert len(forge.calls) == 2
    assert forgefeed.take_unread('s1') == [], 'a 304 delivers nothing'
    forge.etag = 'v2'
    forge.rows = [_row(5, '2026-11-18T11:00:00Z', ('task:alpha',))]
    _hear(forge)
    assert any('#5 ' in line for line in forgefeed.take_unread('s1')), 'PLANTED CONTROL: a new version is read'


def test_this_machines_own_comment_is_not_news(tmp_path: os.PathLike) -> None:
    _bind('s1', 'alpha', tmp_path)
    forgefeed.record_own(f'{Forge(HOST, "o", "r").identity}#3', at=1_794_996_000.0)  # 2026-11-18T10:00:00Z
    rows = [_row(3, '2026-11-18T10:00:02Z', ('task:alpha',)), _row(4, '2026-11-18T10:00:02Z', ('task:alpha',))]
    _hear(RepoForge(rows))
    said = forgefeed.take_unread('s1')
    assert not any('#3 ' in line for line in said), 'its own comment is skipped'
    assert any('#4 ' in line for line in said), 'PLANTED CONTROL: another thread changed at the same time is news'


def test_a_task_no_session_is_bound_to_keeps_its_events_for_the_next_binding(
    tmp_path: os.PathLike, capsys: pytest.CaptureFixture[str]
) -> None:
    _bind('s1', 'alpha', tmp_path)
    _hear(RepoForge([_row(9, '2026-11-18T10:00:00Z', ('task:gamma',))]))
    assert forgefeed.take_unread('s1') == [], 'PLANTED CONTROL: a bound session of another task hears nothing'
    assert any('#9' in line for line in forgefeed.task_pending('gamma'))
    _bind('s3', 'gamma', tmp_path)
    assert forgefeed.main(['inbox'], stdin=io.StringIO(json.dumps({'session_id': 's3'}))) == 0
    assert '#9' in json.loads(capsys.readouterr().out)['hookSpecificOutput']['additionalContext']
    assert forgefeed.task_pending('gamma') == [], 'heard once, by the first session that binds it'


def test_the_tick_is_the_machine_files_setting_and_a_bad_value_is_refused_by_name() -> None:
    assert forgefeed.tick_s({}) == forgefeed.DEFAULT_TICK_S == 120
    assert forgefeed.tick_s({'tick_s': 60}) == 60
    for bad in (0, -5, 1.5, '60', True):
        with pytest.raises(ValueError, match=r'\[forgefeed\] tick_s'):
            forgefeed.tick_s({'tick_s': bad})  # PLANTED CONTROL: each non-positive-int is refused
