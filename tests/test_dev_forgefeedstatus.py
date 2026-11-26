"""v1 #2 -- TASK-HEARS-ITS-FORGE-EVENTS was not effective: the hearer's stable start, its status, and its doors.

Observed on a fresh workstation: no hearer ran and nothing said so; one started by hand ran from a worktree venv;
``task-pending <slug>`` printed only the usage line; nothing answered "is my task subscribed, is the hearer alive".
Each test plants the case its check must say no to.
"""

from __future__ import annotations

import contextlib
import http.client
import io
import json
import os
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from _forge_fake import run_git
from _forge_state import FORGE, StateForge

from dev_lab.dev import forgecli, forgefeed, forgefeedstatus
from dev_lab.dev.forge import Transport
from dev_lab.dev.forgefeedstatus import NoStableInterpreter, stable_python, status, unheard_notice
from dev_lab.dev.forgework import Client
from dev_lab.dev.issuekind import create
from dev_lab.dev.venvpath import VENV_LAYOUTS

_INTERPRETER = VENV_LAYOUTS[os.name]


def _main_with_worktree(tmp_path: Path, *, venv: bool) -> tuple[Path, Path]:
    main = tmp_path / 'main'
    main.mkdir()
    run_git(main, 'init', '-q', '-b', 'main')
    run_git(main, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'root')
    lane = main / '.claude' / 'worktrees' / 'lane'
    run_git(main, 'worktree', 'add', '-q', '-b', 'pr/lane/x', str(lane))
    lane_python = lane.joinpath(*_INTERPRETER)
    lane_python.parent.mkdir(parents=True)
    lane_python.write_text('', encoding='utf-8')
    if venv:
        python = main.joinpath(*_INTERPRETER)
        python.parent.mkdir(parents=True)
        python.write_text('', encoding='utf-8')
    return main, lane


def test_the_hearer_runs_from_the_main_checkouts_interpreter_even_when_started_in_a_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main, lane = _main_with_worktree(tmp_path, venv=True)
    found_main, python = stable_python(lane)
    assert found_main.resolve() == main.resolve()
    assert python.resolve() == main.joinpath(*_INTERPRETER).resolve()
    assert lane.resolve() not in python.resolve().parents, 'PLANTED CONTROL: never the worktree venv beside it'
    started: list[tuple[Path, list[str], Path]] = []
    monkeypatch.setattr(forgefeed, 'detach_argv', lambda root, args, python: started.append((root, args, python)))
    assert forgefeed.ensure(lane)
    assert [(r.resolve(), p.resolve()) for r, _a, p in started] == [(main.resolve(), python.resolve())]


def test_no_main_environment_refuses_naming_the_start_door_and_starts_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _main, lane = _main_with_worktree(tmp_path, venv=False)
    started: list[object] = []
    monkeypatch.setattr(forgefeed, 'detach_argv', lambda *a, **_k: started.append(a))
    with pytest.raises(NoStableInterpreter, match='forgefeed start'):
        forgefeed.ensure(lane)
    payload = json.dumps({'hook_event_name': 'SessionStart', 'cwd': str(lane)})
    assert forgefeed.main(['session-start'], stdin=io.StringIO(payload)) == 0
    said = capsys.readouterr().out
    assert 'forgefeed start' in said, 'the hook says what to do'
    assert 'dep --bootstrap' in said
    assert started == [], 'never fell back to the worktree venv'


def test_status_says_whether_the_hearer_runs_and_how_to_start_it(tmp_path: Path) -> None:
    def ask() -> str:
        return '\n'.join(status(tmp_path, None, clients=lambda _f: StateForge(), forges=[], pending=lambda _s: []))

    assert 'NOT running' in ask()
    assert 'forgefeed start' in ask()
    with forgefeed.held() as mine:
        assert mine
        said = ask()
    assert f'running, pid {os.getpid()}' in said, 'the live holder, by pid'
    assert 'NOT running' not in said
    assert 'forgefeed status <slug>' in said, 'no task named: says how to name one'


def test_status_lists_a_tasks_subscribed_issues_and_its_queue(tmp_path: Path) -> None:
    forge = StateForge()
    forge.add_issue('plain')
    tagged = create(forge, 'mine', '', 'need', ['task:v1'])
    create(forge, 'theirs', '', 'need', ['task:other'])
    lines = status(tmp_path, 'v1', clients=lambda _f: forge, forges=[FORGE], pending=lambda _s: ['e1', 'e2'])
    said = '\n'.join(lines)
    assert f'{FORGE.identity}#{tagged.number} mine' in said
    assert 'theirs' not in said, 'PLANTED CONTROL: the issue of another task'
    assert 'plain' not in said, 'PLANTED CONTROL: an unlabeled issue'
    assert '2 event(s) kept' in said
    none = '\n'.join(status(tmp_path, 'nobody', clients=lambda _f: forge, forges=[FORGE], pending=lambda _s: []))
    assert '0 open thread(s)' in none
    assert 'forge issue label <N> --add task:nobody' in none, 'an unsubscribed task is told how to subscribe'


