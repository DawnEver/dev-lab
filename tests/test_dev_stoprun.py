"""The stop-own-run door: a planted table drives the logic, and a REAL pair of processes the kill."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from lab_commons.liveness import creation_stamp
from lab_commons.proc import pid_alive

from dev_lab.dev import stoprun as door
from dev_lab.dev.servelock import was_stopped
from dev_lab.dev.stoprun import (
    SignaturesNotDeclared,
    declared_orphans,
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
    (root / 'pyproject.toml').write_text(f'[tool.dev_lab.stoprun]\nsignatures = {value}\n', encoding='utf-8')
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
    table = {41: (40, _WORKER), 42: (41, 'python child')}
    born = {41: 100, 42: 101}.get
    assert orphaned_worker(table, 41, born) == 40
    killed: list[int] = []
    code, lines = stop(41, table, dry_run=False, kill=killed.append, born=born)
    assert code == 0
    assert killed == [42, 41]
    assert 'orphaned worker of 40' in lines[0]


def test_a_worker_whose_parent_pid_was_reused_is_an_orphan() -> None:
    """Windows reuses pids: a process holding the named pid but CREATED AFTER the worker is not its parent."""
    table = {40: (1, 'notepad.exe'), 41: (40, _WORKER)}
    born = {40: 500, 41: 100}.get
    assert orphaned_worker(table, 41, born) == 40
    assert stop(41, table, dry_run=True, born=born)[0] == 0


def test_a_worker_of_a_live_parent_is_refused() -> None:
    """PLANTED CONTROL: the same command line under its living parent is somebody's running pool."""
    table = {40: (1, 'python -m some.service'), 41: (40, _WORKER)}
    born = {40: 50, 41: 100}.get
    assert orphaned_worker(table, 41, born) is None
    killed: list[int] = []
    assert stop(41, table, dry_run=False, kill=killed.append, born=born, claimed=_none_claimed)[0] == 3
    assert killed == []


def test_a_worker_whose_parent_stamp_is_unreadable_is_refused() -> None:
    """No creation stamp proves nothing: a present parent of unknown age keeps the worker refused."""
    table = {40: (1, 'python -m some.service'), 41: (40, _WORKER)}
    assert orphaned_worker(table, 41, {41: 100}.get) is None


def test_the_creation_clock_reads_this_process() -> None:
    """The reuse proof needs creation stamps, so the default clock must supply one for a live process."""
    assert creation_stamp(os.getpid()) is not None
    assert process_table()[os.getpid()][1]


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
    parented = {40: (7, _DESIGNER), 7: (1, 'python -m app case run')}
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
        '[tool.dev_lab.stoprun]\nsignatures = ["jcwrap"]\norphans = ["designer"]\n', encoding='utf-8'
    )
    assert declared_signatures(tmp_path) == ('jcwrap',)
    assert declared_orphans(tmp_path) == ('designer',)
    (tmp_path / 'pyproject.toml').write_text('[tool.dev_lab.stoprun]\norphans = "designer"\n', encoding='utf-8')
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


def test_a_pid_whose_creation_stamp_moved_is_not_killed() -> None:
    """A pid recycled after the snapshot names another process: it is skipped, its siblings still stop."""
    killed: list[int] = []
    seen: dict[int, int] = {}

    def born(pid: int) -> int:
        seen[pid] = seen.get(pid, 0) + 1
        return 1000 + pid + (1 if pid == 11 and seen[pid] > 1 else 0)  # 11 is reborn after the snapshot

    code, lines = stop(10, _TABLE, dry_run=False, kill=killed.append, born=born)
    assert code == 0
    assert killed == [12, 10]
    assert any('skipped 11' in line for line in lines)


