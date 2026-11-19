"""PRIVATE-MARKERS on a message is caught before the commit exists, and an unpushed one has a working door.

The door between PRIVATE-MARKERS ("reword before pushing") and GIT-COMMIT-AMEND (no amend): the commit-msg row
refuses the message while the reword is free, and :mod:`dev_lab.dev.reword` re-commits an already-made unpushed
chain onto a fresh branch. Planted controls: a pushed sha, a shared branch and a non-ancestor are each refused.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from dev_lab.dev import privatemarkers, reword

MARKER = (re.compile('secretbox', re.IGNORECASE),)


def _git(root: Path, *argv: str) -> str:
    return reword._git(root, *argv)


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / 'repo'
    root.mkdir()
    _git(root, 'init', '-q', '-b', 'pr/task/feature')
    _git(root, 'config', 'user.email', 'a@example.com')
    _git(root, 'config', 'user.name', 'A')
    for name in ('one', 'two', 'three'):
        (root / name).write_text(name, encoding='utf-8')
        _git(root, 'add', name)
        _git(root, 'commit', '-q', '-m', f'feat: {name} on secretbox' if name == 'two' else f'feat: {name}')
    return root


def test_the_commit_msg_row_refuses_a_marker_before_the_commit_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PLANTED: the same message without the marker passes; a private repo is never judged."""
    monkeypatch.setattr(privatemarkers, 'repo_is_private', lambda *_a, **_k: (False, ''))
    message = tmp_path / 'COMMIT_EDITMSG'
    message.write_text('feat: talk to secretbox\n\n# a comment naming secretbox is not the message\n', 'utf-8')
    assert privatemarkers._judge_message(tmp_path, message, MARKER) == 1
    message.write_text('feat: talk to the store\n\n# secretbox in a comment line\n', 'utf-8')
    assert privatemarkers._judge_message(tmp_path, message, MARKER) == 0
    message.write_text('feat: talk to secretbox\n', 'utf-8')
    monkeypatch.setattr(privatemarkers, 'repo_is_private', lambda *_a, **_k: (True, ''))
    assert privatemarkers._judge_message(tmp_path, message, MARKER) == 0


def test_the_commit_msg_row_is_declared_in_the_base() -> None:
    base = (Path(privatemarkers.__file__).parent / 'githooks' / 'base.toml').read_text(encoding='utf-8')
    assert 'id = "private-markers-message"' in base
    assert 'dev_lab.dev.privatemarkers", "--commit-msg-file"' in base


def test_reword_recommits_the_chain_onto_a_fresh_branch(tmp_path: Path) -> None:
    """Same trees, the one message replaced, later commits kept; the original branch is untouched."""
    root = _repo(tmp_path)
    before = _git(root, 'rev-parse', 'HEAD')
    target = _git(root, 'rev-parse', 'HEAD~1')
    fresh, head = reword.reword(root, target, 'feat: two on the store\n')
    assert fresh == 'pr/task/feature-reworded'
    assert _git(root, 'rev-parse', 'HEAD') == before
    assert _git(root, 'rev-parse', f'{head}^{{tree}}') == _git(root, 'rev-parse', f'{before}^{{tree}}')
    log = _git(root, 'log', '--format=%s', fresh)
    assert 'secretbox' not in log
    assert log.splitlines() == ['feat: three', 'feat: two on the store', 'feat: one']
    assert _git(root, 'rev-parse', f'{fresh}~2') == _git(root, 'rev-parse', 'HEAD~2')


def test_reword_refuses_a_pushed_sha_a_shared_branch_and_a_stranger(tmp_path: Path) -> None:
    """PLANTED: each refusal names its cause; nothing is created."""
    root = _repo(tmp_path)
    target = _git(root, 'rev-parse', 'HEAD~1')
    _git(root, 'update-ref', 'refs/remotes/origin/pr/task/feature', 'HEAD')
    with pytest.raises(reword.Refused, match='already on a remote'):
        reword.reword(root, target, 'x\n')
    _git(root, 'update-ref', '-d', 'refs/remotes/origin/pr/task/feature')
    _git(root, 'branch', '-q', 'integrate/main')
    _git(root, 'switch', '-q', 'integrate/main')
    with pytest.raises(reword.Refused, match='shared'):
        reword.reword(root, target, 'x\n')
    _git(root, 'switch', '-q', 'pr/task/feature')
    _git(root, 'switch', '-q', '--orphan', 'pr/task/other')
    (root / 'z').write_text('z', encoding='utf-8')
    _git(root, 'add', 'z')
    _git(root, 'commit', '-q', '-m', 'feat: z')
    with pytest.raises(reword.Refused, match='not an ancestor'):
        reword.reword(root, target, 'x\n')
    assert 'reworded' not in _git(root, 'branch', '--list')
