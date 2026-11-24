"""The NAMED-TREE REMOVAL door, ``worktrees --remove NAME``, on planted worktrees and the REAL deny engine.

The wall it closes (2026-11-17): RECURSIVE-DELETE's remedy named only ``branchset --discard <branch>`` -- no door
for a DETACHED tree. D31 (user, 2026-11-17): the door removes a tree holding nothing unlanded and refuses one
holding work, naming its doors (merge it, or the user discards it) -- the work is never saved aside.

Planted removals: a clean detached tree and a clean branch tree go. Planted controls, one per way the door could
remove what it must not: a tracked edit, an untracked not-ignored file (nothing written under ``output/``), a
detached commit no ref holds, a live tree, the main checkout, and the raw git removal, which stays refused.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from lab_commons.census import Process

from dev_lab.dev import agenthooks
from dev_lab.dev.famtests.visibility import plant_checkout
from dev_lab.dev.hook_adoption import HookAdoption, render
from dev_lab.dev.worktrees import main, remove, worktrees_door

_GIT = shutil.which('git') or 'git'


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


def test_the_remove_door_passes_the_deny_engine(work: Path, rules: Path) -> None:
    """EVERY-WALL-TEACHES: the door the RECURSIVE-DELETE remedy names passes the REAL engine."""
    command = worktrees_door(work, '--remove loose')
    assert agenthooks.decide(command, rules) is None, command


def test_the_raw_git_removal_stays_refused_and_its_refusal_names_the_door(work: Path, rules: Path) -> None:
    """PLANTED CONTROL: the door is not an opening in the row -- the raw removal is still RECURSIVE-DELETE."""
    reason = agenthooks.decide(f'git worktree remove --force {_tree(work, "loose").as_posix()}', rules)
    assert reason is not None
    assert 'RECURSIVE-DELETE' in reason
    assert 'dev_lab.dev.worktrees --remove <name>' in reason


def test_a_clean_detached_tree_is_removed_its_outputs_home(work: Path) -> None:
    tree = _tree(work, 'loose')
    log = tree / 'output' / 'logs' / 'run.txt'
    log.parent.mkdir(parents=True)
    log.write_text('ignored run output', encoding='utf-8')
    ok, line = remove(work, 'loose', census=_idle, quiet_s=0)
    assert ok, line
    assert line.startswith('removed'), line
    assert not tree.exists()
    assert (work / 'output' / 'logs' / 'run.txt').read_text(encoding='utf-8') == 'ignored run output'
    assert tree.as_posix() not in _registered(work).replace('\\', '/')


def test_a_clean_branch_tree_is_removed_and_its_branch_stays(work: Path) -> None:
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


@pytest.mark.parametrize('change', ['tracked', 'untracked'])
def test_a_tree_holding_unlanded_work_is_kept_with_its_doors_and_nothing_is_parked(work: Path, change: str) -> None:
    """D31 PLANTED: an uncommitted edit or untracked file keeps the tree; nothing is written under ``output/``."""
    tree = _tree(work, 'loose')
    target = tree / ('base.txt' if change == 'tracked' else 'later.txt')
    target.write_text('only here', encoding='utf-8')
    ok, line = remove(work, 'loose', census=_idle, quiet_s=0)
    assert not ok
    assert line.startswith('refused'), line
    assert 'land it through a PR' in line
    assert '--discard <branch> --approved' in line
    assert target.read_text(encoding='utf-8') == 'only here'
    assert not (work / 'output').exists(), 'D31: nothing is parked'


def test_a_detached_commit_no_ref_holds_is_refused(work: Path) -> None:
    """PLANTED CONTROL: a commit only the detached HEAD holds dies with the tree."""
    tree = _tree(work, 'loose')
    (tree / 'new.txt').write_text('committed detached', encoding='utf-8')
    _run(tree, 'add', 'new.txt')
    _run(tree, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'detached work')
    ok, line = remove(work, 'loose', census=_idle, quiet_s=0)
    assert not ok
    assert 'no ref contains' in line
    assert tree.is_dir()


def test_a_live_tree_is_refused(work: Path) -> None:
    """PLANTED CONTROL: another session working in the tree holds it."""
    tree = _tree(work, 'loose')
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


def test_the_door_removes_through_the_cli(work: Path, capsys: pytest.CaptureFixture[str]) -> None:
    old = time.time() - 2 * 3600
    for index in (work / '.git' / 'worktrees').glob('*/index'):
        os.utime(index, (old, old))
    assert main(['--root', str(work), '--remove', 'loose']) == 0
    assert 'removed' in capsys.readouterr().out
    assert not _tree(work, 'loose').exists()


def test_a_tree_whose_directory_is_already_gone_is_pruned_not_crashed_on(work: Path) -> None:
    """A tree whose directory is already gone is pruned (dev-lab#791 wall 1).

    A timed-out removal left the record but not the directory; the next ``--remove`` crashed
    with ``git could not say which refs contain  in <tree>``. A gone directory holds nothing: its record is pruned.
    PLANTED CONTROL: the sibling tree, whose directory stands, is untouched.
    """
    shutil.rmtree(_tree(work, 'loose'))
    removed, line = remove(work, 'loose', census=_idle)
    assert removed, line
    assert 'already gone' in line
    assert not any(row.endswith('loose') for row in _registered(work).splitlines())
    assert _tree(work, 'lane').is_dir()


def test_a_submodule_at_another_commit_names_its_checkout_door_not_discard(work: Path, tmp_path: Path) -> None:
    """A drifted submodule names its real door (dev-lab#791 wall 2).

    A submodule checked out at another commit read as ``tracked changes`` and named ``branchset --discard``; the
    remedy is checking out the recorded sha. PLANTED CONTROL: a tracked edit beside it still names the unlanded
    doors.
    """
    (tmp_path / 'sub').mkdir()
    sub = plant_checkout(tmp_path / 'sub', trunk='main').work
    _run(work, '-c', 'protocol.file.allow=always', 'submodule', 'add', '-q', str(sub), 'vendored')
    _run(work, 'commit', '-q', '-m', 'vendor')
    tree = _tree(work, 'lane')
    _run(tree, 'merge', '-q', '--ff-only', 'main')
    _run(tree, '-c', 'protocol.file.allow=always', 'submodule', 'update', '-q', '--init')
    (tree / 'vendored' / 'drift.txt').write_text('x\n', encoding='utf-8')
    _run(tree / 'vendored', 'add', 'drift.txt')
    _run(tree / 'vendored', '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'drift')
    removed, line = remove(work, 'lane', census=_idle)
    assert not removed
    assert 'submodule update --checkout' in line
    assert 'vendored' in line
    assert 'branchset --discard' not in line
    (tree / '.gitignore').write_text('edited\n', encoding='utf-8')
    removed, line = remove(work, 'lane', census=_idle)
    assert not removed
    assert 'branchset --discard' in line


def test_a_just_used_tree_is_refused_naming_the_quiet_wait(work: Path) -> None:
    """O46 (2026-11-19): the door refused a tree used minutes before; the refusal says how long to wait.

    PLANTED CONTROL: the same tree with no quiet window is removed.
    """
    ok, line = remove(work, 'loose', census=_idle)
    assert not ok
    assert 'index changed' in line, line
    assert 're-run once it has been quiet 60 min' in line, line
    assert _tree(work, 'loose').exists()
    ok, line = remove(work, 'loose', census=_idle, quiet_s=0)
    assert ok, line
