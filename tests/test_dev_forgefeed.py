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
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgestatus import status_post

SHA = 'a' * 40


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


# --- D79: one notification-feed read per forge, routed to tasks by label -------------------------------------------

HOST = 'forge.example'


class FeedForge:
    """A forge host's notification feed and each issue's labels; it counts every request."""

    def __init__(self, threads: list[dict], labels: dict[int, list[str]], *, refuse: int = 0) -> None:
        """*threads* is the feed, *labels* each issue's labels; *refuse* answers the feed with that status."""
        self.forge = Forge(HOST, 'o', 'r')
        self.backend = SimpleNamespace(api_root='/api/v1')
        self.repo = '/api/v1/repos/o/r'
        self.threads, self.labels, self.refuse = threads, labels, refuse
        self.calls: list[str] = []

    def call(self, method: str, path: str, body: object = None, durable: object = None) -> object:
        assert method == 'GET'
        self.calls.append(path)
        if path.startswith('/api/v1/notifications'):
            if self.refuse:
                failed = ForgeCallFailed.__new__(ForgeCallFailed)
                failed.report = SimpleNamespace(attempts=[SimpleNamespace(returncode=self.refuse)])
                raise failed
            return self.threads
        number = int(path.rsplit('/', 2)[-2])
        return [{'name': name} for name in self.labels.get(number, [])]


def _thread(number: int, updated: str, *, comment: int | None = None) -> dict:
    subject = {'type': 'Issue', 'title': f'issue {number}', 'url': f'https://{HOST}/api/v1/repos/o/r/issues/{number}'}
    if comment is not None:
        subject['latest_comment_url'] = f'https://{HOST}/api/v1/repos/o/r/issues/comments/{comment}'
    return {'subject': subject, 'repository': {'full_name': 'o/r'}, 'updated_at': updated}


def _bind(session: str, slug: str, ledger: os.PathLike) -> None:
    path = taskbinding.binding_path(session)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {'session': session, 'task': f'{slug}@abc', 'ledger': {'path': str(ledger)}}
    path.write_text(json.dumps(record), encoding='utf-8')


def _hear(forge: FeedForge) -> tuple[str, ...]:
    return forgefeed.hear_feed(lambda _f: forge, [forge.forge])


def test_one_feed_read_per_forge_whatever_the_number_of_subscribed_issues(tmp_path: os.PathLike) -> None:
    _bind('s1', 'alpha', tmp_path)
    subscribed = {n: ['task:alpha'] for n in range(1, 51)}  # fifty subscribed issues, ONE of them changed
    forge = FeedForge([_thread(7, '2026-11-18T10:00:00Z')], subscribed)
    assert _hear(forge) == (HOST,)
    feed_reads = [p for p in forge.calls if '/notifications' in p]
    assert len(feed_reads) == 1, 'one feed request per forge per tick'
    assert len(forge.calls) == 1 + 1, 'plus one label read for the one CHANGED thread'
    per_issue_shape = len(subscribed)  # the retired shape asked every subscribed issue every tick
    assert len(forge.calls) < per_issue_shape, 'PLANTED CONTROL: a request per subscribed issue fails this bound'


def test_a_thread_reaches_only_the_sessions_of_the_tasks_its_labels_name(tmp_path: os.PathLike) -> None:
    _bind('s1', 'alpha', tmp_path)
    _bind('s2', 'beta', tmp_path)
    forge = FeedForge([_thread(3, '2026-11-18T10:00:00Z')], {3: ['task:alpha', 'bug']})
    _hear(forge)
    assert any('#3' in line for line in forgefeed.take_unread('s1'))
    assert forgefeed.take_unread('s2') == [], 'PLANTED CONTROL: a task the labels do not name hears nothing'


def test_the_cursor_resumes_where_the_last_read_stopped(tmp_path: os.PathLike) -> None:
    _bind('s1', 'alpha', tmp_path)
    forge = FeedForge([_thread(3, '2026-11-18T10:00:00Z')], {3: ['task:alpha']})
    _hear(forge)
    assert 'since=' not in forge.calls[0], 'PLANTED CONTROL: the first read has no cursor'
    forge.threads = []
    _hear(forge)
    assert forge.calls[-1].endswith('&since=2026-11-18T10:00:00Z')
    assert forgefeed.cursor(HOST) == '2026-11-18T10:00:00Z'


def test_a_comment_this_machine_posted_is_not_news(tmp_path: os.PathLike) -> None:
    _bind('s1', 'alpha', tmp_path)
    forgefeed.record_own(77)
    forge = FeedForge(
        [_thread(3, '2026-11-18T10:00:00Z', comment=77), _thread(4, '2026-11-18T10:01:00Z', comment=78)],
        {3: ['task:alpha'], 4: ['task:alpha']},
    )
    _hear(forge)
    said = forgefeed.take_unread('s1')
    assert not any('#3 ' in line for line in said), 'its own comment is skipped'
    assert any('#4 ' in line for line in said), "PLANTED CONTROL: another's comment is news"


def test_a_task_no_session_is_bound_to_keeps_its_events_for_the_next_binding(
    tmp_path: os.PathLike, capsys: pytest.CaptureFixture[str]
) -> None:
    _bind('s1', 'alpha', tmp_path)
    forge = FeedForge([_thread(9, '2026-11-18T10:00:00Z')], {9: ['task:gamma']})
    _hear(forge)
    assert forgefeed.take_unread('s1') == [], 'PLANTED CONTROL: a bound session of another task hears nothing'
    assert any('#9' in line for line in forgefeed.task_pending('gamma'))
    _bind('s3', 'gamma', tmp_path)
    assert forgefeed.main(['inbox'], stdin=io.StringIO(json.dumps({'session_id': 's3'}))) == 0
    assert '#9' in json.loads(capsys.readouterr().out)['hookSpecificOutput']['additionalContext']
    assert forgefeed.task_pending('gamma') == [], 'heard once, by the first session that binds it'


def test_a_feed_the_token_may_not_read_is_refused_by_name_with_its_scope(tmp_path: os.PathLike) -> None:
    _bind('s1', 'alpha', tmp_path)
    forge = FeedForge([], {}, refuse=403)
    assert _hear(forge) == (), 'a refused host is not heard'
    said = forgefeed.take_unread('s1')
    assert any(forgefeed.RULE in line and 'read:notification' in line for line in said)
    with pytest.raises(PermissionError, match='notifications'):
        forgefeed.read_feed(forge)
    other = FeedForge([], {}, refuse=500)
    with pytest.raises(ForgeCallFailed):
        forgefeed.read_feed(other)  # PLANTED CONTROL: another failure is not called a missing scope
