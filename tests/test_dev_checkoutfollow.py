"""CHECKOUT-FOLLOWS-INTEGRATION (user ruling 2026-11-12): a clean primary checkout left behind moves itself.

A main checkout sat detached on an old commit whose manifest the current kit refuses, so neither its venv nor its
hooks could follow. Keeping it current is the toolchain's own work, never a person's prompt: a CLEAN primary
checkout that is detached on, or sitting at, an ancestor of ``origin/<integration>`` fast-forwards onto it.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from dev_lab.dev import checkoutfollow

if TYPE_CHECKING:
    from pathlib import Path

_GIT = shutil.which('git') or 'git'
_DECLARED = '[tool.dev_lab.integrator]\nintegration = "integrate/main"\n'


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        [_GIT, '-C', str(root), '-c', 'user.name=t', '-c', 'user.email=t@t', *args],
        check=True, capture_output=True, text=True, encoding='utf-8',
    ).stdout.strip()  # fmt: skip


def _commit(root: Path, text: str) -> str:
    (root / 'pyproject.toml').write_text(text, encoding='utf-8')
    _git(root, 'add', 'pyproject.toml')
    _git(root, 'commit', '-q', '-m', 'c')
    return _git(root, 'rev-parse', 'HEAD')


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, str, str]:
    """A primary checkout detached on *old*, whose ``origin/integrate/main`` is the newer *tip*."""
    root = tmp_path / 'repo'
    root.mkdir()
    _git(root, 'init', '-q', '-b', 'scratch-start')
    old = _commit(root, '[tool.retired]\nx = 1\n')
    tip = _commit(root, _DECLARED)
    _git(root, 'update-ref', 'refs/remotes/origin/integrate/main', tip)
    _git(root, 'symbolic-ref', 'refs/remotes/origin/HEAD', 'refs/remotes/origin/integrate/main')
    _git(root, 'checkout', '-q', '--detach', old)
    _git(root, 'branch', '-q', '-D', 'scratch-start')
    return root, old, tip


def _no_fetch(_root: Path, _branch: str) -> str | None:
    return None


def test_a_clean_detached_checkout_moves_onto_integration_reading_the_declaration_upstream(repo) -> None:
    """The old tree declares no integrator: the name is read from origin's, never defaulted."""
    root, _old, tip = repo
    assert checkoutfollow.behind(root)
    said = checkoutfollow.advance(root, fetch=_no_fetch)
    assert 'integrate/main' in said
    assert _git(root, 'symbolic-ref', '--short', 'HEAD') == 'integrate/main'
    assert _git(root, 'rev-parse', 'HEAD') == tip
    assert not checkoutfollow.behind(root)
    assert checkoutfollow.advance(root, fetch=_no_fetch) == '', 'PLANTED CONTROL: a current checkout is left alone'


def test_a_checkout_on_integration_behind_its_origin_fast_forwards(repo) -> None:
    root, old, tip = repo
    _git(root, 'switch', '-q', '-c', 'integrate/main')
    assert _git(root, 'rev-parse', 'HEAD') == old
    assert checkoutfollow.behind(root)
    checkoutfollow.advance(root, fetch=_no_fetch)
    assert _git(root, 'rev-parse', 'HEAD') == tip


def test_a_dirty_checkout_is_never_moved_and_says_why(repo) -> None:
    root, old, _tip = repo
    (root / 'pyproject.toml').write_text('edited\n', encoding='utf-8')
    said = checkoutfollow.advance(root, fetch=_no_fetch)
    assert 'uncommitted' in said
    assert _git(root, 'rev-parse', 'HEAD') == old


def test_a_detached_head_neither_an_ancestor_nor_on_origin_is_left_where_it_is(repo) -> None:
    root, _old, _tip = repo
    _git(root, 'checkout', '-q', '--orphan', 'elsewhere')
    _commit(root, _DECLARED + '# elsewhere\n')
    _git(root, 'checkout', '-q', '--detach')
    here = _git(root, 'rev-parse', 'HEAD')
    assert 'not an ancestor' in checkoutfollow.advance(root, fetch=_no_fetch)
    assert _git(root, 'rev-parse', 'HEAD') == here
    _git(root, 'update-ref', 'refs/remotes/origin/feat/elsewhere', here)
    assert 'integrate/main' in checkoutfollow.advance(root, fetch=_no_fetch), 'held upstream: leaving it is lossless'
    assert _git(root, 'symbolic-ref', '--short', 'HEAD') == 'integrate/main'


def test_a_linked_worktree_or_another_branch_is_not_the_follows_business(repo, tmp_path: Path) -> None:
    root, old, _tip = repo
    lane = tmp_path / 'lane'
    _git(root, 'worktree', 'add', '-q', '--detach', str(lane), old)
    assert not checkoutfollow.behind(lane)
    assert checkoutfollow.advance(lane, fetch=_no_fetch) == ''
    _git(root, 'switch', '-q', '-c', 'feat/x')
    assert not checkoutfollow.behind(root)
    assert checkoutfollow.advance(root, fetch=_no_fetch) == ''
    assert _git(root, 'rev-parse', 'HEAD') == old