def test_an_orphaned_multiprocessing_worker_is_an_orphan_by_liverun_s_rule() -> None:
    """A spawn/forkserver worker whose parent is gone is stoppable; a parented one is refused (PLANTED CONTROL)."""
    spawn = 'python.exe -c "from multiprocessing.spawn import spawn_main; spawn_main()" --multiprocessing-fork'
    forkserver = 'python -c from multiprocessing.forkserver import main; main(3, 4)'
    for line in (spawn, forkserver):
        code, lines = stop(80, {80: (7, line)}, dry_run=True, claimed=_none_claimed)
        assert code == 0, lines
    parented = {80: (7, spawn), 7: (1, 'python -m app case run')}
    code, lines = stop(80, parented, dry_run=True, claimed=_none_claimed, born={80: 200, 7: 100}.get)
    assert code == 3
    assert 'parent 7 is alive' in lines[0]


def test_a_refusal_says_what_the_pid_is_who_started_it_whose_it_is_and_the_exit() -> None:
    """2026-11-13: a bare "no signature" left the agent nothing to act on. PLANTED: one pid of this session, one not."""
    table = {
        1: (0, 'init', 100.0),
        2: (1, 'explorer.exe', 100.0),
        5: (2, 'claude --session', 100.0),
        6: (5, 'bash -c agent', 100.0),
        7: (6, 'python -m dev_lab.dev.stoprun --pid 8', 100.0),
        8: (5, 'node watcher.js', 100.0),
        9: (2, 'node other.js', 100.0),
    }
    code, lines = stop(8, table, dry_run=True, me=7, manifest='/r/pyproject.toml')
    said = '\n'.join(lines)
    assert code == 3
    assert "what: 'node watcher.js'" in said
    assert "parent: 5 'claude --session'" in said
    assert 'started from this session (shares ancestor 5' in said
    assert 'ask the user' in said
    assert '[tool.dev_lab.stoprun] signatures' in said
    assert '/r/pyproject.toml' in said
    _, other = stop(9, table, dry_run=True, me=7)
    assert 'not started from this session' in '\n'.join(other)


def test_a_forge_watch_is_a_run_its_owner_may_stop() -> None:
    """A watch holds its checkout's venv (the dep door's VENV LOCK); its owner stops it here and re-arms after."""
    assert identify('python.exe -m dev_lab.dev.forge watch --session abc --stream')
    assert identify('python.exe -m dev_lab.dev.forge watch 9fc0cef9a277 --stream')
    assert not identify('python.exe -m dev_lab.dev.forge status show 9fc0cef9a277')


def test_a_hung_retry_wrapped_network_verb_is_a_run_this_door_stops() -> None:
    """The agent holds the WRAPPER's pid, not the hook's (2026-11-13): the wrapper must be stoppable too."""
    assert identify('sh scripts/hooks/with-retry.sh push origin pr/x')
    assert identify('/usr/bin/bash C:/repo/scripts/hooks/with-retry.sh fetch origin')
    assert not identify('sh scripts/hooks/with-venv.sh push')  # planted control: another script is not this wrapper
    assert not identify('sh scripts/hooks/with-retry.sh')  # no verb: nothing it runs is a network run


class _ApprovedScene:
    """A queued Python controller, its one run, and unrelated processes; no real process is killed."""

    def __init__(self) -> None:
        self.table = {
            30: (1, 'python output/qualify.py'),
            31: (30, 'python scripts/gate/runner.py measure tests/a.py'),
            32: (31, 'python queue_worker.py'),
            40: (1, 'python unrelated.py'),
        }
        self.created = {30: 100, 31: 101, 32: 102, 40: 90}
        self.killed = []
        self.after_kill = lambda _pid: None

    def born(self, pid) -> int | None:
        return self.created.get(pid) if pid in self.table else None

    def fresh(self) -> dict[int, tuple[int, str]]:
        return dict(self.table)

    def kill(self, pid) -> None:
        self.killed.append(pid)
        self.table.pop(pid, None)
        self.after_kill(pid)

    def approval(self, **changes: object) -> door.ApprovedRun:
        fields = {
            'created': 100,
            'command_sha256': hashlib.sha256(self.table[30][1].encode('utf-8')).hexdigest(),
            'user_words': 'Stop only my verified queued qualification controller and its verified run.',
        }
        return door.ApprovedRun(**(fields | changes))

    def stop(self, *, approved=None, dry_run=False, **changes: object) -> tuple[int, list[str]]:
        return door.stop(
            30,
            dict(self.table),
            dry_run=dry_run,
            approved=self.approval() if approved is None else approved,
            born=self.born,
            fresh=self.fresh,
            kill=self.kill,
            gone=lambda pid, _seconds: pid not in self.table,
            **changes,
        )


