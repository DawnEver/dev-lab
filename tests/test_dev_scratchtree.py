"""A THROWAWAY worktree is a DISPOSABLE lease: one door makes it, one removes it, and reclaim takes it once quiet.

Incident 2026-11-10 (a consumer, three times): a detached base tree made to diff tests against was kept by reclaim
as ``not landed`` and a submodule checkout made ``git worktree remove`` fail, so each needed the user. Planted on a
real repository: a disposable detached tree holding a submodule checkout and scratch files is removed and its
registration pruned; refused and left whole are an undeclared detached tree, a disposable one with a tracked edit,
one whose HEAD is a commit no ref holds, one a live process holds, and a path that is not a linked worktree.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from dev_lab.dev.famtests.visibility import commit, plant_checkout
from dev_lab.dev.reclaim import discard, disposable_base, reclaim, scratch
from dev_lab.dev.worktrees import main

_GIT = shutil.which('git') or 'git'
_FILE_PROTOCOL = ('-c', 'protocol.file.allow=always')


def _run(cwd: Path, *args: str) -> str:
    return subprocess.run(
        [_GIT, *args], cwd=cwd, check=True, capture_output=True, text=True, encoding='utf-8', timeout=60
    ).stdout


def _free(_: Path) -> bool:
    return False


def _repo(tmp_path: Path) -> Path:
    work = plant_checkout(tmp_path, trunk='main').work
    (work / '.gitignore').write_text('.claude/\n', encoding='utf-8')
    library = tmp_path / 'library'
    library.mkdir()
    _run(library, 'init', '-q')
    commit(library, 'part.txt')
    _run(work, *_FILE_PROTOCOL, 'submodule', 'add', '-q', str(library), 'cases/library')
    _run(work, 'add', '.gitignore')
    _run(work, 'commit', '-q', '-m', 'submodule')
    _run(work, 'push', '-q', 'origin', 'main')
    return work


def _refused(line: str, why: str) -> bool:
    return line.startswith('refused') and why in line


def _registered(work: Path) -> set[str]:
    return {line.split()[1] for line in _run(work, 'worktree', 'list', '--porcelain').splitlines() if ' ' in line}


def test_a_disposable_tree_with_a_submodule_is_removed_and_pruned(tmp_path: Path) -> None:
    work = _repo(tmp_path)
    made = scratch(work, 'base', 'HEAD')
    tree = work / '.claude' / 'worktrees' / 'base'
    assert made.startswith('made'), made
    assert disposable_base(tree) == _run(work, 'rev-parse', 'HEAD').strip()
    _run(tree, *_FILE_PROTOCOL, 'submodule', 'update', '--init', '-q')
    assert (tree / 'cases' / 'library' / 'part.txt').is_file()
    (tree / 'probe.log').write_text('scratch', encoding='utf-8')  # untracked: scratch the declaration disowns

    assert discard(work, 'base', occupied=_free).startswith('removed'), 'a quiet disposable tree goes'
    assert not tree.exists()
    assert tree.as_posix() not in {Path(p).as_posix() for p in _registered(work)}
    assert not (work / '.git' / 'worktrees' / 'base').exists(), 'the admin directory and its modules go too'


def test_an_undeclared_detached_tree_is_refused(tmp_path: Path) -> None:
    work = _repo(tmp_path)
    tree = work / '.claude' / 'worktrees' / 'plain'
    _run(work, 'worktree', 'add', '-q', '--detach', str(tree), 'HEAD')
    line = discard(work, 'plain', occupied=_free)
    assert _refused(line, 'not declared disposable'), line
    assert (tree / '.git').is_file()


def test_a_tracked_edit_or_an_unheld_commit_refuses_it(tmp_path: Path) -> None:
    work = _repo(tmp_path)
    home = work / '.claude' / 'worktrees'
    scratch(work, 'edited', 'HEAD')
    (home / 'edited' / '.gitignore').write_text('changed\n', encoding='utf-8')
    scratch(work, 'committed', 'HEAD')
    commit(home / 'committed', 'new.txt')
    edited = discard(work, 'edited', occupied=_free)
    committed = discard(work, 'committed', occupied=_free)
    assert _refused(edited, 'tracked changes'), edited
    assert _refused(committed, 'no ref holds'), committed
    _run(home / 'committed', 'branch', 'keep')
    assert discard(work, 'committed', occupied=_free).startswith('removed'), 'a commit a branch holds is not lost'
    assert (home / 'edited' / '.gitignore').read_text(encoding='utf-8') == 'changed\n'


def test_a_live_holder_refuses_it(tmp_path: Path) -> None:
    work = _repo(tmp_path)
    scratch(work, 'held', 'HEAD')
    line = discard(work, 'held', occupied=lambda path: path.name == 'held')
    assert _refused(line, 'live'), line
    assert (work / '.claude' / 'worktrees' / 'held' / '.git').is_file()


def test_a_name_that_is_no_linked_tree_is_refused(tmp_path: Path) -> None:
    work = _repo(tmp_path)
    assert discard(work, '..', occupied=_free).startswith('refused')
    assert discard(work, 'absent', occupied=_free).startswith('refused')
    assert scratch(work, '../escape', 'HEAD').startswith('refused')
    assert (work / '.git').is_dir()


def test_reclaim_takes_a_quiet_disposable_tree_it_would_keep_as_not_landed(tmp_path: Path) -> None:
    work = _repo(tmp_path)
    home = work / '.claude' / 'worktrees'
    scratch(work, 'base', 'HEAD~1')
    _run(work, 'worktree', 'add', '-q', '--detach', str(home / 'plain'), 'HEAD~1')
    for name in ('base', 'plain'):
        (home / name / 'probe.log').write_text('scratch', encoding='utf-8')
    old = time.time() - 2 * 3600
    for index in (work / '.git' / 'worktrees').glob('*/index'):
        os.utime(index, (old, old))
    lines = reclaim(work, ('origin/main',), occupied=_free, runtimes={})
    assert lines is not None
    assert any(line.startswith('removed') and 'base' in line for line in lines), lines
    assert any(line.startswith('kept') and 'plain' in line for line in lines), 'an undeclared tree is still judged'


def test_the_door_makes_and_discards(tmp_path: Path) -> None:
    work = _repo(tmp_path)
    assert main(['--root', str(work), '--scratch', 'cmp', 'HEAD']) == 0
    assert main(['--root', str(work), '--discard', 'cmp']) == 0
    assert main(['--root', str(work), '--discard', 'cmp']) == 1
