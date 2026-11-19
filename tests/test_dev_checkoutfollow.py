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


def _clone_behind(tmp_path: Path) -> tuple[Path, Path, bytes]:
    """A clone on integrate/main one commit behind its bare upstream, whose ``deny-rules.json`` changed upstream."""
    bare, seed, clone = tmp_path / 'up.git', tmp_path / 'seed', tmp_path / 'clone'
    subprocess.run([_GIT, 'init', '-q', '--bare', '-b', 'integrate/main', str(bare)], check=True)
    subprocess.run([_GIT, 'clone', '-q', str(bare), str(seed)], check=True, capture_output=True)
    rules = seed / '.claude' / 'hooks' / 'deny-rules.json'
    rules.parent.mkdir(parents=True)
    rules.write_bytes(b'{"rules": []}\n')
    (seed / 'pyproject.toml').write_text(_DECLARED, encoding='utf-8')
    _git(seed, 'add', '.')
    _git(seed, 'commit', '-q', '-m', 'old rules')
    _git(seed, 'push', '-q', 'origin', 'HEAD:integrate/main')
    subprocess.run([_GIT, 'clone', '-q', '-c', 'core.autocrlf=false', str(bare), str(clone)], check=True,
                   capture_output=True)  # fmt: skip
    rules.write_bytes(b'{"rules": [{"id": "NEW-ROW"}]}\n')
    _git(seed, 'commit', '-q', '-am', 'new rules')
    _git(seed, 'push', '-q', 'origin', 'HEAD:integrate/main')
    return bare, clone, rules.read_bytes()


def _idle(_root: Path) -> str:
    return ''


def test_a_clean_checkout_behind_its_upstream_fetches_and_serves_upstreams_rules_byte_for_byte(tmp_path) -> None:
    """O14: per-call hook inputs are read from disk, so a checkout left behind serves stale rules to every session."""
    _bare, clone, upstream_rules = _clone_behind(tmp_path)
    rules = clone / '.claude' / 'hooks' / 'deny-rules.json'
    assert rules.read_bytes() != upstream_rules, 'PLANTED CONTROL: the clone starts on the old rules'
    assert not checkoutfollow.behind(clone), 'not fetched yet: behind is judged offline'
    _git(clone, 'fetch', '-q')
    said = checkoutfollow.advance(clone, busy=_idle)
    assert 'integrate/main' in said
    assert rules.read_bytes() == upstream_rules


def test_a_live_run_in_the_checkout_leaves_head_and_names_the_holder(tmp_path) -> None:
    _bare, clone, _rules = _clone_behind(tmp_path)
    _git(clone, 'fetch', '-q')
    head = _git(clone, 'rev-parse', 'HEAD')
    said = checkoutfollow.advance(clone, fetch=_no_fetch, busy=lambda _root: 'live run: pid 4242 (app)')
    assert 'pid 4242 (app)' in said
    assert 'live run' in said
    assert _git(clone, 'rev-parse', 'HEAD') == head
    assert checkoutfollow.obstacle(clone, busy=lambda _root: 'live run: pid 4242 (app)')


def test_a_dirty_behind_checkout_is_not_touched_and_its_obstacle_says_so(tmp_path) -> None:
    _bare, clone, _rules = _clone_behind(tmp_path)
    _git(clone, 'fetch', '-q')
    head = _git(clone, 'rev-parse', 'HEAD')
    (clone / 'pyproject.toml').write_text('edited\n', encoding='utf-8')
    assert 'uncommitted' in checkoutfollow.obstacle(clone, busy=_idle)
    assert 'uncommitted' in checkoutfollow.advance(clone, fetch=_no_fetch, busy=_idle)
    assert _git(clone, 'rev-parse', 'HEAD') == head
    assert (clone / 'pyproject.toml').read_text(encoding='utf-8') == 'edited\n'


_JOURNAL = '.claude/tasks/some-task/JOURNAL.md'


