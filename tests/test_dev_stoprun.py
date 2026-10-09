"""The stop-own-run door: a planted table drives the logic, and a REAL pair of processes the kill."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from lab_commons.dev.stoprun import (
    SignaturesNotDeclared,
    declared_signatures,
    identify,
    process_table,
    stop,
    subtree,
)

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
    table = {30: (1, 'C:/JMAG/jcwrap.exe -batch'), 31: (30, 'solver')}
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
            children = [p for p, (ppid, _) in table.items() if ppid == planted.pid]
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
    assert identify('python.exe -mpre_commit hook-impl --config=.pre-commit-config.yaml --hook-type=pre-push')
    assert identify('python.exe scripts/gate/prepush_gate.py')
    assert not identify('python.exe -mpre_commit hook-impl --config=.pre-commit-config.yaml --hook-type=pre-commit')
    assert not identify('git push origin main')
