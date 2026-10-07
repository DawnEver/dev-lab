"""A MERGE MAY NOT LOSE OR REWRITE A TEST IN SILENCE -- the three-way audit at test granularity.

The tests ARE the feature inventory, so a merge regresses a feature in exactly one way no gate can
see: the resolution deletes or rewrites the test that would have caught it. The audit computes, per
test, what a clean three-way merge would hold, and every test where the merge holds something else
must be NAMED in the merge commit with a one-line reason.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from lab_commons.dev import mergeaudit
from lab_commons.dev.mergeaudit import ALTERED, CONFLICTED, LOST, Deviation

if TYPE_CHECKING:
    from pathlib import Path

_GIT = shutil.which('git') or 'git'

A = 'def test_a():\n    assert 1 == 1\n'
A2 = 'def test_a():\n    assert 1 == 2\n'
A3 = 'def test_a():\n    assert 1 == 3\n'
B = 'def test_b():\n    assert True\n'


def _fp(*sources: str) -> dict[str, str]:
    return mergeaudit.read_tests({f'tests/test_{i}.py': s.encode() for i, s in enumerate(sources)})


def _classify(base: str, ours: str, theirs: str, merged: str) -> set[Deviation]:
    trees = [_fp(*(s for s in (src,) if s)) for src in (base, ours, theirs, merged)]
    return set(mergeaudit.classify(*trees))


def test_a_clean_merge_has_no_deviation() -> None:
    assert _classify(A, A2, A, A2) == set()
    assert _classify(A, A, A2, A2) == set()
    assert _classify(A, A2, A2, A2) == set()
    assert _classify('', A, '', A) == set()


def test_a_test_one_side_added_and_the_merge_dropped_is_lost() -> None:
    assert _classify('', '', A, '') == {Deviation(LOST, 'test_a')}


def test_a_test_one_side_changed_and_the_merge_reverted_is_altered() -> None:
    assert _classify(A, A, A2, A) == {Deviation(ALTERED, 'test_a')}


def test_a_deletion_by_one_side_is_that_sides_decision_not_a_deviation() -> None:
    assert _classify(A, '', A, '') == set()
    assert _classify(A, '', A, A) == {Deviation(ALTERED, 'test_a')}


def test_both_sides_changing_one_test_differently_is_conflicted_whatever_the_merge_holds() -> None:
    assert _classify(A, A2, A3, A2) == {Deviation(CONFLICTED, 'test_a')}
    assert _classify(A, A2, '', '') == {Deviation(CONFLICTED, 'test_a')}


def test_a_test_moved_to_another_file_keeps_its_identity() -> None:
    base = {'tests/test_old.py': A.encode()}
    moved = {'tests/test_new.py': A.encode()}
    trees = [mergeaudit.read_tests(t) for t in (base, moved, base, moved)]
    assert mergeaudit.classify(*trees) == ()


def test_a_docstring_or_comment_is_prose_not_specification() -> None:
    documented = 'def test_a():\n    """Why."""\n    # note\n    assert 1 == 1\n'
    assert _fp(A) == _fp(documented)


def test_a_duplicated_name_is_keyed_by_its_path() -> None:
    tree = mergeaudit.read_tests({'tests/x/test_m.py': A.encode(), 'tests/y/test_m.py': A2.encode()})
    assert set(tree) == {'tests/x/test_m.py::test_a', 'tests/y/test_m.py::test_a'}


def test_a_method_on_a_test_class_is_a_test() -> None:
    tree = mergeaudit.read_tests({'tests/test_c.py': b'class TestC:\n    def test_m(self):\n        assert 1\n'})
    assert set(tree) == {'TestC::test_m'}


def test_an_unparseable_file_refuses_rather_than_reading_as_empty() -> None:
    with pytest.raises(mergeaudit.MergeAuditError, match=r'tests/test_bad[.]py'):
        mergeaudit.read_tests({'tests/test_bad.py': b'def test_a(:\n'})


def test_the_ledger_must_name_every_deviation_and_nothing_else() -> None:
    found = (Deviation(LOST, 'test_a'), Deviation(ALTERED, 'test_b'))
    message = 'merge: x\n\nMerge-Audit: LOST test_a -- moved into test_c\nMerge-Audit: ALTERED test_b -- newer pin\n'
    assert mergeaudit.unnamed(found, message) == ()
    assert mergeaudit.unnamed(found, 'merge: x\n\nMerge-Audit: LOST test_a -- moved\n') == (
        'ALTERED test_b: not named -- add `Merge-Audit: ALTERED test_b -- <reason>`',
    )


def test_a_ledger_line_without_a_reason_or_naming_no_deviation_is_refused() -> None:
    found = (Deviation(LOST, 'test_a'),)
    assert mergeaudit.unnamed(found, 'Merge-Audit: LOST test_a\n') == (
        'LOST test_a: not named -- add `Merge-Audit: LOST test_a -- <reason>`',
    )
    assert mergeaudit.unnamed((), 'Merge-Audit: LOST test_z -- gone\n') == (
        'LOST test_z: named, but the merge holds no such deviation -- delete the line',
    )


def _git(root: Path, *args: str) -> str:
    done = subprocess.run([_GIT, '-C', str(root), *args], capture_output=True, text=True, encoding='utf-8', check=True)
    return done.stdout.strip()


def _commit(root: Path, files: dict[str, str | None], message: str) -> None:
    for name, text in files.items():
        path = root / name
        if text is None:
            path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    _git(root, 'add', '-A')
    _git(root, 'commit', '-q', '-m', message)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, 'init', '-q', '-b', 'main')
    _git(tmp_path, 'config', 'user.email', 't@t')
    _git(tmp_path, 'config', 'user.name', 't')
    _commit(tmp_path, {'tests/test_a.py': A, 'src/m.py': 'X = 1\n'}, 'base')
    return tmp_path


def test_the_planted_control_a_lane_test_the_merge_dropped_is_caught_end_to_end(repo: Path) -> None:
    _git(repo, 'checkout', '-q', '-b', 'lane')
    _commit(repo, {'tests/test_b.py': B}, 'lane adds b')
    _git(repo, 'checkout', '-q', 'main')
    _commit(repo, {'src/m.py': 'X = 2\n'}, 'main moves on')
    _git(repo, 'merge', '-q', '--no-commit', 'lane')
    (repo / 'tests/test_b.py').unlink()
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-q', '-m', 'merge lane')
    head = _git(repo, 'rev-parse', 'HEAD')
    assert mergeaudit.audit(repo, head, roots=('tests',)) == (Deviation(LOST, 'test_b'),)
    assert mergeaudit.refusals(repo, (head,), roots=('tests',))


def test_a_clean_merge_audits_clean_end_to_end(repo: Path) -> None:
    _git(repo, 'checkout', '-q', '-b', 'lane')
    _commit(repo, {'tests/test_b.py': B}, 'lane adds b')
    _git(repo, 'checkout', '-q', 'main')
    _commit(repo, {'tests/test_a.py': A2}, 'main edits a')
    _git(repo, 'merge', '-q', '-m', 'merge lane', 'lane')
    head = _git(repo, 'rev-parse', 'HEAD')
    assert mergeaudit.audit(repo, head, roots=('tests',)) == ()
    assert mergeaudit.refusals(repo, (head,), roots=('tests',)) == ()


def test_an_empty_test_tree_refuses_rather_than_auditing_clean(repo: Path) -> None:
    head = _git(repo, 'rev-parse', 'HEAD')
    _git(repo, 'checkout', '-q', '-b', 'lane')
    _commit(repo, {'src/m.py': 'X = 3\n'}, 'lane')
    _git(repo, 'checkout', '-q', 'main')
    _commit(repo, {'src/n.py': 'Y = 1\n'}, 'main')
    _git(repo, 'merge', '-q', '-m', 'merge', 'lane')
    head = _git(repo, 'rev-parse', 'HEAD')
    with pytest.raises(mergeaudit.MergeAuditError, match='no test'):
        mergeaudit.audit(repo, head, roots=('nothing_here',))