def _clone_behind_with_journal(tmp_path: Path, *, upstream_appends: bool = False) -> tuple[Path, str]:
    """A fetched clone one commit behind, whose task journal is tracked; upstream optionally appends to it too."""
    _bare, clone, _rules = _clone_behind(tmp_path)
    seed = tmp_path / 'seed'
    journal = seed / _JOURNAL
    journal.parent.mkdir(parents=True)
    journal.write_text('- opened\n', encoding='utf-8')
    _git(seed, 'add', _JOURNAL)
    _git(seed, 'commit', '-q', '-m', 'journal')
    _git(seed, 'push', '-q', 'origin', 'HEAD:integrate/main')
    _git(clone, 'pull', '-q', '--ff-only')
    (seed / 'pyproject.toml').write_text(_DECLARED + '# newer\n', encoding='utf-8')
    if upstream_appends:
        journal.write_text('- opened\n- upstream line\n', encoding='utf-8')
    _git(seed, 'commit', '-q', '-am', 'newer')
    _git(seed, 'push', '-q', 'origin', 'HEAD:integrate/main')
    _git(clone, 'fetch', '-q')
    return clone, _git(clone, 'rev-parse', 'origin/integrate/main')


def test_a_journal_append_alone_fast_forwards_and_the_append_survives(tmp_path) -> None:
    """O19 ruling A: the rem task hooks append to the main checkout's journal; that dirt never holds the follow."""
    clone, tip = _clone_behind_with_journal(tmp_path)
    journal = clone / _JOURNAL
    journal.write_text('- opened\n- local line\n', encoding='utf-8')
    (clone / '.claude' / 'tasks' / 'untracked-task').mkdir()
    (clone / '.claude' / 'tasks' / 'untracked-task' / 'TASK.md').write_text('t\n', encoding='utf-8')
    assert checkoutfollow.obstacle(clone, busy=_idle) == ''
    assert 'integrate/main' in checkoutfollow.advance(clone, fetch=_no_fetch, busy=_idle)
    assert _git(clone, 'rev-parse', 'HEAD') == tip
    assert journal.read_text(encoding='utf-8') == '- opened\n- local line\n'


def test_a_journal_append_upstream_also_changed_is_refused_by_name(tmp_path) -> None:
    clone, _tip = _clone_behind_with_journal(tmp_path, upstream_appends=True)
    head = _git(clone, 'rev-parse', 'HEAD')
    (clone / _JOURNAL).write_text('- opened\n- local line\n', encoding='utf-8')
    said = checkoutfollow.advance(clone, fetch=_no_fetch, busy=_idle)
    assert _JOURNAL in said
    assert 'upstream' in said
    assert _git(clone, 'rev-parse', 'HEAD') == head


def test_a_journal_edit_that_is_not_an_append_is_refused(tmp_path) -> None:
    clone, _tip = _clone_behind_with_journal(tmp_path)
    head = _git(clone, 'rev-parse', 'HEAD')
    (clone / _JOURNAL).write_text('- rewritten\n', encoding='utf-8')
    said = checkoutfollow.advance(clone, fetch=_no_fetch, busy=_idle)
    assert _JOURNAL in said
    assert 'not an append' in said
    assert _git(clone, 'rev-parse', 'HEAD') == head


def test_a_journal_append_beside_another_tracked_edit_is_refused(tmp_path) -> None:
    clone, _tip = _clone_behind_with_journal(tmp_path)
    head = _git(clone, 'rev-parse', 'HEAD')
    (clone / _JOURNAL).write_text('- opened\n- local line\n', encoding='utf-8')
    rules = clone / '.claude' / 'hooks' / 'deny-rules.json'
    rules.write_bytes(rules.read_bytes() + b'\n')
    said = checkoutfollow.advance(clone, fetch=_no_fetch, busy=_idle)
    assert 'uncommitted' in said
    assert 'deny-rules.json' in said
    assert _git(clone, 'rev-parse', 'HEAD') == head
