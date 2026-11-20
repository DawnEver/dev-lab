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

from _arch_corpus import SOURCE_FLOOR, assert_floor, bound_names, parse, rel, source_modules


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
            # ANNOTATED AND PLAIN ALIKE. MEASURED 2026-09-17 on a package declaring an EMPTY surface:
            # `__all__: list[str] = []` needs its annotation, because an empty list has no element type
            # to infer -- and reading only `ast.Assign` convicted that TRUE declaration of being absent.
            # Same blind spot and same direction as the PEP 695 one below: it manufactures a lie where
            # there is none, never the reverse, so nothing that already passed was wrong.
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            if any(isinstance(t, ast.Name) and t.id == '__all__' for t in targets):
                elts = node.value.elts if isinstance(node.value, ast.List | ast.Tuple) else []
                declared = [e.value for e in elts if isinstance(e, ast.Constant)]
        if declared is None:
            out.append(f'{path.name} declares no __all__, so its public surface is whatever happens to be defined')
            continue
        defined = bound_names(tree.body)
        out.extend(
            f'{path.name}: __all__ names {name!r}, which the module does not define or import'
            for name in declared
            if name not in defined
        )
    return tuple(out)


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
    annotated = tmp_path / 'annotated.py'
    annotated.write_text('__all__: list[str] = []' + chr(10), encoding='utf-8')
    guarded = tmp_path / 'guarded.py'
    guarded.write_text(
        "__all__ = ['X']" + chr(10) + 'with open(__file__):' + chr(10) + '    from os import sep as X' + chr(10),
        encoding='utf-8',
    )
    problems = surface_problems((missing, lying, clean, aliased, annotated, guarded))
    assert any('declares no __all__' in p for p in problems)
    assert any("names 'gone'" in p for p in problems)
    assert not any('clean.py' in p for p in problems)
    # A PEP 695 alias is a real binding, so declaring it is TRUE and must not be convicted.
    assert not any('aliased.py' in p for p in problems)
    # An ANNOTATED `__all__` is a declaration, and an EMPTY one is the strongest kind: it says the
    # module publishes nothing, which is exactly the claim the unseeing reading erased.
    assert not any('annotated.py' in p for p in problems)
    # A name imported inside a module-level `with` (an import guard) is bound at module level.
    assert not any('guarded.py' in p for p in problems)


def test_the_guard_reads_this_repo() -> None:
    """The corpus really is this tree, spelled the way a refusal would spell it."""
    assert 'src/dev_lab/dev/rules.py' in {rel(p) for p in source_modules()}
