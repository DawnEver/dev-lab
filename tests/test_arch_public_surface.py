"""PUBLIC-SURFACE-DECLARED and DECLARATION-LIES, over this package's own modules.

A module that exports nothing deliberately exports everything accidentally, and the four repos that
import this one cannot tell which of the two they are depending on. So every public module under
``src/`` declares ``__all__`` -- and every name in it must RESOLVE, because an ``__all__`` entry
naming something the module does not define is the dominant defect in its purest form: a declaration
that reads as a contract and is checked by nobody until a consumer's ``from ... import *`` explodes.

PRIVATE MODULES ARE EXEMPT BY SHAPE, NOT BY NAME-LIST. A leading underscore already says "not a
surface", so requiring a surface declaration of one would be a rule arguing with itself. The
exemption is computed from the filename, which means it cannot rot into a list of paths somebody
widened during a red suite.
"""

from __future__ import annotations

import ast
from pathlib import Path

from _arch_corpus import SOURCE_FLOOR, assert_floor, parse, rel, source_modules


def _public(path: Path) -> bool:
    """A module whose own filename is public. ``__init__.py`` is the package's surface, so it counts."""
    return path.name == '__init__.py' or not path.name.startswith('_')


def surface_problems(paths: tuple[Path, ...]) -> tuple[str, ...]:
    """Every public module with no ``__all__``, and every ``__all__`` entry that names nothing.

    Pure over its argument so the planted control below can drive THIS function over a planted tree
    rather than re-implement it and agree with itself.
    """
    out: list[str] = []
    for path in paths:
        if not _public(path):
            continue
        tree = parse(path)
        declared: list[str] | None = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == '__all__' for t in node.targets
            ):
                declared = [e.value for e in getattr(node.value, 'elts', []) if isinstance(e, ast.Constant)]
        if declared is None:
            out.append(f'{path.name} declares no __all__, so its public surface is whatever happens to be defined')
            continue
        defined = _defined_names(tree.body)
        out.extend(
            f'{path.name}: __all__ names {name!r}, which the module does not define or import'
            for name in declared
            if name not in defined
        )
    return tuple(out)


def _defined_names(body: list[ast.stmt]) -> set[str]:
    """Every MODULE-LEVEL name a module binds -- by def, class, assignment or import.

    Module level rather than :func:`ast.walk`, because a local variable inside a function is not a
    name a consumer can import: counting one would let a lying ``__all__`` resolve against it.
    """
    names: set[str] = set()
    for node in body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            names.update((a.asname or a.name).split('.')[0] for a in node.names)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.TypeAlias) and isinstance(node.name, ast.Name):
            # ``type Row = ...`` (PEP 695) binds a module-level name a consumer imports and
            # annotates with. MEASURED 2026-09-17 on ``dev.shards.Row``: omitting this convicted a
            # TRUE ``__all__`` entry. The blind spot ran in that direction only -- it manufactured a
            # lie where there was none, never the reverse -- so nothing already declared was wrong.
            names.add(node.name.id)
        elif isinstance(node, ast.If | ast.Try):
            names |= _defined_names(node.body)
            names |= _defined_names(node.orelse)
            names |= _defined_names(getattr(node, 'finalbody', []))
            for handler in getattr(node, 'handlers', []):
                names |= _defined_names(handler.body)
    return names


def test_every_public_module_declares_a_surface_that_resolves() -> None:
    """THE CHECK, over this repo's own tree -- which no planted fixture can speak for."""
    paths = source_modules()
    assert_floor(len(paths), SOURCE_FLOOR, 'public surface')
    problems = surface_problems(paths)
    assert problems == (), (
        'these modules declare a public surface that lies, or none at all:\n  '
        + '\n  '.join(problems)
        + '\nDeclare __all__, or delete the entry that names nothing. A consumer reads __all__ as the '
        'contract; there is no second place for it to find out it was wrong.'
    )


def test_a_planted_module_is_refused(tmp_path: Path) -> None:
    """THE PLANTED CONTROL. Both halves of the claim, through the REAL checker."""
    missing = tmp_path / 'silent.py'
    missing.write_text('X = 1\n', encoding='utf-8')
    lying = tmp_path / 'lying.py'
    lying.write_text("__all__ = ['gone']\n", encoding='utf-8')
    clean = tmp_path / 'clean.py'
    clean.write_text("__all__ = ['X']\nX = 1\n", encoding='utf-8')
    aliased = tmp_path / 'aliased.py'
    aliased.write_text("__all__ = ['Row']\ntype Row = tuple[str, ...]\n", encoding='utf-8')
    problems = surface_problems((missing, lying, clean, aliased))
    assert any('declares no __all__' in p for p in problems)
    assert any("names 'gone'" in p for p in problems)
    assert not any('clean.py' in p for p in problems)
    # A PEP 695 alias is a real binding, so declaring it is TRUE and must not be convicted.
    assert not any('aliased.py' in p for p in problems)


def test_the_guard_reads_this_repo() -> None:
    """The corpus really is this tree, spelled the way a refusal would spell it."""
    assert 'src/lab_commons/dev/rules.py' in {rel(p) for p in source_modules()}
