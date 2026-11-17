"""The ARCHIVED-TREE REMOVAL door, ``worktrees --remove NAME``, on planted worktrees and the REAL deny engine.

The wall it closes (2026-11-17): ``--archive`` reported "safe to remove: git worktree remove --force NAME", a
command RECURSIVE-DELETE refuses, whose remedy named only ``branchset --discard <branch>`` -- no door for a
DETACHED tree. So the archive verdict now names this door, and the row names it too.

Planted removals: an archived detached tree and an archived branch tree go. Planted controls, one per way the door
could remove what it must not: an un-archived dirty tree, a tree changed after its archive (a tracked edit, a new
untracked file), a detached commit no ref holds, a live tree, the main checkout, and the raw git removal, which
stays refused.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from datetime import date
from pathlib import Path

import pytest
from lab_commons.census import Process

from dev_lab.dev import agenthooks
from dev_lab.dev.famtests.visibility import plant_checkout
from dev_lab.dev.hook_adoption import HookAdoption, render
from dev_lab.dev.worktree_archive import archive
from dev_lab.dev.worktrees import main, remove

_GIT = shutil.which('git') or 'git'
_DAY = date(2026, 11, 17)


def _run(cwd: Path, *args: str) -> None:
    subprocess.run([_GIT, *args], cwd=cwd, check=True, capture_output=True, timeout=60)


def _idle() -> tuple[Process, ...]:
    return ()


@pytest.fixture(scope='module')
def rules(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The registry rendered exactly as a repo ships it."""
    path = tmp_path_factory.mktemp('rules') / 'deny-rules.json'
    path.write_text(render(HookAdoption(app_name='suite', remedies={})), encoding='utf-8')
    return path


@pytest.fixture
def work(tmp_path: Path) -> Path:
    """A main checkout ignoring ``output/`` and ``.claude/``: a DETACHED tree ``loose``, a branch tree ``lane``."""
    root = plant_checkout(tmp_path, trunk='main').work
    (root / '.gitignore').write_text('output/\n.claude/\n.venv/\n', encoding='utf-8')
    _run(root, 'add', '.gitignore')
    _run(root, 'commit', '-q', '-m', 'ignore')
    home = root / '.claude' / 'worktrees'
    _run(root, 'worktree', 'add', '-q', '--detach', str(home / 'loose'), 'HEAD')
    _run(root, 'worktree', 'add', '-q', '-b', 'lane', str(home / 'lane'))
    return root


def _tree(work: Path, name: str) -> Path:
    return work / '.claude' / 'worktrees' / name


def _registered(work: Path) -> str:
    return subprocess.run(
        [_GIT, 'worktree', 'list', '--porcelain'],
        cwd=work,
        check=True,
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=60,
    ).stdout


def _verdict(work: Path, name: str) -> str:
    lines = archive(work, name, census=_idle, today=_DAY).lines()
    return next(line for line in lines if 'safe to remove' in line)


def test_the_archive_verdict_names_a_door_the_deny_engine_admits(work: Path, rules: Path) -> None:
    """EVERY-WALL-TEACHES: the command the verdict hands out passes the REAL engine, and it is this door."""
    verdict = _verdict(work, 'loose')
    assert verdict.startswith('safe to remove: '), verdict
    command = verdict.removeprefix('safe to remove: ')
    assert '-m dev_lab.dev.worktrees' in command
    assert command.endswith('--remove loose'), command
    assert agenthooks.decide(command, rules) is None, command


def test_the_raw_git_removal_stays_refused_and_its_refusal_names_the_door(work: Path, rules: Path) -> None:
    """PLANTED CONTROL: the door is not an opening in the row -- the raw removal is still RECURSIVE-DELETE."""
    reason = agenthooks.decide(f'git worktree remove --force {_tree(work, "loose").as_posix()}', rules)
    assert reason is not None
    assert 'RECURSIVE-DELETE' in reason
    assert 'dev_lab.dev.worktrees --remove <name>' in reason


def test_an_archived_detached_tree_is_removed(work: Path) -> None:
    tree = _tree(work, 'loose')
    (tree / 'notes.txt').write_text('untracked, saved by the archive', encoding='utf-8')
    assert archive(work, 'loose', census=_idle, today=_DAY).safe
    ok, line = remove(work, 'loose', census=_idle, quiet_s=0)
    assert ok, line
    assert line.startswith('removed'), line
    assert not tree.exists()
    assert tree.as_posix() not in _registered(work).replace('\\', '/')


