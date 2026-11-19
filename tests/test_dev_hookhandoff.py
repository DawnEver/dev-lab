"""The hook hand-off's edges (HOOK-UNDER-FIVE-SECONDS): one runner, defensive reads, nothing stranded.

Each arm plants the edge and its control: a live runner is not started twice and a dead one is replaced; a torn job,
a torn deferred line or a foreign lock is skipped, never a crash; a job queued while the runner finishes still runs.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest
from lab_commons.liveness import creation_stamp

from dev_lab.dev import gitdirs, hookhandoff, metrics
from dev_lab.dev.agent_wiring import Wire

_ROW = (Wire(('Stop',), 'planted_handoff_row'),)


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / 'repo'
    (root / '.git').mkdir(parents=True)
    return root


def _starts(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    started: list[Path] = []
    monkeypatch.setattr(hookhandoff, 'detach', lambda _root, job: started.append(job))
    return started


def test_a_live_runner_is_not_started_twice_and_a_dead_one_is_replaced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, started = _repo(tmp_path), _starts(monkeypatch)
    queue = root / '.git' / hookhandoff.HANDOFF_DIR
    queue.mkdir(parents=True)
    lock = queue / hookhandoff.RUNNER_LOCK
    lock.write_text(json.dumps({'pid': os.getpid(), 'created': creation_stamp(os.getpid())}), encoding='utf-8')
    hookhandoff.hand_off(root, 'Stop', '{}', _ROW)
    assert started == [], 'a live runner drains the new job: no second runner'
    for dead in ('{"pid": 999999999, "created": 1}', 'torn{', '[]'):
        lock.write_text(dead, encoding='utf-8')
        hookhandoff.hand_off(root, 'Stop', '{}', _ROW)
    assert len(started) == 3, 'a dead, torn or foreign lock holds no runner'


def test_the_runner_skips_a_torn_job_runs_the_rest_and_lets_go(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    queue = root / '.git' / hookhandoff.HANDOFF_DIR
    queue.mkdir(parents=True)
    (queue / '1-torn-Stop.json').write_text('{"event": "St', encoding='utf-8')
    (queue / '2-ok-Stop.json').write_text(json.dumps({'event': 'Stop', 'rows': ['x']}), encoding='utf-8')
    ran: list[dict] = []

    def run(job: dict) -> None:
        ran.append(job)
        if len(ran) == 1:  # a job queued while the runner works is run before it lets go
            (queue / '3-late-Stop.json').write_text(json.dumps({'event': 'Stop', 'rows': ['y']}), encoding='utf-8')

    hookhandoff.drain(queue, run)
    assert [job['rows'] for job in ran] == [['x'], ['y']]
    assert list(queue.glob('*.json')) == []
    assert not (queue / hookhandoff.RUNNER_LOCK).exists(), 'the runner lets go of its lock'


def test_a_dead_writers_record_is_adopted_and_a_live_ones_waited_for(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The write-ahead record: a dead dispatcher's inline rows run; a live one's settle first, so nothing runs twice.

    PLANTED CONTROL: the live writer's record (this process) settles with no late rows while the runner waits, and the
    runner runs nothing of it.
    """
    root, started = _repo(tmp_path), _starts(monkeypatch)
    queue = root / '.git' / hookhandoff.HANDOFF_DIR
    dead = hookhandoff.write_ahead(root, 'Stop', '{}', _ROW)
    assert dead is not None
    body = json.loads(dead.read_text(encoding='utf-8'))
    dead.write_text(json.dumps({**body, 'writer': {'pid': 999999999, 'created': 1}}), encoding='utf-8')
    live = hookhandoff.write_ahead(root, 'Stop', '{}', (Wire(('Stop',), 'planted_live_row'),))
    (queue / 'torn.pending').write_text('{"rows": [', encoding='utf-8')
    ran: list[list[str]] = []
    settler = threading.Timer(0.6, hookhandoff.settle, (live, (), root))
    settler.start()
    began = time.monotonic()
    hookhandoff.drain(queue, lambda job: ran.append(job['rows']))
    settler.join()
    assert ran == [['planted_handoff_row']]
    assert time.monotonic() - began >= 0.5, 'the runner waited for the live record to settle'
    assert list(queue.glob('*.pending')) == [], 'the torn record is dropped'
    assert started == []


