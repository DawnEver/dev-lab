"""ONE RESOURCE PATH (P1): dev-lab builds no Supply and calls no ``admit``; it asks lab-commons' engine.

A supply is MEASURED by a provider (:mod:`lab_commons.box.providers`, :mod:`lab_commons.hpc.provider`) and judged by
the engine's one rule (:func:`lab_commons.resources.admits`). The forge's claim pass, ``forge try`` and the tick each
built their own -- a host card turned into a ``Supply``, a default task fabricated for an unmeasured account, an
empty one for an unreadable Slurm. The set of dev-lab functions that do so is pinned BY NAME, and it is empty.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

SRC: Final = Path(__file__).resolve().parents[1] / 'src' / 'dev_lab'

#: ``(module, function)`` allowed to build a Supply or call the rule: none -- dev-lab is a consumer.
ALLOWED: Final[frozenset[tuple[str, str]]] = frozenset()

_CALLED: Final = frozenset({'Supply', 'admit'})


def _name(func: ast.expr) -> str:
    return func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ''


def sites(tree: ast.Module, module: str) -> set[tuple[str, str]]:
    """``(module, qualified function)`` of every ``Supply(...)`` or ``admit(...)`` call in *tree*."""
    found: set[tuple[str, str]] = set()

    def walk(node: ast.AST, scope: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                walk(child, (*scope, child.name))
                continue
            if isinstance(child, ast.Call) and _name(child.func) in _CALLED:
                found.add((module, '.'.join(scope) or '<module>'))
            walk(child, scope)

    walk(tree, ())
    return found


def test_dev_lab_builds_no_supply_and_calls_no_admit() -> None:
    paths = sorted(SRC.rglob('*.py'))
    assert len(paths) > 100, 'FLOOR: the scan must read the package'
    found = set()
    for path in paths:
        module = '.'.join(path.relative_to(SRC.parent).with_suffix('').parts)
        found |= sites(ast.parse(path.read_text(encoding='utf-8')), module)
    assert found == ALLOWED


def test_the_scan_finds_an_inline_supply_and_admit_planted_control() -> None:
    planted = ast.parse(
        'def _supply(card):\n    return Supply(card.host, x)\n'
        'class Pass:\n    def go(self):\n        return admit(job, d, s)\n'
    )
    assert sites(planted, 'm') == {('m', '_supply'), ('m', 'Pass.go')}
