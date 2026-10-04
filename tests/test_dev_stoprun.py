"""The stop-own-run door: a planted table drives the logic, and a REAL pair of processes the kill."""

from __future__ import annotations

import subprocess
import sys

from lab_commons.dev.stoprun import identify, process_table, stop, subtree

_TABLE = {
    10: (1, 'python -m lab_commons.dev.verify --no-status'),
    11: (10, 'python -m pytest -n 4'),
    12: (11, 'python worker'),
    20: (1, 'node server.js'),
}


def test_only_an_identifiable_run_is_stopped_and_children_go_first() -> None:
    killed: list[int] = []
    code, _ = stop(10, _TABLE, dry_run=False, kill=killed.append)
    assert code == 0
    assert killed == [12, 11, 10]
    assert subtree(_TABLE, 20) == [20]


def test_an_unidentified_or_missing_pid_is_refused_and_nothing_is_killed() -> None:
    killed: list[int] = []
    assert stop(20, _TABLE, dry_run=False, kill=killed.append)[0] == 3
    assert stop(99, _TABLE, dry_run=False, kill=killed.append)[0] == 3
    assert killed == []
    assert identify('python scripts/gate/runner.py gate')
    assert not identify('python scripts/gate/other.py')


def test_the_real_table_and_kill_stop_a_planted_run_and_spare_a_bystander() -> None:
    sleeper = 'import time; time.sleep(120)'
    run = subprocess.Popen([sys.executable, '-c', sleeper, '-m', 'lab_commons.dev.verify'])
    bystander = subprocess.Popen([sys.executable, '-c', sleeper])
    try:
        table = process_table()
        assert stop(bystander.pid, table, dry_run=False)[0] == 3
        assert stop(run.pid, table, dry_run=False)[0] == 0
        run.wait(timeout=30)
        assert bystander.poll() is None
    finally:
        for proc in (run, bystander):
            proc.kill()
            proc.wait(timeout=30)
