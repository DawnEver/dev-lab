"""The LOCAL worktree door, driven on a real repository: planted prunable, kept and orphan trees."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from lab_commons.dev.famtests.visibility import commit, plant_checkout
from lab_commons.dev.worktrees import main, prune

_GIT = shutil.which('git') or 'git'


def _run(cwd: Path, *args: str) -> None:
    subprocess.run([_GIT, *args], cwd=cwd, check=True, capture_output=True, timeout=60)


def _planted(tmp_path: Path) -> Path:
    work = plant_checkout(tmp_path, trunk='main').work
    (work / '.gitignore').write_text('output/\n__pycache__/\n.claude/\n', encoding='utf-8')
    _run(work, 'add', '.gitignore')
    _run(work, 'commit', '-q', '-m', 'ignore')
    _run(work, 'push', '-q', 'origin', 'main')
    home = work / '.claude' / 'worktrees'
    _run(work, 'worktree', 'add', '--detach', str(home / 'done'), 'origin/main')
    (home / 'done' / 'output').mkdir()
    (home / 'done' / 'output' / 'result.txt').write_text('keep me', encoding='utf-8')
    (home / 'done' / '__pycache__').mkdir()
    _run(work, 'worktree', 'add', '-b', 'wip', str(home / 'wip'), 'origin/main')
    commit(home / 'wip', 'wip.txt')
    _run(work, 'worktree', 'add', '--detach', str(home / 'dirty'), 'origin/main')
    (home / 'dirty' / 'scratch.txt').write_text('untracked', encoding='utf-8')
    (home / 'leftover').mkdir()
    (home / 'leftover' / 'note.txt').write_text('agent output', encoding='utf-8')
    return work


def _archived(work: Path, name: str) -> list[str]:
    return [p.read_text(encoding='utf-8') for p in (work / 'output' / 'logs').rglob(name)]


def test_the_census_touches_nothing(tmp_path: Path) -> None:
    work = _planted(tmp_path)
    lines = prune(work, apply=False) or ()
    assert any(line.startswith('prunable') and 'done' in line for line in lines)
    assert any(line.startswith('orphan') and 'leftover' in line for line in lines)
    assert (work / '.claude' / 'worktrees' / 'done' / 'output' / 'result.txt').is_file()
    assert (work / '.claude' / 'worktrees' / 'leftover').is_dir()


def test_prune_archives_before_removing_and_keeps_what_is_not_safe(tmp_path: Path) -> None:
    work = _planted(tmp_path)
    home = work / '.claude' / 'worktrees'
    assert main(['--root', str(work), '--prune']) == 0
    assert not (home / 'done').exists()
    assert _archived(work, 'result.txt') == ['keep me'], 'ignored output/ is archived, never deleted'
    assert (home / 'wip' / 'wip.txt').is_file(), 'HEAD on no remote branch: kept'
    assert (home / 'dirty' / 'scratch.txt').is_file(), 'untracked files: kept'
    assert not (home / 'leftover').exists()
    assert _archived(work, 'note.txt') == ['agent output']
