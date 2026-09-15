"""TOLERANCE-CARRIES-A-UNIT, checked over every ``approx`` call this suite writes.

WHAT THE SHAPE COSTS. ``pytest.approx(x)`` defaults to ``rel=1e-6`` combined with ``abs=1e-12``, and
the two legs combine with OR: the assertion passes if EITHER is met. So the floor is always there --
the only question is whether the site CHOSE it. On a quantity whose magnitude sits near or below
``abs / rel`` the absolute leg swallows the relative one and the assertion cannot fail; on a
quantity far above it the default floor is slack nobody priced. Either way the number that decides
the test was supplied by the framework, in whatever unit the left-hand side happened to be in.

MEASURED HERE, not imported from the rule's prose. Before this guard existed this repo wrote SEVEN
bare ``approx`` calls (2026-09-15). One of them compared the vacuum permeability, 1.2566e-6 H/m,
against the default ``abs=1e-12`` -- a floor worth 1e-6 of the value being checked, which would have
accepted a constant wrong in its seventh digit. That is the rule's own inversion, live in the tree
that authors the rule, and it is why this rule was declared VIOLATED rather than merely absent until
the seven were given floors.

``abs=`` IS REQUIRED UNCONDITIONALLY, AND ``abs=0.0`` PASSES. On a site whose value is exact -- a
binary-representable ratio, a round trip that must lose nothing -- ``abs=0.0`` is semantically inert
and costs the author nothing but the sentence saying so. Requiring it everywhere means a new site
cannot be written wrong at all, rather than written wrong and then exempted. There is NO allowlist,
for the reason a waiver set always fails: at that point the cheapest repair for a red is to join it.

This is a LINT over the AST, not an oracle on the numerics. It reads the keywords off the `Call`
node, so a comment or a string containing ``abs`` cannot fool it, and it treats a dotted ``approx``
and a bare imported ``approx`` as the same call.
"""

from __future__ import annotations

import ast
from pathlib import Path

from _arch_corpus import assert_floor, parse, rel, suite_modules

#: Below this the suite scan did not reach the tree, so an empty finding proves nothing. MEASURED
#: 2026-09-15 (23 test modules); set under the measurement so a new file does not red the floor.
SUITE_FLOOR = 18


def _is_approx(func: ast.expr) -> bool:
    """``approx(...)`` or ``<anything>.approx(...)`` -- the import style is not the subject."""
    return (isinstance(func, ast.Name) and func.id == 'approx') or (
        isinstance(func, ast.Attribute) and func.attr == 'approx'
    )


def floorless_approx_calls(paths: tuple[Path, ...]) -> tuple[str, ...]:
    """Every ``approx`` call in *paths* with no explicit ``abs=`` -- pure over its argument."""
    out: list[str] = []
    for path in paths:
        for node in ast.walk(parse(path)):
            if not isinstance(node, ast.Call) or not _is_approx(node.func):
                continue
            if 'abs' not in {kw.arg for kw in node.keywords if kw.arg is not None}:
                out.append(f'{_name(path)}:{node.lineno}')
    return tuple(out)


def _name(path: Path) -> str:
    try:
        return rel(path)
    except ValueError:
        return path.name


def test_every_approx_states_an_absolute_floor() -> None:
    """THE CHECK, over the whole suite."""
    modules = suite_modules()
    assert_floor(len(modules), SUITE_FLOOR, 'suite')
    floorless = floorless_approx_calls(modules)
    assert floorless == (), (
        'these approx calls take the default abs=1e-12, a floor in whatever unit the left-hand side '
        'happens to be in rather than one the site chose:\n  ' + '\n  '.join(floorless) + '\n'
        'State a floor justified by the quantity. abs=0.0 is a legitimate answer for an exact value, '
        'and saying so in a comment is the whole cost.'
    )


def test_a_planted_floorless_approx_is_refused(tmp_path: Path) -> None:
    """THE PLANTED CONTROL: three call shapes through the REAL predicate, not a re-implementation."""
    bare = tmp_path / 'test_bare.py'
    bare.write_text('def test_x():\n    assert 1 == pytest.approx(1.0)\n', encoding='utf-8')
    rel_only = tmp_path / 'test_rel_only.py'
    rel_only.write_text('def test_x():\n    assert 1 == approx(1.0, rel=1e-9)\n', encoding='utf-8')
    floored = tmp_path / 'test_floored.py'
    floored.write_text('def test_x():\n    assert 1 == pytest.approx(1.0, abs=0.0)\n', encoding='utf-8')

    found = floorless_approx_calls((bare, rel_only, floored))
    assert any(p.startswith('test_bare.py:') for p in found), 'a bare approx must be refused'
    assert any(p.startswith('test_rel_only.py:') for p in found), 'a rel= with no abs= must be refused'
    assert not any(p.startswith('test_floored.py:') for p in found), 'abs=0.0 is a stated floor'
