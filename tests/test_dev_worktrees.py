"""The LOCAL worktree door on a real repository: a landed tree goes with what git does not TRACK (ruling 2026-11-12).

Planted refusals: a modified tracked file, a staged file, a HEAD on no remote branch (holding an untracked file:
the CONTROL that it is the unlanded HEAD that keeps it). Planted removals: a tree with ignored artefacts (a cache,
``.venv``, a build-written ``__version__.py``), a landed tree with an untracked not-ignored file, an unregistered
directory holding files, an EMPTY one, and a landed tree whose ``output/logs`` is moved home, verified, first.
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

from dev_lab.dev import reclaimrun, worktrees
from dev_lab.dev.famtests.visibility import commit, plant_checkout
from dev_lab.dev.worktrees import main, prune

_GIT = shutil.which('git') or 'git'
_BLOCKED = ('modified', 'staged', 'wip')
_GONE = ('done', 'leftover', 'empty', 'untracked', 'ignored')


def _run(cwd: Path, *args: str) -> None:
    subprocess.run([_GIT, *args], cwd=cwd, check=True, capture_output=True, timeout=60)


def _planted(tmp_path: Path) -> Path:
    work = plant_checkout(tmp_path, trunk='main').work
    ignored = 'output/\n__pycache__/\n.claude/\n.venv/\n__version__.py\n'
    (work / '.gitignore').write_text(ignored, encoding='utf-8')
    _run(work, 'add', '.gitignore')
    _run(work, 'commit', '-q', '-m', 'ignore')
    _run(work, 'push', '-q', 'origin', 'main')
    home = work / '.claude' / 'worktrees'
    for name in ('done', 'modified', 'untracked', 'staged', 'ignored'):
        _run(work, 'worktree', 'add', '--detach', str(home / name), 'origin/main')
    (home / 'done' / '__pycache__').mkdir()
    (home / 'done' / '.venv' / 'Scripts').mkdir(parents=True)
    (home / 'done' / '.venv' / 'Scripts' / 'python.exe').write_text('', encoding='utf-8')
    (home / 'done' / 'src' / 'pkg').mkdir(parents=True)
    (home / 'done' / 'src' / 'pkg' / '__version__.py').write_text('version = "0"', encoding='utf-8')
    (home / 'modified' / 'base.txt').write_text('changed', encoding='utf-8')
    (home / 'untracked' / 'scratch.txt').write_text('untracked', encoding='utf-8')
    (home / 'staged' / 'new.txt').write_text('staged', encoding='utf-8')
    _run(home / 'staged', 'add', 'new.txt')
    (home / 'ignored' / 'output' / 'logs').mkdir(parents=True)
    (home / 'ignored' / 'output' / 'logs' / 'result.txt').write_text('keep me', encoding='utf-8')
    _run(work, 'worktree', 'add', '-b', 'wip', str(home / 'wip'), 'origin/main')
    commit(home / 'wip', 'wip.txt')
    (home / 'wip' / 'scratch.txt').write_text('CONTROL: kept because unlanded', encoding='utf-8')
    (home / 'leftover').mkdir()
    (home / 'leftover' / 'note.txt').write_text('agent output', encoding='utf-8')
    (home / 'empty' / 'nested').mkdir(parents=True)
    _settled(work)
    return work


def _settled(work: Path) -> None:
    """Age every linked tree's index past the live-session window (``dev_lab.dev.reclaim.QUIET_S``)."""
    old = time.time() - 2 * 3600
    for index in (work / '.git' / 'worktrees').glob('*/index'):
        os.utime(index, (old, old))


def test_the_census_touches_nothing(tmp_path: Path) -> None:
    work = _planted(tmp_path)
    lines = prune(work, apply=False) or ()
    assert any(line.startswith('prunable') and 'done' in line for line in lines)
    assert any(line.startswith('prunable') and 'empty' in line for line in lines)
    assert (work / '.claude' / 'worktrees' / 'done').is_dir()
    assert (work / '.claude' / 'worktrees' / 'empty').is_dir()


def test_a_landed_tree_goes_with_what_git_does_not_track_and_its_outputs_go_home(tmp_path: Path) -> None:
    work = _planted(tmp_path)
    home = work / '.claude' / 'worktrees'
    lines = prune(work, apply=True) or ()
    for name in _GONE:
        assert not (home / name).exists(), f'{name} must be reclaimed'
    for name in _BLOCKED:
        assert (home / name).is_dir(), f'{name} must be refused'
        assert any(line.startswith('kept') and name in line for line in lines)
    assert (work / 'output' / 'logs' / 'result.txt').read_text(encoding='utf-8') == 'keep me', 'moved home first'
    assert (home / 'staged' / 'new.txt').is_file()
    assert main(['--root', str(work), '--prune']) == 0


def _slow_prune(*_: object, **__: object) -> tuple[str, ...]:
    time.sleep(30)
    return ()


def test_a_hook_invoked_prune_detaches_and_returns_at_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A hook-invoked ``--prune`` detaches the background reclaim of the MAIN checkout and returns at once.

    INCIDENT 2026-11-12: old worktrees still carry an inline ``worktrees --prune`` SessionStart row (6+ min over
    108 trees), and every session started in one hung. The planted prune would take 30 s.
    """
    work = _planted(tmp_path)
    started: list[Path] = []
    monkeypatch.setattr(worktrees, 'prune', _slow_prune)
    monkeypatch.setattr(reclaimrun, 'detach', lambda root, **_: started.append(root))
    payload = json.dumps({'hook_event_name': 'SessionStart', 'cwd': str(work / '.claude' / 'worktrees' / 'done')})
    t0 = time.monotonic()
    assert main(['--prune'], stdin=io.StringIO(payload)) == 0
    assert time.monotonic() - t0 < 10.0
    assert started == [work.resolve()]


def test_without_a_hook_payload_the_prune_runs_inline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The CONTROL: a person's ``--prune`` (no payload) still prunes in the foreground and detaches nothing."""
    work = _planted(tmp_path)
    ran: list[Path] = []
    started: list[Path] = []
    monkeypatch.setattr(worktrees, 'prune', lambda root, **_: ran.append(root) or ())
    monkeypatch.setattr(reclaimrun, 'detach', lambda root, **_: started.append(root))
    assert main(['--prune', '--root', str(work)], stdin=io.StringIO('')) == 0
    assert (ran, started) == ([work.resolve()], [])