def test_an_approved_controller_stops_first_and_cannot_launch_the_next_file() -> None:
    scene = _ApprovedScene()
    launched = []

    def next_file(pid) -> None:
        if pid == 31 and 30 in scene.table:
            launched.append('next-file')

    scene.after_kill = next_file
    code, lines = scene.stop()
    assert code == 0
    assert scene.killed == [30, 32, 31]
    assert launched == []
    assert 40 in scene.table
    assert 'user-authorized' in '\n'.join(lines)


@pytest.mark.parametrize(
    'changes',
    [
        {'created': None},
        {'created': True},
        {'created': 100.0},
        {'created': 0},
        {'created': -1},
        {'command_sha256': ''},
        {'command_sha256': 'x' * 64},
        {'command_sha256': 'A' * 64},
        {'user_words': ''},
        {'user_words': '   '},
        {'user_words': None},
        {'user_words': True},
    ],
)
def test_an_approved_identity_requires_all_three_actual_facts(changes) -> None:
    scene = _ApprovedScene()
    with pytest.raises(ValueError, match=r'created|command|user'):
        scene.approval(**changes)
    assert scene.killed == []


@pytest.mark.parametrize('which', ['birth', 'command', 'unknown-birth'])
def test_an_approved_root_identity_mismatch_refuses_before_any_kill(which) -> None:
    scene = _ApprovedScene()
    approved = scene.approval()
    if which == 'birth':
        scene.created[30] += 1
    elif which == 'command':
        scene.table[30] = (1, 'python another_controller.py')
    else:
        scene.created[30] = None
    code, _ = scene.stop(approved=approved)
    assert code == 3
    assert scene.killed == []


def test_an_approved_identity_does_not_adopt_old_ppid_foreign_children_or_their_descendants() -> None:
    scene = _ApprovedScene()
    scene.table |= {25: (30, 'foreign pre-existing child'), 26: (25, 'its foreign child')}
    scene.created |= {25: 80, 26: 103}
    assert scene.stop()[0] == 0
    assert scene.killed == [30, 32, 31]
    assert {25, 26, 40} <= scene.table.keys()


def test_equal_birth_stamps_preserve_a_real_fast_spawn_edge() -> None:
    scene = _ApprovedScene()
    scene.created[31] = scene.created[32] = 100
    assert scene.stop()[0] == 0
    assert scene.killed == [30, 32, 31]


def test_an_unreadable_child_identity_cannot_be_treated_as_none_equals_none() -> None:
    scene = _ApprovedScene()
    scene.created[32] = None
    assert scene.stop()[0] == 3
    assert scene.killed == []


@pytest.mark.parametrize('mutation', ['birth', 'command', 'ppid', 'growth'])
def test_a_fresh_subtree_change_stops_further_kills_and_reports_partial(mutation) -> None:
    scene = _ApprovedScene()

    def change(pid) -> None:
        if pid != 30:
            return
        if mutation == 'birth':
            scene.created[32] += 1
        elif mutation == 'command':
            scene.table[32] = (31, 'foreign replacement command')
        elif mutation == 'ppid':
            scene.table[32] = (40, scene.table[32][1])
        else:
            scene.table[33] = (31, 'a newly spawned worker')
            scene.created[33] = 104

    scene.after_kill = change
    code, lines = scene.stop()
    assert code == 3
    assert scene.killed == [30]
    assert 'partial' in '\n'.join(lines).lower()
    assert {31, 32, 40} <= scene.table.keys()


def test_the_approved_root_is_rechecked_against_a_fresh_table_before_it_is_stopped() -> None:
    scene = _ApprovedScene()
    snapshot = dict(scene.table)
    approved = scene.approval()
    scene.table[30] = (1, 'python a_different_root.py')
    code, _ = door.stop(
        30,
        snapshot,
        dry_run=False,
        approved=approved,
        born=scene.born,
        fresh=scene.fresh,
        kill=scene.kill,
        gone=lambda _pid, _seconds: True,
    )
    assert code == 3
    assert scene.killed == []


