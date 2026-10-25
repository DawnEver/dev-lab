"""The LOCAL worktree door on a real repository: a landed tree goes with all git does not track (ruling 2026-10-25).

Planted refusals: a modified tracked file, a staged file, and a HEAD on no remote branch. Planted removals: a
tree with ignored artefacts (a cache, ``.venv``, a build-written ``__version__.py``), one with an untracked file,
one with an ignored ``output/logs`` (moved home first), an unregistered directory holding files, and an EMPTY one.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from dev_lab.dev.famtests.visibility import commit, plant_checkout
from dev_lab.dev.worktrees import main, prune

_GIT = shutil.which('git') or 'git'
_BLOCKED = ('modified', 'staged', 'wip')
_GONE = ('done', 'untracked', 'ignored', 'leftover', 'empty')


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
    (home / 'leftover').mkdir()
    (home / 'leftover' / 'note.txt').write_text('agent output', encoding='utf-8')
    (home / 'empty' / 'nested').mkdir(parents=True)
    return work


def test_the_census_touches_nothing(tmp_path: Path) -> None:
    work = _planted(tmp_path)
    lines = prune(work, apply=False) or ()
    assert any(line.startswith('prunable') and 'done' in line for line in lines)
    assert any(line.startswith('prunable') and 'empty' in line for line in lines)
    assert (work / '.claude' / 'worktrees' / 'done').is_dir()
    assert (work / '.claude' / 'worktrees' / 'empty').is_dir()


def test_a_landed_tree_goes_with_everything_git_does_not_track(tmp_path: Path) -> None:
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