def test_late_rows_of_a_settled_record_become_a_job_and_start_a_runner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, started = _repo(tmp_path), _starts(monkeypatch)
    record = hookhandoff.write_ahead(root, 'Stop', '{}', (*_ROW, Wire(('Stop',), 'planted_done_row')))
    hookhandoff.settle(record, _ROW, root)
    [job] = started
    assert json.loads(job.read_text(encoding='utf-8'))['rows'] == ['planted_handoff_row']
    assert 'writer' not in json.loads(job.read_text(encoding='utf-8'))
    assert record is not None
    assert not record.exists()


def test_deferred_answers_are_taken_once_and_a_torn_line_is_skipped(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    hookhandoff.defer(root, 'sess', 'SessionStart', 'venv is behind')
    path = root / '.git' / hookhandoff.DEFERRED_DIR / 'sess.jsonl'
    with path.open('a', encoding='utf-8') as torn:
        torn.write('{"event": "Stop", "te')
    assert hookhandoff.take_deferred(root, 'sess') == ['[deferred from SessionStart] venv is behind']
    assert hookhandoff.take_deferred(root, 'sess') == []
    assert hookhandoff.take_deferred(root, 'other') == [], 'PLANTED CONTROL: another session hears nothing'


def test_outside_a_checkout_the_queue_lives_in_the_temp_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(hookhandoff.tempfile, 'gettempdir', lambda: str(tmp_path / 'temp'))
    bare = tmp_path / 'bare'
    bare.mkdir()
    assert hookhandoff.state_dir(bare) == tmp_path / 'temp' / 'dev-lab-hooks'
    assert hookhandoff.state_dir(_repo(tmp_path)) == tmp_path / 'repo' / '.git'


def test_git_dirs_are_read_off_the_files_without_git(tmp_path: Path) -> None:
    """A main checkout, a linked worktree (``.git`` file and ``commondir``), and outside any checkout."""
    main = _repo(tmp_path)
    own = main / '.git' / 'worktrees' / 'lane'
    own.mkdir(parents=True)
    (own / 'commondir').write_text('../..\n', encoding='utf-8')
    lane = tmp_path / 'lane'
    (lane / 'src').mkdir(parents=True)
    (lane / '.git').write_text(f'gitdir: {own}\n', encoding='utf-8')
    assert gitdirs.git_dir(main / 'deep') == main / '.git'
    assert gitdirs.git_dir(lane / 'src') == own.resolve()
    assert gitdirs.common_dir(lane / 'src') == (main / '.git').resolve()
    assert metrics.checkout(lane / 'src') == main.resolve()
    outside = tmp_path / 'nowhere'
    outside.mkdir()
    assert gitdirs.git_dir(outside) is None
    assert metrics.checkout(outside) == outside


def test_two_files_written_in_one_clock_tick_never_share_a_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """PLANTED: a clock that does not advance (Windows' coarse ``time_ns``) between the record and the detached job.

    Shared names let the late record's adoption overwrite the detached job, and the runner then unlinked it unrun.
    """
    root, _ = _repo(tmp_path), _starts(monkeypatch)
    monkeypatch.setattr(hookhandoff.time, 'time_ns', lambda: 1_700_000_000_000_000_000)
    record = hookhandoff.write_ahead(root, 'Stop', '{}', _ROW)
    job = hookhandoff.hand_off(root, 'Stop', '{}', _ROW)
    assert record is not None
    assert record.with_suffix('.json') != job, 'the record, once adopted, would overwrite the queued job'
    hookhandoff.settle(record, _ROW, root)
    assert len(list(job.parent.glob('*.json'))) == 2, 'the adopted record and the queued job are both still queued'
