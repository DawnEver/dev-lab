"""CLONE-REMOVE: a whole redundant clone goes only through its door, and only when nothing in it is unique.

Real git (a bare origin and its clone). PLANTED CONTROLS: a clone with ONE unpushed commit is never removed; nor
one with an untracked file, a stash, a live holder or a machine-file ``[repos]`` row naming it; a clone with none of
those, approved, is gone with its linked worktree, and the line echoes the user's words.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest
from _branch_repos import clone_pair
from _forge_fake import run_git
from lab_commons.census import Process

from dev_lab.dev import cloneremove
from dev_lab.dev.liverun import Census


def _clone(tmp_path: Path) -> Path:
    _origin, work = clone_pair(tmp_path)
    run_git(work, 'checkout', '-q', '-B', 'integrate/main', 'origin/integrate/main')
    return work


def _remove(
    clone: Path,
    *,
    approved: str = 'user 2026-11-19: drop the redundant clone',
    census: Census = tuple,
    declared: Mapping[str, str] | None = None,
) -> tuple[int, str]:
    return cloneremove.remove(clone, approved, census=census, declared={} if declared is None else declared)


def test_a_clean_pushed_clone_is_removed_with_its_worktrees_and_the_words_recorded(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    run_git(
        clone,
        'worktree',
        'add',
        '-q',
        '-b',
        'pr/t/x',
        str(clone / '.claude' / 'worktrees' / 'x'),
        'origin/integrate/main',
    )
    code, line = _remove(clone)
    assert code == 0, line
    assert not clone.exists()
    assert 'approved: "user 2026-11-19: drop the redundant clone"' in line


def test_one_unpushed_commit_keeps_the_clone(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    (clone / 'u.txt').write_text('u\n', encoding='utf-8')
    run_git(clone, 'add', 'u.txt')
    run_git(clone, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--no-verify', '-m', 'u')
    code, line = _remove(clone)
    assert code == 1
    assert clone.is_dir(), 'PLANTED: an unpushed commit is never removed'
    assert 'integrate/main' in line
    assert 'on no remote' in line


def test_untracked_work_keeps_the_clone(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    (clone / 'new.txt').write_text('n\n', encoding='utf-8')
    code, line = _remove(clone)
    assert code == 1
    assert clone.is_dir()
    assert 'uncommitted' in line


def test_a_stash_keeps_the_clone(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    (clone / 'README.md').write_text('changed\n', encoding='utf-8')
    run_git(clone, '-c', 'user.name=t', '-c', 'user.email=t@t', 'stash', '-q')
    code, line = _remove(clone)
    assert code == 1
    assert clone.is_dir()
    assert 'stash' in line


def test_a_live_holder_keeps_the_clone(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    holder = Process(4242, 1, 'python', 'python -m x', 60.0, str(clone))
    code, line = _remove(clone, census=lambda: (holder,))
    assert code == 1
    assert clone.is_dir()
    assert '4242' in line


def test_a_declared_consumer_keeps_the_clone(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    code, line = _remove(clone, declared={'repos.thing': str(clone)})
    assert code == 1
    assert clone.is_dir()
    assert 'repos.thing' in line


def test_no_words_no_removal(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    code, _line = _remove(clone, approved='  ')
    assert code == 1
    assert clone.is_dir()


@pytest.mark.parametrize('target', ['not-a-repo', 'linked'])
def test_only_a_main_checkout_is_a_clone(tmp_path: Path, target: str) -> None:
    clone = _clone(tmp_path)
    if target == 'linked':
        path = clone / '.claude' / 'worktrees' / 'y'
        run_git(clone, 'worktree', 'add', '-q', '-b', 'pr/t/y', str(path), 'origin/integrate/main')
    else:
        path = tmp_path / 'plain'
        path.mkdir()
    code, _line = _remove(path)
    assert code == 1
    assert path.is_dir()