def test_a_task_label_written_while_no_hearer_runs_names_the_start_door(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert 'forgefeed start' in (unheard_notice(tmp_path, ['kind:need', 'task:v1']) or '')
    assert unheard_notice(tmp_path, ['kind:need']) is None, 'PLANTED CONTROL: no task label, nothing to hear'
    with forgefeed.held():
        assert unheard_notice(tmp_path, ['task:v1']) is None, 'PLANTED CONTROL: a running hearer hears it'
    forge = StateForge()
    number = forge.add_issue('x')
    monkeypatch.setattr(forgecli, 'client_for', lambda *_a, **_k: forge)
    assert forgecli.issue_and_pr(['issue', 'label', str(number), '--add', 'task:v1'], cwd=tmp_path, env={}) == 0
    assert 'forgefeed start' in capsys.readouterr().err
    argv = ['issue', 'create', '--title', 't', '--kind', 'need', '--label', 'task:v1']
    assert forgecli.issue_and_pr(argv, cwd=tmp_path, env={}) == 0
    assert 'forgefeed start' in capsys.readouterr().err


def test_task_pending_takes_its_slug_and_an_empty_queue_says_so(capsys: pytest.CaptureFixture[str]) -> None:
    """v1 #2 (e): ``task-pending v1-migration`` printed only the usage line -- the verb matched one word."""
    assert forgefeed.main(['task-pending', 'v1']) == 0
    assert 'task v1: no events kept' in capsys.readouterr().out
    forgefeed._keep('v1', 'thread changed')
    assert forgefeed.main(['task-pending', 'v1']) == 0
    assert capsys.readouterr().out.strip() == 'thread changed'
    assert forgefeed.main(['task-pending']) == 2, 'PLANTED CONTROL: no slug is refused'
    err = capsys.readouterr().err
    assert 'task-pending <slug>' in err
    assert 'status [<slug>]' in err


def test_the_lock_records_the_interpreter_the_hearer_runs_from() -> None:
    with forgefeed.held():
        held = json.loads(forgefeedstatus.lock_path().read_text(encoding='utf-8'))
    assert held['python']


# --- (d): a forge read that hangs ends inside its budget and names what it measured ---------------------------


@pytest.fixture
def silent_forge() -> Iterator[str]:
    """A forge that accepts the connection and never answers: the 90-120 s hang, compressed."""
    server = socket.socket()
    server.bind(('127.0.0.1', 0))
    server.listen(8)
    held: list[socket.socket] = []
    stop = threading.Event()

    def accept() -> None:
        server.settimeout(0.1)
        while not stop.is_set():
            with contextlib.suppress(OSError):
                held.append(server.accept()[0])

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    try:
        yield f'127.0.0.1:{server.getsockname()[1]}'
    finally:
        stop.set()
        thread.join(timeout=5)
        for one in held:
            one.close()
        server.close()


def test_a_hanging_read_ends_inside_its_budget_naming_the_cause(
    silent_forge: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def to_silent(_host: str, timeout: float) -> http.client.HTTPConnection:
        return http.client.HTTPConnection(silent_forge, timeout=timeout)

    def built(_root: Path, **given: Transport) -> Client:
        transport = given['transport']
        return Client(FORGE, 'T', transport=transport, sleep=lambda _s: None)

    monkeypatch.setattr(forgecli, 'client_for', built)
    began = time.monotonic()
    code = forgecli.issue_and_pr(['issue', 'view', '1'], cwd=tmp_path, env={}, transport=to_silent, budget_s=1.0)
    spent = time.monotonic() - began
    err = capsys.readouterr().err
    assert code == 1
    assert spent < 10, f'ended near its 1 s budget, not after three 30 s timeouts ({spent:.1f} s)'
    assert '1 s read budget' in err, err
    assert 'timed out' in err, 'the measured cause, not a bare timeout'


def test_a_read_that_answers_is_untouched_by_the_budget(tmp_path: Path, monkeypatch, capsys) -> None:
    """PLANTED CONTROL beside the hang: an answering forge reads normally under the same budget."""
    forge = StateForge()
    number = forge.add_issue('x')
    monkeypatch.setattr(forgecli, 'client_for', lambda *_a, **_k: forge)
    assert forgecli.issue_and_pr(['issue', 'view', str(number)], cwd=tmp_path, env={}, budget_s=1.0) == 0
    assert f'#{number}' in capsys.readouterr().out
