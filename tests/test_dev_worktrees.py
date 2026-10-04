"""The LOCAL worktree door on a real repository: only a CLEAN tree goes (ruling 2026-10-04).

Planted refusals: a modified file, an untracked file, a staged file, an ignored ``output/``, a HEAD on
no remote branch, and an unregistered directory holding files. Planted removals: a clean tree with
only caches, and an EMPTY unregistered directory.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from lab_commons.dev.famtests.visibility import commit, plant_checkout
from lab_commons.dev.worktrees import main, prune

_GIT = shutil.which('git') or 'git'
_BLOCKED = ('modified', 'untracked', 'staged', 'ignored', 'wip')


def _run(cwd: Path, *args: str) -> None:
    subprocess.run([_GIT, *args], cwd=cwd, check=True, capture_output=True, timeout=60)


def _planted(tmp_path: Path) -> Path:
    work = plant_checkout(tmp_path, trunk='main').work
    (work / '.gitignore').write_text('output/\n__pycache__/\n.claude/\n', encoding='utf-8')
    _run(work, 'add', '.gitignore')
    _run(work, 'commit', '-q', '-m', 'ignore')
    _run(work, 'push', '-q', 'origin', 'main')
    home = work / '.claude' / 'worktrees'
    for name in ('done', 'modified', 'untracked', 'staged', 'ignored'):
        _run(work, 'worktree', 'add', '--detach', str(home / name), 'origin/main')
    (home / 'done' / '__pycache__').mkdir()
    (home / 'modified' / 'base.txt').write_text('changed', encoding='utf-8')
    (home / 'untracked' / 'scratch.txt').write_text('untracked', encoding='utf-8')
    (home / 'staged' / 'new.txt').write_text('staged', encoding='utf-8')
    _run(home / 'staged', 'add', 'new.txt')
    (home / 'ignored' / 'output').mkdir()
    (home / 'ignored' / 'output' / 'result.txt').write_text('keep me', encoding='utf-8')
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
    assert any(line.startswith('orphan') and 'empty' in line for line in lines)
    assert (work / '.claude' / 'worktrees' / 'done').is_dir()
    assert (work / '.claude' / 'worktrees' / 'empty').is_dir()


def test_only_a_clean_tree_and_an_empty_leftover_go(tmp_path: Path) -> None:
    work = _planted(tmp_path)
    home = work / '.claude' / 'worktrees'
    lines = prune(work, apply=True) or ()
    assert not (home / 'done').exists()
    assert not (home / 'empty').exists()
    for name in _BLOCKED:
        assert (home / name).is_dir(), f'{name} must be refused'
        assert any(line.startswith('kept') and name in line for line in lines)
    assert (home / 'ignored' / 'output' / 'result.txt').read_text(encoding='utf-8') == 'keep me'
    assert (home / 'staged' / 'new.txt').is_file()
    assert (home / 'leftover' / 'note.txt').is_file(), 'a leftover holding files is listed, never moved'
    assert any('note.txt' in line for line in lines)
    assert main(['--root', str(work), '--prune']) == 0
