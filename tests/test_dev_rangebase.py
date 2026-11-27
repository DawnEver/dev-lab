"""One family answer to "no merge base with the integration branch" (:mod:`dev_lab.dev.rangebase`).

Planted in tmp repos: an EMPTY-root trunk plus an unrelated skeleton passes every range check; a CONTENTFUL
unrelated trunk is refused by name with the door; the normal related case is unchanged.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from dev_lab.dev import envreads, memoryadds, mergeaudit, rangebase

if TYPE_CHECKING:
    from pathlib import Path

_GIT = shutil.which('git') or 'git'
_ENTRY = '.claude/memory/2026/01/01/an-entry.md'
_TEXT = '---\nname: an-entry\ndescription: d\n---\n\nBody.\n'
_TEST = 'def test_a():\n    assert True\n'
_ENV = '[tool.dev_lab.env]\nentry = []\npending = ["src/a.py"]\nstrict = false\n'


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(
        [_GIT, '-C', str(root), '-c', 'core.hooksPath=/dev/null', *args],
        capture_output=True, text=True, encoding='utf-8', check=True,
    )  # fmt: skip
    return done.stdout.strip()


def _commit(root: Path, files: dict[str, str], message: str) -> str:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding='utf-8')
    _git(root, 'add', '-A')
    _git(root, 'commit', '-q', '--allow-empty', '-m', message)
    return _git(root, 'rev-parse', 'HEAD')


def _lanes(tmp_path: Path, trunk: dict[str, str], *, related: bool = False) -> tuple[Path, str, str]:
    """A repo with branch ``trunk`` (holding *trunk*) and a ``skeleton`` lane, on its own root unless *related*."""
    _git(tmp_path, 'init', '-q', '-b', 'trunk')
    _git(tmp_path, 'config', 'user.email', 't@t')
    _git(tmp_path, 'config', 'user.name', 't')
    base = _commit(tmp_path, trunk, 'trunk root')
    if related:
        _git(tmp_path, 'checkout', '-q', '-b', 'skeleton')
    else:
        _git(tmp_path, 'checkout', '-q', '--orphan', 'skeleton')
        _git(tmp_path, 'rm', '-rfq', '--ignore-unmatch', '.')
    head = _commit(tmp_path, {'tests/test_a.py': _TEST, _ENTRY: _TEXT, 'pyproject.toml': _ENV}, 'skeleton')
    return tmp_path, base, head


def _merge(root: Path, base: str) -> str:
    _git(root, 'merge', '-q', '--no-ff', '--allow-unrelated-histories', '-m', 'chore(merge): trunk', base)
    return _git(root, 'rev-parse', 'HEAD')


def test_an_empty_root_trunk_passes_every_range_check(tmp_path: Path) -> None:
    root, base, head = _lanes(tmp_path, {})
    assert rangebase.range_base(root, base, head) == rangebase.EMPTY_TREE
    assert rangebase.log_range(rangebase.EMPTY_TREE, head) == [head]
    assert memoryadds.problems_between(root, base, head) == ()
    assert envreads.range_problems(root, base, head) == []
    assert mergeaudit.audit(root, _merge(root, base), roots=['tests']) == ()


def test_the_empty_base_still_judges_every_entry_as_added(tmp_path: Path) -> None:
    """PLANTED CONTROL: from the empty tree a malformed new entry is still refused, so the check can say no."""
    root, base, _ = _lanes(tmp_path, {})
    head = _commit(root, {'.claude/memory/2026/01/01/bad.md': 'no front matter\n'}, 'bad entry')
    assert memoryadds.problems_between(root, base, head)


def test_a_contentful_unrelated_trunk_is_refused_by_name(tmp_path: Path) -> None:
    root, base, head = _lanes(tmp_path, {'README.md': 'x\n'})
    with pytest.raises(rangebase.NoMergeBaseError, match=r'NO-MERGE-BASE.*--allow-unrelated-histories'):
        rangebase.range_base(root, base, head)
    (found,) = memoryadds.problems_between(root, base, head)
    assert found.startswith('NO-MERGE-BASE')
    assert rangebase.DOOR in found
    (found,) = envreads.range_problems(root, base, head)
    assert found.startswith('NO-MERGE-BASE')


def test_a_contentful_unrelated_merge_is_refused_by_name_by_merge_audit(tmp_path: Path) -> None:
    root, base, _ = _lanes(tmp_path, {'tests/test_b.py': 'def test_b():\n    pass\n'})
    with pytest.raises(mergeaudit.MergeAuditError, match=r'NO-MERGE-BASE.*start the lane from'):
        mergeaudit.audit(root, _merge(root, base), roots=['tests'])


def test_the_related_case_is_unchanged(tmp_path: Path) -> None:
    root, base, head = _lanes(tmp_path, {'README.md': 'x\n'}, related=True)
    assert rangebase.range_base(root, base, head) == base
    assert rangebase.log_range(base, head) == [f'{base}..{head}']
    assert memoryadds.problems_between(root, base, head) == ()
    assert envreads.range_problems(root, base, head) == []


def test_a_git_failure_is_named_not_a_traceback(tmp_path: Path) -> None:
    root, base, _ = _lanes(tmp_path, {})
    with pytest.raises(rangebase.NoMergeBaseError, match='NO-MERGE-BASE: git merge-base'):
        rangebase.merge_bases(root, base, 'no-such-ref')
