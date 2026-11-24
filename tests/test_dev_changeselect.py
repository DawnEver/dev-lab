"""``verify --changed`` selects exactly the test files whose footprint a change reaches."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import lab_commons.launch as _door
import pytest

from dev_lab.dev import verify
from dev_lab.dev.changeselect import changed_paths, select
from dev_lab.dev.footprint import Footprints

if TYPE_CHECKING:
    from pathlib import Path

_GIT = shutil.which('git') or 'git'
_FILES = {
    'pyproject.toml': '[project]\nname = "p"\n',
    'src/pkg/__init__.py': '',
    'src/pkg/a.py': 'from pkg import b\n',
    'src/pkg/b.py': '',
    'src/pkg/lonely.py': '',
    'tests/test_a.py': 'from pkg.a import x\n',
    'tests/test_b.py': 'def test():\n    import pkg.b\n',
    'tests/sub/conftest.py': '',
    'tests/sub/test_c.py': '',
}


def _git(root: Path, *args: str) -> None:
    _door.run([_GIT, '-C', str(root), *args], check=True, capture_output=True)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    for rel, text in _FILES.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding='utf-8')
    _git(tmp_path, 'init', '-q')
    _git(tmp_path, 'add', '.')
    _git(tmp_path, '-c', 'user.email=a@b', '-c', 'user.name=a', 'commit', '-qm', 'x')
    return tmp_path


def test_a_changed_module_selects_every_test_reaching_it_transitively(root: Path) -> None:
    assert select(Footprints.working(root), ['src/pkg/b.py']) == ('tests/test_a.py', 'tests/test_b.py')


def test_a_module_no_test_reaches_selects_nothing(root: Path) -> None:
    """Planted control: a change must be able to select no test at all."""
    assert select(Footprints.working(root), ['src/pkg/lonely.py']) == ()


def test_a_conftest_selects_its_subtree_and_pytest_config_selects_everything(root: Path) -> None:
    footprints = Footprints.working(root)
    assert select(footprints, ['tests/sub/conftest.py']) == ('tests/sub/test_c.py',)
    assert len(select(footprints, ['pyproject.toml'])) == len(footprints.tests())


def test_the_working_tree_is_read_new_tests_and_edits_included(root: Path) -> None:
    (root / 'tests/test_new.py').write_text('import pkg.lonely\n', encoding='utf-8')
    (root / 'src/pkg/lonely.py').write_text('X = 1\n', encoding='utf-8')
    changed = changed_paths(root, '')
    assert changed == ['src/pkg/lonely.py', 'tests/test_new.py']
    assert select(Footprints.working(root), changed) == ('tests/test_new.py',)
    with pytest.raises(ValueError, match='no-such-ref'):
        changed_paths(root, 'no-such-ref...HEAD')


def test_verify_changed_runs_the_selection_and_says_when_it_selects_nothing(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(verify, 'changed_paths', lambda _root, _range: ['src/pkg/b.py'])
    assert verify._changed_selection(root, '') == ('tests/test_a.py', 'tests/test_b.py')
    monkeypatch.setattr(verify, 'changed_paths', lambda _root, _range: ['src/pkg/lonely.py'])
    assert verify._changed_selection(root, '') == verify.EXIT_CODES[verify.Conclusion.PASS]
    monkeypatch.setattr(verify, 'changed_paths', lambda _root, _range: ['pyproject.toml'])
    assert verify._changed_selection(root, '') == ()  # the whole suite is no selection: the producer's rule holds

    def refused(_root: Path, _range: str) -> list[str]:
        why = 'git diff bad failed'
        raise ValueError(why)

    monkeypatch.setattr(verify, 'changed_paths', refused)
    assert verify._changed_selection(root, 'bad') == 2
