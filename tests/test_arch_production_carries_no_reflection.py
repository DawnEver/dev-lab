"""NO-GETATTR: `src/` and `tests/` carry zero ``getattr``/``hasattr`` calls and zero ``__getattr__`` hooks.

User directive 2026-09-26, family-wide: reflection is banned outright. A declared field is read by
attribute access, a name-keyed lookup through ``vars(obj).get(name)`` or an explicit mapping, an
optional capability through a ``runtime_checkable`` Protocol, and a lazy re-export through an explicit
import. Zero is not a ceiling to walk down, so the pin names offending sites rather than a count.
"""

from __future__ import annotations

import ast

from _arch_corpus import SOURCE_FLOOR, TEST_FLOOR, assert_floor, rel, source_modules, suite_modules

_BANNED_CALLS = frozenset({'getattr', 'hasattr'})


def _reflection_sites(source: str, filename: str) -> list[int]:
    """Line numbers of every ``getattr(...)``/``hasattr(...)`` call and ``__getattr__`` definition."""
    tree = ast.parse(source, filename=filename)
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _BANNED_CALLS)
        or (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == '__getattr__')
    )


def test_a_planted_getattr_and_hook_are_both_found() -> None:
    planted = 'def __getattr__(name):\n    return getattr(object(), name)\n'
    assert _reflection_sites(planted, '<planted>') == [1, 2]


def test_production_carries_no_reflection_at_all() -> None:
    files = source_modules()
    assert_floor(len(files), SOURCE_FLOOR, 'reflection')
    offenders = [
        f'{rel(path)}:{line}'
        for path in files
        for line in _reflection_sites(path.read_text(encoding='utf-8'), str(path))
    ]
    assert not offenders, f'getattr/__getattr__ is banned in src/ (directive 2026-09-26): {offenders}'


def test_the_suite_carries_no_reflection_at_all() -> None:
    files = suite_modules()
    assert_floor(len(files), TEST_FLOOR, 'reflection')
    offenders = [
        f'{rel(path)}:{line}'
        for path in files
        for line in _reflection_sites(path.read_text(encoding='utf-8'), str(path))
    ]
    assert not offenders, f'getattr/hasattr/__getattr__ is banned in tests/ (directive 2026-09-26): {offenders}'
