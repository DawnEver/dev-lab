"""SESSION-HEARS-ITS-PRS through ONE machine watcher (dev-lab#581).

A harness ``Monitor`` dies after 30 minutes, so a session waiting on a long PR was refused at every stop. One
watcher per machine polls every session's PRs, appends each change to the session's inbox and beats; the Stop
gate counts a session heard when the beat is fresh and covers its open PRs. Each test plants its control.
"""

from __future__ import annotations

import io
import json
import os

import pytest
from _forge_state import FORGE, StateForge

from dev_lab.dev import prwatcher, pushstop, sessionprs
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
    prwatcher.poll_once(clients=lambda _f: forge, now=100.0)
    prwatcher.poll_once(clients=lambda _f: forge, now=200.0)
    mine = prwatcher.take_unread('s1')
    assert len(mine) == 1
    assert mine[0].startswith(key)
    assert 'failure' in mine[0]
    assert other not in ''.join(mine), "PLANTED CONTROL: another session's PR never reaches this inbox"
    assert prwatcher.take_unread('s1') == [], 'a read event is not surfaced again'


def test_the_beat_hears_a_session_only_while_fresh_live_and_covering(monkeypatch: pytest.MonkeyPatch) -> None:
    forge = StateForge()
    _open(forge)
    assert not prwatcher.heard('s1', now=0.0), 'PLANTED CONTROL: no beat, nothing heard'
    with prwatcher.held() as mine:
        assert mine
        prwatcher.poll_once(clients=lambda _f: forge, now=1000.0)
        assert prwatcher.heard('s1', now=1000.0 + prwatcher.FRESH_S - 1)
        assert not prwatcher.heard('s1', now=1000.0 + prwatcher.FRESH_S + 1), 'PLANTED CONTROL: a stale beat'
        _open(forge, 's1', 'pr/later')
        assert not prwatcher.heard('s1', now=1001.0), 'PLANTED CONTROL: a PR the last poll did not cover'
        prwatcher.poll_once(clients=lambda _f: forge, now=1002.0)
        assert prwatcher.heard('s1', now=1003.0)
    monkeypatch.setattr(prwatcher, 'still_the_same_process', lambda _pid, _created: False)
    assert not prwatcher.heard('s1', now=1003.0), 'PLANTED CONTROL: a dead watcher does not hear'


def test_the_watcher_is_a_singleton_and_a_dead_holders_lock_is_taken_over(monkeypatch: pytest.MonkeyPatch) -> None:
    with prwatcher.held() as first:
        assert first
        assert prwatcher.running()
        with prwatcher.held() as second:
            assert not second, 'PLANTED CONTROL: a live holder keeps the lock'
    assert not prwatcher.running()
    with prwatcher.held() as first:
        assert first
        monkeypatch.setattr(prwatcher, 'still_the_same_process', lambda _pid, _created: False)
        with prwatcher.held() as taken:
            assert taken, 'a dead holder (crashed watcher) is taken over'


def test_start_detaches_only_when_no_watcher_runs(monkeypatch: pytest.MonkeyPatch, tmp_path: os.PathLike) -> None:
    started: list[list[str]] = []
    monkeypatch.setattr(prwatcher, 'detach_argv', lambda _root, args: started.append(args))
    assert prwatcher.ensure(tmp_path)
    assert started == [['-m', 'dev_lab.dev.prwatcher', 'run']]
    with prwatcher.held():
        assert not prwatcher.ensure(tmp_path), 'PLANTED CONTROL: a running watcher is not started twice'
    assert len(started) == 1


def test_run_polls_until_it_yields_its_venv() -> None:
    forge = StateForge()
    _open(forge)
    status_post(forge, SHA, context='tests/base', state='failure', description='boom')
    polls = iter(['', '', 'venv update pending'])
    code = prwatcher.run(clients=lambda _f: forge, every_s=0, sleep=lambda _s: None, yielding=lambda: next(polls))
    assert code == prwatcher.YIELDED
    assert len(prwatcher.take_unread('s1')) == 1
    assert not prwatcher.running(), 'the lock is released on exit'


def test_the_prompt_hook_surfaces_unread_events_once(capsys: pytest.CaptureFixture[str]) -> None:
    forge = StateForge()
    key = _open(forge)
    payload = json.dumps({'hook_event_name': 'UserPromptSubmit', 'session_id': 's1'})
    assert prwatcher.main(['inbox'], stdin=io.StringIO(payload)) == 0
    assert capsys.readouterr().out == '', 'PLANTED CONTROL: an empty inbox says nothing'
    status_post(forge, SHA, context='tests/base', state='failure', description='boom')
    prwatcher.poll_once(clients=lambda _f: forge, now=1.0)
    assert prwatcher.main(['inbox'], stdin=io.StringIO(payload)) == 0
    said = json.loads(capsys.readouterr().out)['hookSpecificOutput']
    assert said['hookEventName'] == 'UserPromptSubmit'
    assert key in said['additionalContext']
    assert prwatcher.main(['inbox'], stdin=io.StringIO(payload)) == 0
    assert capsys.readouterr().out == ''


def test_the_stop_gate_counts_a_fresh_covering_beat_as_a_watch() -> None:
    forge = StateForge()
    _open(forge)
    refused = pushstop.unwatched_refusal('s1').block
    assert refused is not None, 'PLANTED CONTROL: no watch and no watcher'
    assert 'dev_lab.dev.prwatcher start' in refused, 'the refusal names the watcher door'
    with prwatcher.held():
        prwatcher.poll_once(clients=lambda _f: forge)
        assert pushstop.unwatched_refusal('s1').block is None
