"""In-flight dedupe: a second request for the SAME (tree, env, selector) attaches to the first.

MEASURED 2026-10-08 in one consumer repo: 95 of 98 runner logs that day were one key, re-launched
about twice a minute by agents polling a held box. Every arm below drives the real function over a
real directory, with a real thread as the leader, because the property is about two callers.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from lab_commons.dev.inflight import RunKey, claim_path, run_once

KEY = RunKey(tree='t1', env='e1', selector='verify tests/a.py')


def test_a_lone_request_runs_and_says_it_led(tmp_path: Path) -> None:
    """No one in flight: the caller runs, and the answer says it was not attached."""
    assert run_once(KEY, lambda: 'PASS', directory=tmp_path, poll_s=0.01) == ('PASS', False)
    assert not claim_path(tmp_path, KEY).exists(), 'the claim outlived its run'


def test_a_duplicate_attaches_to_the_run_in_flight_and_never_runs(tmp_path: Path) -> None:
    """THE POINT: the follower's own run is never called, and it receives the leader's answer."""
    started, release = threading.Event(), threading.Event()
    led: list[tuple[str, bool]] = []

    def leader() -> str:
        started.set()
        release.wait(10)
        return 'FAIL (1 failed)'

    thread = threading.Thread(target=lambda: led.append(run_once(KEY, leader, directory=tmp_path, poll_s=0.01)))
    thread.start()
    assert started.wait(10)
    follower_ran: list[bool] = []
    timer = threading.Timer(0.2, release.set)
    timer.start()
    got = run_once(KEY, lambda: follower_ran.append(True) or 'MINE', directory=tmp_path, poll_s=0.01)
    thread.join(10)
    assert got == ('FAIL (1 failed)', True)
    assert follower_ran == [], 'the duplicate ran its own copy of the suite'
    assert led == [('FAIL (1 failed)', False)]


def test_a_different_key_does_not_attach(tmp_path: Path) -> None:
    """PLANTED CONTROL: a live claim on ANOTHER key leaves this request to run on its own."""
    other = RunKey(tree='t2', env='e1', selector=KEY.selector)
    claim_path(tmp_path, other).write_text(json.dumps({'pid': 0, 'run': 'x'}), encoding='utf-8')
    assert run_once(KEY, lambda: 'PASS', directory=tmp_path, poll_s=0.01) == ('PASS', False)


def test_a_claim_whose_leader_died_is_taken_over(tmp_path: Path) -> None:
    """A crashed leader leaves a claim; a dead pid is not a run anyone can attach to."""
    dead = subprocess.Popen([sys.executable, '-c', 'pass'])
    dead.wait()
    claim_path(tmp_path, KEY).write_text(json.dumps({'pid': dead.pid, 'run': 'gone'}), encoding='utf-8')
    assert run_once(KEY, lambda: 'PASS', directory=tmp_path, poll_s=0.01) == ('PASS', False)


def test_a_leader_that_raises_releases_its_claim(tmp_path: Path) -> None:
    """A run that produced nothing must not leave followers waiting on it forever."""

    def boom() -> str:
        msg = 'boom'
        raise RuntimeError(msg)

    with pytest.raises(RuntimeError, match='boom'):
        run_once(KEY, boom, directory=tmp_path, poll_s=0.01)
    assert not claim_path(tmp_path, KEY).exists()


def test_the_key_digest_separates_every_field() -> None:
    """Tree, env and selector each move the key; a run on another env answers nothing here."""
    digests = {
        KEY.digest(),
        RunKey('t2', KEY.env, KEY.selector).digest(),
        RunKey(KEY.tree, 'e2', KEY.selector).digest(),
        RunKey(KEY.tree, KEY.env, 'verify').digest(),
    }
    assert len(digests) == 4