def test_approved_dry_run_has_the_same_identity_checks_but_never_kills() -> None:
    scene = _ApprovedScene()
    code, lines = scene.stop(dry_run=True)
    assert code == 0
    assert scene.killed == []
    assert next(line for line in lines if 'would stop' in line).startswith('would stop 30')


@pytest.mark.parametrize('role', ['self', 'ancestor'])
def test_an_explicit_approval_never_allows_stopping_self_or_an_ancestor(monkeypatch, role) -> None:
    scene = _ApprovedScene()
    if role == 'self':
        monkeypatch.setattr(door.os, 'getpid', lambda: 30)
    else:
        scene.table[50] = (30, 'the caller')
        monkeypatch.setattr(door.os, 'getpid', lambda: 50)
    assert scene.stop()[0] == 3
    assert scene.killed == []


@pytest.mark.parametrize(
    'arguments',
    [
        ['--approved-created', '100'],
        ['--approved-command-sha256', 'a' * 64],
        ['--approved-user-words', 'Stop my exact controller.'],
        ['--approved-created', '100', '--approved-command-sha256', 'a' * 64],
        ['--approved-created', '100', '--approved-user-words', 'Stop my exact controller.'],
        ['--approved-command-sha256', 'a' * 64, '--approved-user-words', 'Stop my exact controller.'],
    ],
)
def test_half_filled_approval_cli_inputs_are_rejected_before_process_census(monkeypatch, arguments) -> None:
    def forbidden() -> None:
        msg = 'an incomplete authorization reached the process census'
        raise AssertionError(msg)

    monkeypatch.setattr(door, 'process_table', forbidden)
    with pytest.raises(SystemExit) as error:
        door.main(['--pid', '30', *arguments])
    assert error.value.code == 2


def test_stopping_the_proven_parent_allows_its_same_child_to_be_reparented() -> None:
    scene = _ApprovedScene()

    def reparent(pid) -> None:
        if pid == 30:
            scene.table[31] = (1, scene.table[31][1])

    scene.after_kill = reparent
    assert scene.stop()[0] == 0
    assert scene.killed == [30, 32, 31]


def test_preexisting_reparenting_is_rejected_before_stopping_the_controller() -> None:
    scene = _ApprovedScene()
    snapshot = dict(scene.table)
    approved = scene.approval()
    scene.table[31] = (40, scene.table[31][1])
    code, _ = door.stop(
        30,
        snapshot,
        dry_run=False,
        approved=approved,
        born=scene.born,
        fresh=scene.fresh,
        kill=scene.kill,
        gone=lambda _pid, _seconds: True,
    )
    assert code == 3
    assert scene.killed == []


def test_a_controller_that_did_not_stop_does_not_license_stopping_its_children() -> None:
    scene = _ApprovedScene()
    attempted = []
    code, lines = door.stop(
        30,
        dict(scene.table),
        dry_run=False,
        approved=scene.approval(),
        born=scene.born,
        fresh=scene.fresh,
        kill=attempted.append,
        gone=lambda _pid, _seconds: False,
    )
    assert code == 3
    assert attempted == [30]
    assert 'partial' in '\n'.join(lines).lower()
    assert {31, 32, 40} <= scene.table.keys()


