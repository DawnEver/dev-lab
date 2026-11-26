"""dev-lab imports nothing from ``lab_commons.units`` or ``lab_commons.em``: lab-commons retires both.

Their replacement is :mod:`lab_commons.quantity` (``registry()``, ``parse``, ``parse_si``). The scan reads every
tracked ``.py`` under ``src/`` and ``tests/`` as an AST, so a module that NAMES a retired module in prose or in a
fixture string is not an import; and a planted module proves the scan says no.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

from _arch_corpus import assert_floor, parse, rel, source_modules, suite_modules

RETIRED: Final = frozenset({'lab_commons.units', 'lab_commons.em'})


def _imports_of_retired(tree: ast.Module) -> list[str]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            parent = node.module == 'lab_commons'
            names = [f'lab_commons.{alias.name}' for alias in node.names] if parent else [node.module]
        else:
            continue
        found += [name for name in names if any(name == r or name.startswith(f'{r}.') for r in RETIRED)]
    return found


def test_no_module_imports_a_retired_lab_commons_module() -> None:
    modules = source_modules() + suite_modules()
    assert_floor(len(modules), 100, 'retired lab_commons import')
    offenders = {rel(path): hits for path in modules if (hits := _imports_of_retired(parse(path)))}
    assert not offenders, f'import lab_commons.quantity (registry(), parse, parse_si) instead: {offenders}'


def test_the_scan_refuses_each_spelling_of_a_retired_import(tmp_path: Path) -> None:
    """PLANTED-CONTROL: every import form is caught, and prose naming the module is not an import."""
    planted = tmp_path / 'planted.py'
    planted.write_text(
        'import lab_commons.units\n'
        'from lab_commons.em import Q_0A_per_m\n'
        'from lab_commons import units, em\n'
        'from lab_commons.quantity import registry\n'
        'TEXT = "from lab_commons.units import Q_"\n',
        encoding='utf-8',
    )
    assert _imports_of_retired(ast.parse(planted.read_text(encoding='utf-8'))) == [
        'lab_commons.units',
        'lab_commons.em',
        'lab_commons.units',
        'lab_commons.em',
    ]
