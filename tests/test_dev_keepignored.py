"""``keepignored``: a path the old head tracked and the repo now ignores survives the move that untracks it."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from dev_lab.dev.keepignored import restore

_GIT = shutil.which('git') or 'git'


def _git(root: Path, *args: str) -> str:
    return subprocess.run([_GIT, *args], cwd=root, capture_output=True, encoding='utf-8', check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / 'repo'
    root.mkdir()
    _git(root, 'init', '-q', '-b', 'main')
    _git(root, 'config', 'user.email', 't@example.invalid')
    _git(root, 'config', 'user.name', 't')
    _git(root, 'config', 'core.hooksPath', str(tmp_path / 'no-hooks'))
    (root / 'ledger').mkdir()
    (root / 'ledger' / 'TASK.md').write_bytes(b'goal\r\n\x00binary-safe\n')
    (root / 'plain.txt').write_text('deleted for real\n')
    (root / 'kept.txt').write_text('stays tracked\n')
    _git(root, 'add', '-A')
    _git(root, 'commit', '-q', '-m', 'track all')
    return root


def _untrack_on_branch(root: Path) -> None:
    """On branch `move`: untrack ledger/ beside its .gitignore line, and really delete plain.txt."""
    _git(root, 'checkout', '-q', '-b', 'move')
    (root / '.gitignore').write_text('ledger/\n')
    _git(root, 'rm', '-q', '-r', '--cached', 'ledger')
    _git(root, 'rm', '-q', 'plain.txt')
    _git(root, 'add', '.gitignore')
    _git(root, 'commit', '-q', '-m', 'untrack the ledger')
    _git(root, 'checkout', '-q', 'main')


def test_a_merge_that_untracks_an_ignored_path_keeps_its_file(repo: Path) -> None:
    _untrack_on_branch(repo)
    _git(repo, 'merge', '-q', '--ff-only', 'move')
    assert not (repo / 'ledger' / 'TASK.md').exists(), 'git deletes it: the case the door exists for'
    assert restore(repo, 'ORIG_HEAD') == ['ledger/TASK.md']
    assert (repo / 'ledger' / 'TASK.md').read_bytes() == b'goal\r\n\x00binary-safe\n'
    assert _git(repo, 'ls-files', 'ledger') == '', 'restored as local state, never re-tracked'


def test_a_real_deletion_stays_deleted(repo: Path) -> None:
    """PLANTED CONTROL: plain.txt is untracked by the same commit but NOT ignored -- a deletion, kept deleted."""
    _untrack_on_branch(repo)
    _git(repo, 'merge', '-q', '--ff-only', 'move')
    restore(repo, 'ORIG_HEAD')
    assert not (repo / 'plain.txt').exists()


def test_an_existing_file_is_never_overwritten(repo: Path) -> None:
    """PLANTED CONTROL: the local ledger already holds newer bytes -- untouched."""
    _untrack_on_branch(repo)
    _git(repo, 'merge', '-q', '--ff-only', 'move')
    (repo / 'ledger').mkdir(exist_ok=True)
    (repo / 'ledger' / 'TASK.md').write_text('newer local\n')
    assert restore(repo, 'ORIG_HEAD') == []
    assert (repo / 'ledger' / 'TASK.md').read_text() == 'newer local\n'


def test_a_checkout_onto_the_untracking_commit_keeps_the_file(repo: Path) -> None:
    _untrack_on_branch(repo)
    _git(repo, 'checkout', '-q', 'move')
    assert restore(repo, 'HEAD@{1}') == ['ledger/TASK.md']
    assert not (repo / 'plain.txt').exists()


def test_a_rebase_onto_the_untracking_commit_keeps_the_file(repo: Path) -> None:
    _untrack_on_branch(repo)
    _git(repo, 'checkout', '-q', '-b', 'lane', 'main')
    (repo / 'kept.txt').write_text('lane edit\n')
    _git(repo, 'commit', '-q', '-am', 'lane work')
    before = _git(repo, 'rev-parse', 'HEAD')
    _git(repo, 'rebase', '-q', 'move')
    assert restore(repo, before) == ['ledger/TASK.md']


def test_a_still_tracked_path_and_an_unknown_previous_head_restore_nothing(repo: Path) -> None:
    """PLANTED CONTROL: same head on both sides, and a head that does not resolve (a new worktree)."""
    assert restore(repo, 'HEAD') == []
    assert restore(repo, 'no-such-ref') == []
