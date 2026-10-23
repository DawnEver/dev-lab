"""The stop-own-run door: a planted table drives the logic, and a REAL pair of processes the kill."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from dev_lab.dev.servelock import was_stopped
from dev_lab.dev.stoprun import (
    SignaturesNotDeclared,
    declared_orphans,
    declared_signatures,
    identify,
    process_table,
    stop,
    subtree,
)

_TABLE = {
    10: (1, 'python -m dev_lab.dev.verify tests/a.py'),
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
    run = subprocess.Popen([sys.executable, '-c', sleeper, '-m', 'dev_lab.dev.verify'])
    bystander = subprocess.Popen([sys.executable, '-c', sleeper])
    try:
        # A child seen between fork and exec still carries THIS process's command line, so the
        # table is read until the planted run shows its own -- the race one CI leg lost.
        table = process_table()
        for _ in range(100):
            if 'dev_lab.dev.verify' in table.get(run.pid, (0, ''))[1]:
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
    assert identify('python.exe -m dev_lab.dev.githooks run pre-push origin url')
    assert identify('python.exe scripts/gate/prepush_gate.py')
    assert not identify('python.exe -m dev_lab.dev.githooks run pre-commit')
    assert not identify('git push origin main')


_SERVE = {
    30: (1, 'python -m dev_lab.dev.forge serve --lock x'),
    31: (30, 'python scripts/gate/runner.py part jmag --full'),
    32: (31, 'python -m pytest -n 4'),
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


# --------------------------------------------------------------------------------------------
# an ORPHAN -- parent gone, no box claim, a declared vendor tool or a scratch/ script -- is stoppable
# (measured 2026-10-21: two orphan JMAG Designers, a node-side JobSystem and a scratch watcher were all
# refused as "no run signature", and RAW-PROCESS-KILL left no supported way to free the box they held)

_ORPHANS = (r'designer(?:\.exe)?\b.*--process-link', r'JobSystem\.exe\b.*\s-s\b')
_DESIGNER = '"C:/Program Files/JMAG-Designer24.1/designer.exe" --process-link --no-splash'


def _none_claimed() -> set[int]:
    return set()


def test_an_orphan_vendor_tool_with_no_claim_is_stopped_children_first() -> None:
    table = {40: (7, _DESIGNER), 41: (40, 'jmag solver child'), 20: (1, 'node server.js'), 1: (0, 'init')}
    killed: list[int] = []
    code, lines = stop(40, table, dry_run=False, kill=killed.append, orphans=_ORPHANS, claimed=_none_claimed)
    assert code == 0, lines
    assert killed == [41, 40]
    assert 'orphan' in lines[0]


def test_a_node_side_jobsystem_and_a_scratch_watcher_are_orphans_too() -> None:
    table = {
        50: (8, r'C:\JMAG\JobSystem.exe -s --control=node7:9000'),
        60: (9, 'bash /d/repo/scratch/jmag_watch.sh'),
        61: (60, 'tail -F /d/repo/output/run.log'),
    }
    for pid, expect in ((50, [50]), (60, [61, 60])):
        killed: list[int] = []
        assert stop(pid, table, dry_run=False, kill=killed.append, orphans=_ORPHANS, claimed=_none_claimed)[0] == 0
        assert killed == expect


def test_a_planted_posix_orphan_reparented_to_init_is_an_orphan() -> None:
    """PLANTED (forge, 2026-10-23): on POSIX an orphan's ppid becomes 1, and init is alive and older than it."""
    table = {60: (1, 'python -c sleep scratch/watch.py'), 1: (0, '/sbin/init')}
    born = {60: 200, 1: 1}.get
    code, lines = stop(60, table, dry_run=True, claimed=_none_claimed, born=born)
    assert code == 0, lines


def test_an_orphan_whose_parent_pid_was_reused_by_a_younger_process_is_still_an_orphan() -> None:
    table = {40: (7, _DESIGNER), 7: (1, 'explorer.exe')}
    born = {40: 100, 7: 200}.get
    code, _ = stop(40, table, dry_run=True, orphans=_ORPHANS, claimed=_none_claimed, born=born)
    assert code == 0


def test_an_orphan_is_refused_naming_why_when_any_one_condition_fails() -> None:
    """PLANTED CONTROLS: each condition alone refuses -- a live parent, a claim, an undeclared tool, no ledger."""
    parented = {40: (7, _DESIGNER), 7: (1, 'python -m motronics case run')}
    orphaned = {40: (7, _DESIGNER), 41: (40, 'child'), 70: (5, 'notepad.exe')}
    born = {40: 200, 7: 100}.get
    killed: list[int] = []

    def unreadable() -> set[int]:
        msg = 'ledger locked'
        raise OSError(msg)

    def refused(table: dict, pid: int, claimed: object) -> str:
        code, lines = stop(pid, table, dry_run=False, kill=killed.append, orphans=_ORPHANS, born=born, claimed=claimed)
        assert code == 3
        return lines[0]

    assert 'parent 7 is alive' in refused(parented, 40, _none_claimed)
    assert 'holds a box claim' in refused(orphaned, 40, lambda: {41})
    assert 'no orphan signature' in refused(orphaned, 70, _none_claimed)
    assert 'ledger' in refused(orphaned, 40, unreadable)
    assert killed == []


def test_declared_orphans_are_read_from_the_same_table_as_the_signatures(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.lab_commons.stoprun]\nsignatures = ["jcwrap"]\norphans = ["designer"]\n', encoding='utf-8'
    )
    assert declared_signatures(tmp_path) == ('jcwrap',)
    assert declared_orphans(tmp_path) == ('designer',)
    (tmp_path / 'pyproject.toml').write_text('[tool.lab_commons.stoprun]\norphans = "designer"\n', encoding='utf-8')
    with pytest.raises(SignaturesNotDeclared):
        declared_orphans(tmp_path)


def test_a_real_orphaned_scratch_script_is_stopped_and_a_parented_one_is_spared() -> None:
    sleeper = 'import time; time.sleep(120)'
    spawn = (
        'import subprocess, sys; d = subprocess.DEVNULL; '
        f'print(subprocess.Popen([sys.executable, "-c", "{sleeper}", "scratch/watch.py"], '
        'stdin=d, stdout=d, stderr=d).pid)'
    )
    launcher = subprocess.run(
        [sys.executable, '-c', spawn], capture_output=True, text=True, encoding='utf-8', timeout=60, check=True
    )
    orphan = int(launcher.stdout.strip())
    parented = subprocess.Popen([sys.executable, '-c', sleeper, 'scratch/watch.py'])
    try:
        table = process_table()
        for _ in range(100):
            if 'scratch/watch.py' in table.get(parented.pid, (0, ''))[1] and orphan in table:
                break
            time.sleep(0.1)
            table = process_table()
        assert stop(parented.pid, table, dry_run=False, claimed=_none_claimed)[0] == 3
        assert stop(orphan, table, dry_run=False, claimed=_none_claimed)[0] == 0
        for _ in range(100):
            if orphan not in process_table():
                break
            time.sleep(0.1)
        assert orphan not in process_table()
        assert parented.poll() is None
    finally:
        parented.kill()
        parented.wait(timeout=30)
        with contextlib.suppress(OSError):
            os.kill(orphan, signal.SIGTERM)
