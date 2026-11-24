"""The family's static import-edge reader: every nesting depth, both spellings, src layout."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dev_lab.dev.importedges import closure, edges, imports_of, module_name

if TYPE_CHECKING:
    from pathlib import Path


def _tree(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')


def test_a_src_layout_file_is_named_without_its_src_prefix(tmp_path: Path) -> None:
    _tree(tmp_path, {'src/pkg/__init__.py': '', 'src/pkg/a.py': '', 'tests/test_a.py': ''})
    assert module_name(tmp_path, tmp_path / 'src/pkg/a.py') == 'pkg.a'
    assert module_name(tmp_path, tmp_path / 'src/pkg/__init__.py') == 'pkg'
    assert module_name(tmp_path, tmp_path / 'tests/test_a.py') == 'tests.test_a'


def test_a_function_body_import_and_a_relative_import_are_both_edges(tmp_path: Path) -> None:
    _tree(
        tmp_path,
        {
            'src/pkg/__init__.py': '',
            'src/pkg/b.py': 'def f():\n    import pkg.c\n',
            'src/pkg/a.py': 'from .b import f\nfrom . import d\n',
        },
    )
    assert imports_of(tmp_path, tmp_path / 'src/pkg/a.py') == frozenset({'pkg.b', 'pkg.b.f', 'pkg', 'pkg.d'})
    assert 'pkg.c' in imports_of(tmp_path, tmp_path / 'src/pkg/b.py')


def test_the_closure_follows_edges_transitively_and_resolves_names_to_modules(tmp_path: Path) -> None:
    _tree(
        tmp_path,
        {
            'src/pkg/__init__.py': '',
            'src/pkg/a.py': 'from pkg.b import f\n',
            'src/pkg/b.py': 'import pkg.c\n',
            'src/pkg/c.py': '',
            'src/pkg/z.py': '',
        },
    )
    graph = edges(tmp_path)
    assert graph['pkg.a'] == frozenset({'pkg.b'})
    assert closure(graph, {'pkg.a'}) == {'pkg.a', 'pkg.b', 'pkg.c'}
    # the planted control: a module nothing imports stays out
    assert 'pkg.z' not in closure(graph, {'pkg.a'})
