"""The family's static import-edge reader: every nesting depth, both spellings, src layout, never silent."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from dev_lab.dev.importedges import bindings, cycle, dotted_uses, import_edges, imports_of, module_name

if TYPE_CHECKING:
    from pathlib import Path


def test_a_src_layout_file_is_named_without_its_src_prefix(tmp_path: Path) -> None:
    for rel in ('src/pkg/__init__.py', 'src/pkg/a.py', 'tests/test_a.py'):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text('', encoding='utf-8')
    assert module_name(tmp_path, tmp_path / 'src/pkg/a.py') == 'pkg.a'
    assert module_name(tmp_path, tmp_path / 'src/pkg/__init__.py') == 'pkg'
    assert module_name(tmp_path, tmp_path / 'tests/test_a.py') == 'tests.test_a'


def test_a_function_body_import_and_a_relative_import_are_both_edges(tmp_path: Path) -> None:
    (tmp_path / 'src/pkg').mkdir(parents=True)
    (tmp_path / 'src/pkg/__init__.py').write_text('from . import a\n', encoding='utf-8')
    (tmp_path / 'src/pkg/a.py').write_text('from .b import f\ndef g():\n    import pkg.c\n', encoding='utf-8')
    assert imports_of(tmp_path, tmp_path / 'src/pkg/a.py') == frozenset({'pkg.b', 'pkg.b.f', 'pkg.c'})
    assert imports_of(tmp_path, tmp_path / 'src/pkg/__init__.py') == frozenset({'pkg', 'pkg.a'})


def test_import_edges_reads_a_source_string_and_refuses_what_it_cannot_parse() -> None:
    source = 'import os as o\nfrom ..up import thing\ndef f():\n    from . import sib\n'
    expected = frozenset({'os', 'pkg.up', 'pkg.up.thing', 'pkg.sub', 'pkg.sub.sib'})
    assert import_edges(source, 'pkg.sub.mod') == expected
    assert import_edges('x = 1\n', 'pkg.mod') == frozenset()  # planted control: no import, no edge
    with pytest.raises(SyntaxError):
        import_edges('def (:\n', 'm')
    with pytest.raises(ImportError):
        import_edges('from ... import x\n', 'pkg.mod')


def test_dotted_uses_follow_an_attribute_chain_from_the_name_an_import_binds() -> None:
    """``import os`` then ``os.environ`` is a use of ``os.environ``; a local name is not an import (planted control)."""
    source = (
        'import os\nimport pkg.alpha.mod as m\nfrom pkg.beta import sub\nfrom . import sib\n'
        'def f(environ):\n    os.environ.get("x")\n    m.thing.attr\n    sub.g()\n    sib.h\n    environ.get\n'
    )
    uses = dotted_uses(source, 'pkg.gamma.mod')
    assert {'os.environ', 'os.environ.get', 'pkg.alpha.mod.thing.attr', 'pkg.beta.sub.g', 'pkg.gamma.sib.h'} <= uses
    assert import_edges(source, 'pkg.gamma.mod') <= uses
    assert not any(use.startswith('environ') for use in uses)


def test_cycle_names_one_cycle_in_order_and_an_acyclic_graph_has_none() -> None:
    assert cycle({'a': {'b'}, 'b': {'c'}, 'c': {'a'}, 'd': set()}) == ['a', 'b', 'c', 'a']
    assert cycle({'a': {'b'}, 'b': {'c'}, 'c': set()}) is None  # planted control: a chain is no cycle
    assert cycle({'a': {'a'}}) == ['a', 'a']


def test_bindings_map_each_local_name_to_what_it_stands_for() -> None:
    source = 'import os\nimport a.b\nimport a.c as c\nfrom .d import e as f\nfrom g import *\n'
    assert bindings(source, 'pkg.mod') == {'os': 'os', 'a': 'a', 'c': 'a.c', 'f': 'pkg.d.e'}
