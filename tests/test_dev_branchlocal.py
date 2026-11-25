"""The LOCAL BRANCH DELETE door ``python -m dev_lab.dev.branchdelete --local [--apply]``.

Wall 2026-11-25: a user-ruled cleanup of ~170 landed local branches across the family had no local door that
both knew the rule (contained in origin's integration, in any origin ``pr/`` head, or in a declared ref) and
spared the live lanes: ``branchset --apply`` also reclaims worktrees, ``branchprune`` acts on origin.

Planted deletions: a branch inside ``origin/integrate/main``, one inside an origin ``pr/`` head, one inside a
``--contained-in`` ref. Planted controls: a branch with a commit no such ref holds, one checked out in a
worktree, one matching ``--keep``, the trunk itself, and a dry run that deletes nothing.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import dev_lab.dev.branchlocal as module
from dev_lab.dev.branchdelete import main
from dev_lab.dev.branchlocal import sweep_local

_GIT = shutil.which('git') or 'git'
_ID = ('-c', 'user.name=t', '-c', 'user.email=t@t')


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        [_GIT, *_ID, *args], cwd=cwd, check=True, capture_output=True, text=True, encoding='utf-8', timeout=60
    ).stdout.strip()


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name, encoding='utf-8')
    _git(repo, 'add', name)
    _git(repo, 'commit', '-q', '-m', name)
    return _git(repo, 'rev-parse', 'HEAD')


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Branches: landed-int, landed-pr, landed-declared, unique, busy (worktree), live/lane (keep)."""
    root = tmp_path / 'repo'
    root.mkdir()
    _git(root, 'init', '-q', '-b', 'main')
    _commit(root, 'base')
    _git(root, 'branch', 'landed-int')
    _commit(root, 'on-int')
    _git(root, 'update-ref', 'refs/remotes/origin/integrate/main', 'HEAD')
    _git(root, 'switch', '-q', '-c', 'landed-pr')
    _commit(root, 'pr-work')
    _git(root, 'update-ref', 'refs/remotes/origin/pr/x/y', 'HEAD')
    _git(root, 'switch', '-q', '-c', 'declared')
    _commit(root, 'declared-work')
    _git(root, 'branch', 'landed-declared', 'HEAD~0')
    _commit(root, 'declared-more')
    _git(root, 'switch', '-q', '-c', 'unique', 'main')
    _commit(root, 'only-here')
    _git(root, 'switch', '-q', 'main')
    _git(root, 'branch', 'busy', 'landed-int')
    _git(root, 'worktree', 'add', '-q', str(tmp_path / 'busy-tree'), 'busy')
    _git(root, 'branch', 'live/lane', 'landed-int')
    return root


def _branches(repo: Path) -> set[str]:
    return set(_git(repo, 'for-each-ref', '--format=%(refname:short)', 'refs/heads').split())


def test_a_dry_run_lists_and_deletes_nothing(repo: Path) -> None:
    before = _branches(repo)
    lines = sweep_local(repo, keep=('live/*',), contained_in=('declared',), apply=False)
    assert any(line.startswith('deletable') and 'landed-int' in line for line in lines), lines
    assert _branches(repo) == before


def test_apply_deletes_exactly_the_contained_branches(repo: Path) -> None:
    lines = sweep_local(repo, keep=('live/*',), contained_in=('declared',), apply=True)
    left = _branches(repo)
    assert {'landed-int', 'landed-pr', 'landed-declared'}.isdisjoint(left), lines
    assert {'unique', 'busy', 'live/lane', 'main', 'declared'} <= left, lines
    assert any(line.startswith('kept') and 'unique' in line and 'only here' in line for line in lines), lines
    assert any(line.startswith('kept') and 'busy' in line and 'checked out' in line for line in lines), lines
    assert any(line.startswith('kept') and 'live/lane' in line and 'keep' in line for line in lines), lines


def test_without_the_declared_ref_its_branch_is_kept(repo: Path) -> None:
    """PLANTED CONTROL: ``--contained-in`` is what admits a branch held only by a local ref."""
    sweep_local(repo, keep=(), contained_in=(), apply=True)
    assert 'landed-declared' in _branches(repo)


def test_a_branch_that_moved_after_the_judgment_is_kept(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PLANTED CONTROL: the delete is pinned to the judged sha."""
    real = module._judged

    def moved(root: Path, *args: object, **kwargs: object) -> object:
        rows = real(root, *args, **kwargs)
        _git(root, 'update-ref', 'refs/heads/landed-int', _git(root, 'rev-parse', 'unique'))
        return rows

    monkeypatch.setattr(module, '_judged', moved)
    sweep_local(repo, keep=(), contained_in=(), apply=True)
    assert 'landed-int' in _branches(repo)


def test_the_cli(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(['--local', '--root', str(repo), '--keep', 'live/*', '--contained-in', 'declared', '--apply']) == 0
    assert 'deleted' in capsys.readouterr().out
    assert 'landed-int' not in _branches(repo)