def test_the_real_approved_python_controller_and_child_stop_without_stopping_a_bystander(tmp_path) -> None:
    script = tmp_path / 'controller.py'
    receipt = tmp_path / 'pids.json'
    script.write_text(
        'import json, os, pathlib, subprocess, sys, time\n'
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        f'p = pathlib.Path({str(receipt.with_suffix(".tmp"))!r})\n'
        'p.write_text(json.dumps([os.getpid(), child.pid]))\n'
        f'p.replace({str(receipt)!r})\n'
        'time.sleep(120)\n',
        encoding='utf-8',
    )
    run = subprocess.Popen([sys.executable, str(script)])
    bystander = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])
    child, child_created = None, None
    try:
        deadline = time.monotonic() + 20
        while not receipt.is_file() and time.monotonic() < deadline:
            time.sleep(0.05)
        controller, child = json.loads(receipt.read_text())
        child_created = creation_stamp(child)
        table = process_table()
        created = creation_stamp(controller)
        assert created is not None
        assert child_created is not None
        approved = door.ApprovedRun(
            created=created,
            command_sha256=hashlib.sha256(table[controller][1].encode('utf-8')).hexdigest(),
            user_words='Stop only the controller and child this test just created.',
        )

        def gone(pid, seconds) -> bool:
            if pid == controller:
                try:
                    run.wait(timeout=seconds)
                except subprocess.TimeoutExpired:
                    return False
                return True
            deadline = time.monotonic() + seconds
            while pid_alive(pid) and time.monotonic() < deadline:
                time.sleep(0.05)
            return not pid_alive(pid)

        code, lines = door.stop(controller, table, dry_run=False, approved=approved, gone=gone)
        assert code == 0, lines
        assert run.poll() is not None
        assert gone(child, 20)
        assert bystander.poll() is None
    finally:
        if child is not None and child_created is not None and creation_stamp(child) == child_created:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(child, signal.SIGTERM)
        for proc in (run, bystander):
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=30)


def test_complete_approval_cli_passes_the_exact_identity_and_user_words_to_the_one_stop_owner(
    monkeypatch, tmp_path
) -> None:
    scene = _ApprovedScene()
    approved = scene.approval()
    calls = []

    def observed(pid, table, **kwargs: object) -> tuple[int, list[str]]:
        calls.append((pid, table, kwargs))
        return 0, ['would stop the approved controller']

    monkeypatch.setattr(door, 'process_table', scene.fresh)
    monkeypatch.setattr(door, 'stop', observed)
    words = 'Stop only the controller I just identified.'
    assert (
        door.main(
            [
                '--pid',
                '30',
                '--repo',
                str(tmp_path),
                '--dry-run',
                '--approved-created',
                '100',
                '--approved-command-sha256',
                approved.command_sha256,
                '--approved-user-words',
                words,
            ]
        )
        == 0
    )
    assert len(calls) == 1
    pid, table, options = calls[0]
    assert pid == 30
    assert table == scene.table
    assert options['dry_run'] is True
    actual = options['approved']
    assert actual.created == 100
    assert actual.command_sha256 == approved.command_sha256
    assert actual.user_words == words


def test_an_unreadable_empty_command_is_not_an_identity_even_when_its_empty_hash_matches() -> None:
    scene = _ApprovedScene()
    scene.table[30] = (1, '')
    assert scene.stop()[0] == 3
    assert scene.killed == []


def test_a_fresh_census_error_before_stopping_refuses_without_a_kill() -> None:
    scene = _ApprovedScene()

    def unreadable() -> dict:
        msg = 'process census is unreadable'
        raise OSError(msg)

    scene.fresh = unreadable
    code, lines = scene.stop()
    assert code == 3
    assert scene.killed == []
    assert 'unreadable' in '\n'.join(lines)


def test_a_census_error_after_stopping_the_controller_reports_partial() -> None:
    scene = _ApprovedScene()

    def unreadable_after_stop() -> dict:
        if scene.killed:
            msg = 'process census is unreadable'
            raise OSError(msg)
        return dict(scene.table)

    scene.fresh = unreadable_after_stop
    code, lines = scene.stop()
    assert code == 3
    assert scene.killed == [30]
    assert 'partial' in '\n'.join(lines).lower()


def test_a_failed_stop_reports_partial_and_does_not_continue_into_children() -> None:
    scene = _ApprovedScene()
    attempts = []

    def denied(pid) -> None:
        attempts.append(pid)
        msg = 'process stop refused'
        raise PermissionError(msg)

    scene.kill = denied
    code, lines = scene.stop()
    assert code == 3
    assert attempts == [30]
    assert 'partial' in '\n'.join(lines).lower()
