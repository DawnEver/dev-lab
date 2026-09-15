"""FIX-THE-CAUSE, in the one shape a shared library can check mechanically.

TWO HAZARDS, ONE RULE. A module that binds the same module-level name twice has one definition
shadowing another, and whichever one a reader is looking at is the wrong one half the time -- that
is a patched symptom that no longer advertises its cause. And a ``_legacy``/``_compat``/deprecation
alias is the same defect with a name on it: a second entry point kept alive so callers need not
move, in a package whose callers are four repos that WILL not move once they are not made to.

THE ALIAS HALF IS THE ONE THAT MATTERS HERE. This package is imported by repos that cannot see its
history; the only way a rename reaches them is by breaking, deliberately, at a point somebody
chooses. An alias converts that into a silent fork where two spellings of one idea drift apart.
"""

from __future__ import annotations

import ast
from pathlib import Path

from _arch_corpus import SOURCE_FLOOR, assert_floor, parse, source_modules

#: Spellings that announce a second entry point kept alive for callers that did not move.
_ALIAS_MARKERS = ('_legacy', '_compat', '_deprecated', '_old', 'legacy_', 'compat_', 'deprecated_')


def duplicate_and_alias_problems(paths: tuple[Path, ...]) -> tuple[str, ...]:
    """Every module-level name bound twice, and every alias-shaped name -- pure over its argument."""
    out: list[str] = []
    for path in paths:
        seen: dict[str, int] = {}
        for node in parse(path).body:
            for name in _bound(node):
                if name in seen:
                    out.append(
                        f'{path.name}: {name!r} is defined twice (lines {seen[name]} and {node.lineno}); '
                        f'one of the two is the definition a reader will not be looking at'
                    )
                else:
                    seen[name] = node.lineno
                if any(marker in name.lower() for marker in _ALIAS_MARKERS):
                    out.append(
                        f'{path.name}: {name!r} is a second entry point for callers that did not move; '
                        f'move the callers WITH the code instead'
                    )
    return tuple(out)


def _bound(node: ast.stmt) -> tuple[str, ...]:
    """The module-level names one top-level statement binds by DEFINITION (not by import)."""
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return (node.name,)
    if isinstance(node, ast.Assign):
        return tuple(t.id for t in node.targets if isinstance(t, ast.Name))
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
        return (node.target.id,)
    return ()


def test_no_module_binds_one_name_twice_or_keeps_an_alias() -> None:
    """THE CHECK, over this repo's own source tree."""
    paths = source_modules()
    assert_floor(len(paths), SOURCE_FLOOR, 'one-name-one-definition')
    problems = duplicate_and_alias_problems(paths)
    assert problems == (), 'a name has two definitions, or an alias outlived its callers:\n  ' + '\n  '.join(problems)


def test_a_planted_duplicate_and_a_planted_alias_are_refused(tmp_path: Path) -> None:
    """THE PLANTED CONTROL, through the REAL checker, with a clean file to keep it honest."""
    twice = tmp_path / 'twice.py'
    twice.write_text('def f() -> None: ...\n\n\ndef f() -> None: ...\n', encoding='utf-8')
    alias = tmp_path / 'alias.py'
    alias.write_text('def read_toml_legacy() -> None: ...\n', encoding='utf-8')
    clean = tmp_path / 'fine.py'
    clean.write_text('def f() -> None: ...\n\n\ndef g() -> None: ...\n', encoding='utf-8')
    problems = duplicate_and_alias_problems((twice, alias, clean))
    assert any('defined twice' in p for p in problems)
    assert any('second entry point' in p for p in problems)
    assert not any('fine.py' in p for p in problems)
