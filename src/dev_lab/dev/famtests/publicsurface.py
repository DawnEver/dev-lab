"""PUBLIC-SURFACE-DECLARED: every public module declares ``__all__``, and every name in it resolves.

A module that exports nothing deliberately exports everything accidentally, and a consumer cannot tell which of the
two it depends on. An ``__all__`` entry naming something the module does not define is a declaration that reads as a
contract and is checked by nobody until a consumer's ``from ... import *`` explodes (DECLARATION-LIES).

PRIVATE MODULES ARE EXEMPT BY SHAPE, NOT BY NAME-LIST: a leading underscore already says "not a surface", and the
exemption is computed from the filename, so it cannot rot into a list of paths widened during a red suite.

THE CORPUS is every tracked ``*.py`` under the consumer's declared source roots (``src`` by default), archived code
excluded (:func:`dev_lab.dev.codeplace.is_archived`). The one repo-shaped fact is its floor.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING

from dev_lab.dev import floors
from dev_lab.dev.codeplace import is_archived
from dev_lab.dev.rules import tracked_files

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ['assert_public_surface', 'bound_names', 'public_modules', 'surface_problems']


def bound_names(body: list[ast.stmt]) -> set[str]:
    """Every MODULE-LEVEL name a module binds -- by def, class, assignment, PEP 695 alias or import.

    Module level rather than :func:`ast.walk`, because a local variable inside a function is not a name a consumer
    can import: counting one would let a lying ``__all__`` resolve against it. A module-level ``if``/``try``/``with``
    (an import guard) binds its every branch at module level.
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
            names.add(node.name.id)
        elif isinstance(node, ast.If | ast.Try | ast.With):
            names |= bound_names(_branch_bodies(node))
    return names


def _branch_bodies(node: ast.If | ast.Try | ast.With) -> list[ast.stmt]:
    """Every statement a module-level ``if``/``try``/``with`` runs at module level, in any branch."""
    if isinstance(node, ast.With):
        return list(node.body)
    body = [*node.body, *node.orelse]
    if isinstance(node, ast.Try):
        body += [*node.finalbody, *(stmt for handler in node.handlers for stmt in handler.body)]
    return body


def _declared(tree: ast.Module) -> list[str] | None:
    """The module's ``__all__`` entries, annotated or plain (an EMPTY annotated one is a declaration), else None."""
    declared: list[str] | None = None
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        if any(isinstance(t, ast.Name) and t.id == '__all__' for t in targets):
            value = node.value
            elts = value.elts if isinstance(value, ast.List | ast.Tuple) else []
            declared = [e.value for e in elts if isinstance(e, ast.Constant)]
    return declared


def surface_problems(paths: Iterable[Path]) -> tuple[str, ...]:
    """Every public module of *paths* with no ``__all__``, and every ``__all__`` entry that names nothing.

    Pure over its argument, so a planted control drives THIS function rather than a re-implementation.
    """
    out: list[str] = []
    for path in paths:
        if path.name != '__init__.py' and path.name.startswith('_'):
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        declared = _declared(tree)
        if declared is None:
            out.append(
                f'{path.as_posix()} declares no __all__, so its public surface is whatever happens to be defined'
            )
            continue
        defined = bound_names(tree.body)
        out.extend(
            f'{path.as_posix()}: __all__ names {name!r}, which the module does not define or import'
            for name in declared
            if name not in defined
        )
    return tuple(out)


def public_modules(root: Path, source_roots: Iterable[str] = ('src',)) -> tuple[Path, ...]:
    """Every tracked, present, unarchived ``*.py`` under *root*'s *source_roots*, sorted."""
    prefixes = tuple(f'{one.strip("/")}/' for one in source_roots)
    return tuple(
        root / rel
        for rel in sorted(tracked_files(root))
        if rel.endswith('.py') and rel.startswith(prefixes) and not is_archived(rel) and (root / rel).is_file()
    )


def assert_public_surface(*, root: Path, floor: int, source_roots: Iterable[str] = ('src',)) -> None:
    """Refuse a public module of *root* declaring no surface or a lying one, and a corpus below *floor*."""
    paths = public_modules(root, source_roots)
    floors.assert_floor(len(paths), floor=floor, what='public surface')
    if problems := surface_problems(paths):
        msg = (
            'PUBLIC-SURFACE-DECLARED: these modules declare a public surface that lies, or none at all:\n  '
            + '\n  '.join(problems)
            + '\nDeclare __all__, or delete the entry that names nothing. A consumer reads __all__ as the '
            'contract; there is no second place for it to find out it was wrong.'
        )
        raise AssertionError(msg)
