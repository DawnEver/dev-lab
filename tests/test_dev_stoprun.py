"""The stop-own-run door: a planted table drives the logic, and a REAL pair of processes the kill."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from dev_lab.dev.servelock import was_stopped
from dev_lab.dev.stoprun import (
    SignaturesNotDeclared,
    declared_signatures,
    identify,
    orphaned_worker,
    process_table,
    stop,
    subtree,
)

_TABLE = {
    10: (1, 'python -m dev_lab.dev.verify tests/a.py', 100.0),
    11: (10, 'python -m pytest -n 4', 100.0),
    12: (11, 'python worker', 100.0),
    20: (1, 'node server.js', 100.0),
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
    run = subprocess.Popen([sys.executable, '-c', sleeper, '-m', 'dev_lab.dev.verify'])
    bystander = subprocess.Popen([sys.executable, '-c', sleeper])
    try:
        # A child seen between fork and exec still carries THIS process's command line, so the
        # table is read until the planted run shows its own -- the race one CI leg lost.
        table = process_table()
        for _ in range(100):
            if 'dev_lab.dev.verify' in table.get(run.pid, (0, '', 0.0))[1]:
                break
            time.sleep(0.1)
            table = process_table()
        assert stop(bystander.pid, table, dry_run=False)[0] == 3
        assert stop(run.pid, table, dry_run=False)[0] == 0
        run.wait(timeout=30)
        assert bystander.poll() is None
    finally:
        for proc in (run, bystander):
            proc.kill()
            proc.wait(timeout=30)


def _declare(root: Path, value: str) -> Path:
    (root / 'pyproject.toml').write_text(f'[tool.lab_commons.stoprun]\nsignatures = {value}\n', encoding='utf-8')
    return root


def test_a_declared_signature_is_read_from_the_repo_and_a_malformed_one_raises(tmp_path: Path) -> None:
    assert declared_signatures(tmp_path) == ()
    assert declared_signatures(_declare(tmp_path, '["jcwrap"]')) == ('jcwrap',)
    for bad in ('"jcwrap"', '[1]', '["("]', '{a = 1}'):
        _declare(tmp_path, bad)
        with pytest.raises(SignaturesNotDeclared):
            declared_signatures(tmp_path)


def test_dry_run_names_the_signature_that_matched_and_kills_nothing() -> None:
    table = {30: (1, 'C:/JMAG/jcwrap.exe -batch', 100.0), 31: (30, 'solver', 100.0)}
    killed: list[int] = []
    code, lines = stop(30, table, dry_run=True, kill=killed.append, signatures=('jcwrap',))
    assert code == 0
    assert killed == []
    assert "'jcwrap'" in lines[0]
    assert stop(30, table, dry_run=True)[0] == 3


def test_a_declared_signature_stops_a_planted_tree_and_spares_a_bystander(tmp_path: Path) -> None:
    parent_src = (
        'import subprocess, sys, time; '
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']); time.sleep(120)"
    )
    planted = subprocess.Popen([sys.executable, '-c', parent_src, 'jcwrap'])
    bystander = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)', 'jcwrap-not'])
    try:
        children: list[int] = []
        table = process_table()
        for _ in range(100):
            table = process_table()
            children = [p for p, (ppid, *_) in table.items() if ppid == planted.pid]
            if children:
                break
            time.sleep(0.1)
        assert children
        assert stop(planted.pid, table, dry_run=False)[0] == 3
        signatures = declared_signatures(_declare(tmp_path, r'["\\sjcwrap$"]'))
        assert stop(bystander.pid, table, dry_run=False, signatures=signatures)[0] == 3
        assert stop(planted.pid, table, dry_run=False, signatures=signatures)[0] == 0
        planted.wait(timeout=30)
        for _ in range(100):
            if not set(children) & set(process_table()):
                break
            time.sleep(0.1)
        assert not set(children) & set(process_table())
        assert bystander.poll() is None
    finally:
        for proc in (planted, bystander):
            proc.kill()
            proc.wait(timeout=30)


def test_a_blocking_pre_push_hook_is_a_run_this_door_stops() -> None:
    """A PUSH MUST NEVER BLOCK: the rule says kill it, so the door that kills must recognise it."""
    assert identify('python.exe -m dev_lab.dev.githooks run pre-push origin url')
    assert identify('python.exe scripts/gate/prepush_gate.py')
    assert not identify('python.exe -m dev_lab.dev.githooks run pre-commit')
    assert not identify('git push origin main')


_SERVE = {
    30: (1, 'python -m dev_lab.dev.forge serve --lock x', 100.0),
    31: (30, 'python scripts/gate/runner.py part jmag --full', 100.0),
    32: (31, 'python -m pytest -n 4', 100.0),
}


def test_a_serve_is_stopped_producers_first_noted_and_given_a_grace_to_release(tmp_path: Path) -> None:
    killed: list[int] = []
    waited: list[int] = []

    def gone(pid: int, seconds: float) -> bool:
        waited.append(pid)
        assert seconds > 0
        return True  # the serve released its claim and exited on its own

    code, lines = stop(30, _SERVE, dry_run=False, kill=killed.append, gone=gone, notes=tmp_path)
    assert code == 0
    assert killed == [32, 31]
    assert waited == [30]
    assert was_stopped(31, root=tmp_path)
    assert not was_stopped(32, root=tmp_path)
    assert any('serve' in line for line in lines)


def test_a_serve_that_outlives_its_grace_is_killed(tmp_path: Path) -> None:
    killed: list[int] = []
    stop(30, _SERVE, dry_run=False, kill=killed.append, gone=lambda *_: False, notes=tmp_path)
    assert killed == [32, 31, 30]


#: A multiprocessing worker names the process it exists to serve in its own command line.
_WORKER = (
    '"C:/py/python.exe" -c "from multiprocessing.spawn import spawn_main; spawn_main(parent_pid=40, pipe_handle=9)"'
)


def test_a_worker_whose_named_parent_is_gone_is_an_orphan_and_is_stopped() -> None:
    """The proof is structural: the parent it names is not in the table, so it can never be handed work."""
    table = {41: (40, _WORKER, 100.0), 42: (41, 'python child', 101.0)}
    assert orphaned_worker(table, 41) == 40
    killed: list[int] = []
    code, lines = stop(41, table, dry_run=False, kill=killed.append)
    assert code == 0
    assert killed == [42, 41]
    assert 'orphaned worker of 40' in lines[0]


def test_a_worker_whose_parent_pid_was_reused_is_an_orphan() -> None:
    """Windows reuses pids: a process holding the named pid but CREATED AFTER the worker is not its parent."""
    table = {40: (1, 'notepad.exe', 500.0), 41: (40, _WORKER, 100.0)}
    assert orphaned_worker(table, 41) == 40
    assert stop(41, table, dry_run=True)[0] == 0


def test_a_worker_of_a_live_parent_is_refused() -> None:
    """PLANTED CONTROL: the same command line under its living parent is somebody's running pool."""
    table = {40: (1, 'python -m some.service', 50.0), 41: (40, _WORKER, 100.0)}
    assert orphaned_worker(table, 41) is None
    killed: list[int] = []
    assert stop(41, table, dry_run=False, kill=killed.append)[0] == 3
    assert killed == []


def test_the_real_table_carries_each_process_creation_time() -> None:
    """The reuse proof needs creation times, so the platform table must supply one for every process."""
    table = process_table()
    ppid, cmdline, created = table[os.getpid()]
    assert ppid > 0
    assert cmdline
    assert 0 < created <= time.time()
