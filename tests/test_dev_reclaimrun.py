"""Reclaim runs in the workflow: safe (a real edit is kept, its outputs go home first) and never blocking.

Planted on a real repository, both sides of every line the 2026-10-27 ruling drew: a tree with a real edit is
KEPT and listed in the run's log; one differing only in CR/LF, and one changing only a DECLARED generated path,
are reclaimed with their branches; a tree's ``output/logs`` lands in the main checkout before the tree goes; a
tree whose index moved within the hour is a live session and kept; a held lock makes a second run a no-op; and
the session-start hook acts only from a main checkout.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from dev_lab.dev import reclaimrun
from dev_lab.dev.agent_guard import RECLAIM_COMMAND, WIRING
from dev_lab.dev.famtests.visibility import plant_checkout
from dev_lab.dev.reclaim import blockers
from dev_lab.dev.reclaimrun import LOCK_NAME, held, main, main_checkout, run

_GIT = shutil.which('git') or 'git'
_LOG = Path('output/logs/26/10/27/run/result.txt')
_BRANCHSET = "\n[tool.lab_commons.branchset]\ntrunk = 'main'\nsessions = []\n"
_GENERATED = "\n[tool.lab_commons.worktrees]\ngenerated = ['uv.lock']\n"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        [_GIT, *args], cwd=cwd, check=True, capture_output=True, text=True, encoding='utf-8', timeout=60
    ).stdout


def _free(_: Path) -> bool:
    return False


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _quiet(tree: Path) -> None:
    """Age *tree*'s index past the live-session window."""
    index = Path(_git(tree, 'rev-parse', '--path-format=absolute', '--git-path', 'index').strip())
    old = time.time() - 2 * 3600
    os.utime(index, (old, old))


def _planted(tmp_path: Path) -> Path:
    work = plant_checkout(tmp_path, trunk='main').work
    _git(work, 'config', 'core.autocrlf', 'false')
    _write(work / '.gitignore', b'.claude/\n.venv/\noutput/\n')
    _write(work / 'text.txt', b'a\nb\n')
    _write(work / 'uv.lock', b'v1\n')
    with (work / 'pyproject.toml').open('a', encoding='utf-8') as handle:
        handle.write(_BRANCHSET + _GENERATED)
    _git(work, 'add', '.gitignore', 'text.txt', 'uv.lock', 'pyproject.toml')
    _git(work, 'commit', '-q', '-m', 'plant')
    _git(work, 'push', '-q', 'origin', 'main')
    home = work / '.claude' / 'worktrees'
    for name in ('edited', 'crlf', 'generated', 'live'):
        _git(work, 'worktree', 'add', '-q', '-b', name, str(home / name), 'origin/main')
    _write(home / 'edited' / 'text.txt', b'a\nREAL EDIT\n')
    _write(home / 'crlf' / 'text.txt', b'a\r\nb\r\n')
    _write(home / 'crlf' / _LOG, b'a run archive')
    _write(home / 'generated' / 'uv.lock', b'v2\n')
    for name in ('edited', 'crlf', 'generated'):
        _quiet(home / name)
    return work


@pytest.fixture
def planted(tmp_path: Path) -> Path:
    return _planted(tmp_path)


def test_only_real_tracked_edits_block(planted: Path) -> None:
    home = planted / '.claude' / 'worktrees'
    assert blockers(home / 'edited') == ('text.txt',)
    assert blockers(home / 'crlf') == (), 'a CR/LF-only difference is not work'
    assert blockers(home / 'generated', ('uv.lock',)) == (), 'a declared generated path is not work'
    assert blockers(home / 'generated') == ('uv.lock',), 'undeclared, the same change IS work'


def test_a_run_reclaims_the_landed_keeps_the_edited_and_logs_both(planted: Path) -> None:
    home = planted / '.claude' / 'worktrees'
    log = run(planted, occupied=_free)
    assert log is not None
    assert log.parent.name == 'reclaim'
    assert log.parent.parent.parent.parent.parent == planted / 'output' / 'logs'
    text = log.read_text(encoding='utf-8')
    for gone in ('crlf', 'generated'):
        assert not (home / gone).exists(), gone
        assert f'deleted  local   {gone}' in text, text
    for kept, why in (('edited', 'tracked changes'), ('live', 'a live session')):
        assert (home / kept).is_dir(), kept
        assert any(line.startswith('kept') and kept in line and why in line for line in text.splitlines()), text
    assert (home / 'edited' / 'text.txt').read_bytes() == b'a\nREAL EDIT\n', 'a real edit is never touched'
    assert (planted / _LOG).read_bytes() == b'a run archive', 'the run archive went home before the delete'
    assert set(_git(planted, 'branch', '--format=%(refname:short)').split()) == {'main', 'edited', 'live'}


def test_a_batch_bounds_the_removals_and_defers_the_rest(planted: Path) -> None:
    log = run(planted, batch=1, occupied=_free)
    assert log is not None
    lines = log.read_text(encoding='utf-8').splitlines()
    assert sum(line.startswith('removed') for line in lines) == 1
    assert sum(line.startswith('deferred') for line in lines) == 1


def test_a_held_lock_makes_the_second_run_a_no_op(planted: Path) -> None:
    home = planted / '.claude' / 'worktrees'
    with held(planted) as first:
        assert first
        assert run(planted, occupied=_free) is None
    assert (home / 'crlf').is_dir(), 'the blocked run touched nothing'
    assert not (planted / '.git' / LOCK_NAME).exists(), 'the lock is released'


def test_a_stale_lock_is_taken_over(planted: Path) -> None:
    lock = planted / '.git' / LOCK_NAME
    lock.write_text('1\n', encoding='utf-8')
    old = time.time() - 7 * 3600
    os.utime(lock, (old, old))
    assert run(planted, occupied=_free) is not None


def test_session_start_detaches_from_a_main_checkout_only(planted: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[Path] = []
    monkeypatch.setattr(reclaimrun, 'detach', lambda root, **_: started.append(root))
    linked = planted / '.claude' / 'worktrees' / 'live'
    assert main_checkout(linked) is None
    assert main_checkout(planted) == planted.resolve()
    for cwd in (linked, planted):
        assert main(['--session-start'], stdin=io.StringIO(json.dumps({'cwd': str(cwd)}))) == 0
    assert started == [planted.resolve()], 'a linked tree is somebody lease: no run'


def test_the_kit_wires_the_reclaim_at_session_start() -> None:
    assert any(w.event == 'SessionStart' and w.command == RECLAIM_COMMAND for w in WIRING)
    assert '--session-start' in RECLAIM_COMMAND
