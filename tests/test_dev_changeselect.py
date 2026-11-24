"""Which tests a change reaches: import, path-literal and conftest edges; data-declared always/full sets."""

from __future__ import annotations

import shutil
from pathlib import Path

import lab_commons.launch as _door
import pytest

from dev_lab.dev import verify
from dev_lab.dev.changeselect import SelectData, changed_paths, select, select_data


def _tree(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')


_FILES = {
    'src/pkg/__init__.py': '',
    'src/pkg/a.py': 'from pkg import b\n',
    'src/pkg/b.py': '',
    'src/pkg/lonely.py': '',
    'tools/thing.py': '',
    'tests/test_a.py': 'from pkg.a import x\n',
    'tests/test_b.py': 'def test():\n    import pkg.b\n',
    'tests/test_tool.py': "PATH = 'tools/thing.py'\n",
    'tests/sub/conftest.py': '',
    'tests/sub/test_c.py': '',
    'tests/arch/test_layers.py': '',
}
_GIT = shutil.which('git') or 'git'
_DATA = SelectData(always=('tests/arch',), full=('pyproject.toml',))


@pytest.fixture
def root(tmp_path: Path) -> Path:
    _tree(tmp_path, _FILES)
    return tmp_path


def test_a_changed_module_selects_every_test_reaching_it_transitively(root: Path) -> None:
    picked = select(root, [Path('src/pkg/b.py')], _DATA)
    assert picked.paths == ('tests/arch', 'tests/test_a.py', 'tests/test_b.py')


def test_a_module_no_test_reaches_selects_only_the_always_set(root: Path) -> None:
    """The planted control: a change must be able to select NOTHING beyond the always-run set."""
    assert select(root, [Path('src/pkg/lonely.py')], _DATA).paths == ('tests/arch',)


def test_a_path_literal_is_an_edge(root: Path) -> None:
    assert 'tests/test_tool.py' in select(root, [Path('tools/thing.py')], _DATA).paths


def test_a_conftest_selects_its_subtree_and_a_changed_test_selects_itself(root: Path) -> None:
    assert 'tests/sub' in select(root, [Path('tests/sub/conftest.py')], _DATA).paths
    assert 'tests/test_b.py' in select(root, [Path('tests/test_b.py')], _DATA).paths


def test_a_declared_full_file_selects_the_whole_suite_and_says_why(root: Path) -> None:
    picked = select(root, [Path('pyproject.toml'), Path('src/pkg/b.py')], _DATA)
    assert picked.full
    assert picked.reasons == ('pyproject.toml is declared full-selection',)


def test_a_deleted_module_selects_its_importers_by_name(root: Path) -> None:
    (root / 'src/pkg/b.py').unlink()
    assert 'tests/test_b.py' in select(root, [Path('src/pkg/b.py')], _DATA).paths


def test_the_sets_are_read_as_data_from_pyproject(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.dev_lab.verify.select]\nalways = ["tests/arch"]\nfull = ["uv.lock"]\n', encoding='utf-8'
    )
    assert select_data(tmp_path) == SelectData(always=('tests/arch',), full=('uv.lock',))
    (tmp_path / 'pyproject.toml').write_text('[project]\nname = "x"\n', encoding='utf-8')
    assert select_data(tmp_path) == SelectData(always=(), full=('pyproject.toml', 'uv.lock'))


def test_changed_paths_reads_the_working_tree_and_names_a_bad_range(root: Path) -> None:
    def git(*args: str) -> None:
        _door.run([_GIT, '-C', str(root), *args], check=True, capture_output=True)

    git('init', '-q')
    git('-c', 'user.email=a@b', '-c', 'user.name=a', 'add', '.')
    git('-c', 'user.email=a@b', '-c', 'user.name=a', 'commit', '-qm', 'x')
    assert changed_paths(root, '') == []
    (root / 'src/pkg/b.py').write_text('X = 1\n', encoding='utf-8')
    (root / 'new.py').write_text('', encoding='utf-8')
    assert changed_paths(root, '') == [Path('new.py'), Path('src/pkg/b.py')]
    with pytest.raises(ValueError, match='no-such-ref'):
        changed_paths(root, 'no-such-ref...HEAD')


def test_verify_changed_runs_the_selection_and_says_when_it_selects_nothing(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(verify, 'changed_paths', lambda _root, _range: [Path('src/pkg/b.py')])
    assert verify._changed_selection(root, '') == ('tests/test_a.py', 'tests/test_b.py')
    monkeypatch.setattr(verify, 'changed_paths', lambda _root, _range: [Path('src/pkg/lonely.py')])
    assert verify._changed_selection(root, '') == verify.EXIT_CODES[verify.Conclusion.PASS]

    def refused(_root: Path, _range: str) -> list[Path]:
        why = 'git diff bad failed'
        raise ValueError(why)

    monkeypatch.setattr(verify, 'changed_paths', refused)
    assert verify._changed_selection(root, 'bad') == 2