def test_an_archived_branch_tree_is_removed_and_its_branch_stays(work: Path) -> None:
    assert archive(work, 'lane', census=_idle, today=_DAY).safe
    ok, line = remove(work, 'lane', census=_idle, quiet_s=0)
    assert ok, line
    assert not _tree(work, 'lane').exists()
    branches = subprocess.run(
        [_GIT, 'branch', '--list', 'lane'],
        cwd=work,
        check=True,
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=60,
    )
    assert 'lane' in branches.stdout, 'the branch goes through branchset, never this door'


def test_an_unarchived_dirty_tree_is_refused(work: Path) -> None:
    """PLANTED CONTROL: no archive, a tracked edit -- refused, the tree and its edit untouched."""
    tree = _tree(work, 'loose')
    (tree / 'base.txt').write_text('only here', encoding='utf-8')
    ok, line = remove(work, 'loose', census=_idle, quiet_s=0)
    assert not ok
    assert 'refused' in line
    assert '--archive loose' in line, 'the refusal names its door'
    assert (tree / 'base.txt').read_text(encoding='utf-8') == 'only here'


def test_an_unarchived_clean_tree_is_refused_too(work: Path) -> None:
    """The archive is the precondition, not a judgement of what is lost: one rule, archive then remove."""
    ok, line = remove(work, 'loose', census=_idle, quiet_s=0)
    assert not ok
    assert '--archive loose' in line
    assert _tree(work, 'loose').is_dir()


@pytest.mark.parametrize('change', ['tracked', 'untracked'])
def test_a_tree_changed_after_its_archive_is_refused(work: Path, change: str) -> None:
    """PLANTED CONTROL: an archive that no longer matches the tree saves nothing of the change."""
    tree = _tree(work, 'loose')
    assert archive(work, 'loose', census=_idle, today=_DAY).safe
    target = tree / ('base.txt' if change == 'tracked' else 'later.txt')
    target.write_text('after the archive', encoding='utf-8')
    ok, line = remove(work, 'loose', census=_idle, quiet_s=0)
    assert not ok
    assert 'since its archive' in line
    assert '--archive loose' in line
    assert target.read_text(encoding='utf-8') == 'after the archive'


def test_a_detached_commit_no_ref_holds_is_refused(work: Path) -> None:
    """PLANTED CONTROL: the archive saves no commit; a commit only the detached HEAD holds dies with the tree."""
    tree = _tree(work, 'loose')
    (tree / 'new.txt').write_text('committed detached', encoding='utf-8')
    _run(tree, 'add', 'new.txt')
    _run(tree, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'detached work')
    archive(work, 'loose', census=_idle, today=_DAY)
    ok, line = remove(work, 'loose', census=_idle, quiet_s=0)
    assert not ok
    assert 'no ref contains' in line
    assert tree.is_dir()


def test_a_live_tree_is_refused(work: Path) -> None:
    """PLANTED CONTROL: another session working in the tree holds it."""
    tree = _tree(work, 'loose')
    assert archive(work, 'loose', census=_idle, today=_DAY).safe
    session = Process(77, 1, 'C:/node/node.exe', 'node claude', 600.0, str(tree))
    ok, line = remove(work, 'loose', census=lambda: (session,), quiet_s=0)
    assert not ok
    assert 'pid 77' in line
    assert tree.is_dir()


def test_the_main_checkout_and_an_unknown_name_are_refused(work: Path) -> None:
    for name in (work.name, 'nope'):
        ok, line = remove(work, name, census=_idle, quiet_s=0)
        assert not ok, name
        assert 'refused' in line
    assert work.is_dir()


def test_the_door_archives_then_removes_through_the_cli(work: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The CLI pair a person or an agent runs: ``--archive NAME`` then the ``--remove NAME`` it names."""
    assert main(['--root', str(work), '--archive', 'loose']) == 0
    old = time.time() - 2 * 3600
    for index in (work / '.git' / 'worktrees').glob('*/index'):
        os.utime(index, (old, old))
    assert main(['--root', str(work), '--remove', 'loose']) == 0
    assert 'removed' in capsys.readouterr().out
    assert not _tree(work, 'loose').exists()
