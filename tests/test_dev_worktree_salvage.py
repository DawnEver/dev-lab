"""The SALVAGE door ``worktrees --salvage NAME`` and the ORPHAN door ``worktrees --reap-orphans``.

The wall they close (2026-11-24): a user-ruled cleanup of ~150 old worktrees had to save each dirty tree's work
before removing it. A salvage COMMIT ran the lint hooks, which judged scratch probes as a landing and refused
every one without a door; and ``*.reclaiming`` directories whose gitdir had vanished were refused by ``--remove``
(git lists no such tree) with no door at all. A salvage snapshot is a RECORD, not a landing: git plumbing, no
hooks. Planted controls: a live tree is refused naming its pid; a clean tree has nothing to salvage; a tree edited
after its salvage keeps the quiet wait; an orphan holding a file no reachable object holds is kept and named.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from lab_commons.census import Process

from dev_lab.dev import agenthooks
from dev_lab.dev.famtests.visibility import plant_checkout
from dev_lab.dev.hook_adoption import HookAdoption, render
from dev_lab.dev.salvage import reap_orphans, salvage
from dev_lab.dev.worktree_outputs import worktrees_door
from dev_lab.dev.worktrees import main, remove

_GIT = shutil.which('git') or 'git'


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        [_GIT, *args], cwd=cwd, check=True, capture_output=True, text=True, encoding='utf-8', timeout=60
    ).stdout.strip()


def _idle() -> tuple[Process, ...]:
    return ()


@pytest.fixture
def work(tmp_path: Path) -> Path:
    """A main checkout ignoring ``output/`` ``.claude/`` ``.venv/`` with a branch tree ``lane``."""
    root = plant_checkout(tmp_path, trunk='main').work
    (root / '.gitignore').write_text('output/\n.claude/\n.venv/\n', encoding='utf-8')
    _git(root, 'add', '.gitignore')
    _git(root, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'ignore')
    _git(root, 'worktree', 'add', '-q', '-b', 'lane', str(root / '.claude' / 'worktrees' / 'lane'))
    return root


def _tree(work: Path, name: str) -> Path:
    return work / '.claude' / 'worktrees' / name


def _dirty(work: Path) -> Path:
    tree = _tree(work, 'lane')
    (tree / '.gitignore').write_text('output/\n.claude/\n.venv/\nedited\n', encoding='utf-8')
    (tree / 'probe.py').write_text('print(1)\n', encoding='utf-8')
    (tree / '.venv').mkdir()
    (tree / '.venv' / 'junk.txt').write_text('ignored', encoding='utf-8')
    return tree


@pytest.mark.parametrize('flags', ['--salvage lane', '--reap-orphans'])
def test_the_doors_pass_the_deny_engine(work: Path, tmp_path: Path, flags: str) -> None:
    rules = tmp_path / 'deny-rules.json'
    rules.write_text(render(HookAdoption(app_name='suite', remedies={})), encoding='utf-8')
    command = worktrees_door(work, flags)
    assert agenthooks.decide(command, rules) is None, command


def test_a_dirty_tree_is_snapshotted_onto_its_salvage_branch_without_hooks(work: Path) -> None:
    tree = _dirty(work)
    hooks = work / '.git' / 'hooks'
    hooks.mkdir(exist_ok=True)
    (hooks / 'pre-commit').write_text('#!/bin/sh\nexit 1\n', encoding='utf-8')
    head = _git(tree, 'rev-parse', 'HEAD')
    ok, line = salvage(work, 'lane', census=_idle)
    assert ok, line
    sha = _git(work, 'rev-parse', 'salvage/lane')
    assert sha[:10] in line
    assert '2 files' in line, line
    assert _git(work, 'rev-parse', 'salvage/lane^') == head
    files = _git(work, 'ls-tree', '-r', '--name-only', 'salvage/lane').splitlines()
    assert 'probe.py' in files
    assert not any(name.startswith('.venv') for name in files), 'what git ignores is regenerable, never salvaged'
    assert _git(work, 'show', 'salvage/lane:.gitignore').endswith('edited')
    assert _git(tree, 'rev-parse', '--abbrev-ref', 'HEAD') == 'lane', 'the tree is not moved'
    assert (tree / 'probe.py').is_file()


def test_a_salvaged_tree_is_removed_without_the_quiet_wait(work: Path) -> None:
    _dirty(work)
    assert salvage(work, 'lane', census=_idle)[0]
    ok, line = remove(work, 'lane', census=_idle)
    assert ok, line
    assert not _tree(work, 'lane').exists()
    assert _git(work, 'show', 'salvage/lane:probe.py') == 'print(1)'


def test_a_tree_edited_after_its_salvage_keeps_every_refusal(work: Path) -> None:
    """PLANTED CONTROL: the salvage admits only the content it recorded."""
    tree = _dirty(work)
    assert salvage(work, 'lane', census=_idle)[0]
    (tree / 'later.py').write_text('x = 1\n', encoding='utf-8')
    ok, line = remove(work, 'lane', census=_idle, quiet_s=0)
    assert not ok
    assert 'nothing was removed' in line, line
    assert tree.is_dir()


def test_a_second_salvage_keeps_the_first(work: Path) -> None:
    tree = _dirty(work)
    assert salvage(work, 'lane', census=_idle)[0]
    first = _git(work, 'rev-parse', 'salvage/lane')
    (tree / 'later.py').write_text('x = 1\n', encoding='utf-8')
    assert salvage(work, 'lane', census=_idle)[0]
    parents = _git(work, 'rev-list', '--parents', '-n', '1', 'salvage/lane').split()
    assert first in parents


def test_a_clean_tree_has_nothing_to_salvage(work: Path) -> None:
    """PLANTED CONTROL: no empty salvage branch is made."""
    ok, line = salvage(work, 'lane', census=_idle)
    assert not ok
    assert 'nothing to salvage' in line
    assert not _git(work, 'branch', '--list', 'salvage/lane')


def test_a_live_tree_is_refused_naming_its_pid(work: Path) -> None:
    """PLANTED CONTROL: a process working in the tree may still be writing it."""
    tree = _dirty(work)
    session = Process(77, 1, 'C:/node/node.exe', 'node claude', 600.0, str(tree))
    ok, line = salvage(work, 'lane', census=lambda: (session,))
    assert not ok
    assert 'pid 77' in line
    assert not _git(work, 'branch', '--list', 'salvage/lane')


def test_salvage_through_the_cli(work: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _dirty(work)
    assert main(['--root', str(work), '--salvage', 'lane']) in {0, 1}
    out = capsys.readouterr().out
    assert 'salvage/lane' in out or 'pid' in out


def _orphan(work: Path) -> Path:
    """``lane`` moved aside to ``lane.reclaiming`` and its git record pruned: git lists it nowhere."""
    tree = _tree(work, 'lane')
    aside = tree.with_name('lane.reclaiming')
    tree.rename(aside)
    _git(work, 'worktree', 'prune')
    return aside


def test_an_orphan_whose_files_all_live_in_reachable_objects_is_reaped(work: Path) -> None:
    aside = _orphan(work)
    (aside / '.venv').mkdir()
    (aside / '.venv' / 'junk.txt').write_text('ignored, regenerable', encoding='utf-8')
    lines = reap_orphans(work, census=_idle)
    assert any(line.startswith('removed') and 'lane.reclaiming' in line for line in lines), lines
    assert not aside.exists()


def test_an_orphan_holding_unreachable_content_is_kept_and_named(work: Path) -> None:
    """PLANTED CONTROL: a file no reachable object holds is work that exists nowhere else."""
    aside = _orphan(work)
    (aside / 'only-here.txt').write_text('nowhere else', encoding='utf-8')
    lines = reap_orphans(work, census=_idle)
    assert any(line.startswith('kept') and 'only-here.txt' in line for line in lines), lines
    assert (aside / 'only-here.txt').is_file()


def test_a_registered_tree_is_never_an_orphan(work: Path) -> None:
    """PLANTED CONTROL: a tree git lists is ``--remove``'s, never reaped."""
    lines = reap_orphans(work, census=_idle)
    assert not any('lane' in line for line in lines), lines
    assert _tree(work, 'lane').is_dir()


def test_a_live_orphan_is_kept_naming_its_pid(work: Path) -> None:
    aside = _orphan(work)
    holder = Process(78, 1, 'C:/py/python.exe', 'python x', 600.0, str(aside))
    lines = reap_orphans(work, census=lambda: (holder,))
    assert any('pid 78' in line for line in lines), lines
    assert aside.is_dir()
