"""NO-REFLECTION: one origin-aware scanner for attribute and namespace reflection.

User ruling 2026-10-04, family-wide, superseding the 2026-09-26 getattr-only directive: reflection
is banned outright. A declared field is read by attribute access, a capability by ``isinstance``
against a Protocol, a dataclass surface by ``dataclasses.fields``/``replace``, a name-keyed choice
by an explicit dict, and an absent attribute by ``pytest.raises(AttributeError)``. Moving the call
behind ``vars()`` or ``__dict__`` is the same probe renamed, and is not a fix.

THE CORPUS IS EVERY TRACKED ``*.py`` -- source, tests, scripts, examples -- except a path with an
``attic`` or ``archived`` segment, which is read-only history. Each consumer had its own copy of this
scan over its own subset of trees, and each copy banned a different subset of the four names.

THE ONE REPO-SHAPED FACT IS THE ALLOW-SET, keyed by repo-relative POSIX path with the REASON as the
value, and it has no default. It is TWO-SIDED: a path that no longer reflects is named too, so a
cleaned file must leave the set in the same edit. An irreducible boundary (a native extension's
optional symbol) belongs there; convenience does not.
"""

from __future__ import annotations

import ast
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from lab_commons.dev import floors
from lab_commons.dev.rules import tracked_files

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ['BANNED_CALLS', 'EXCLUDED_SEGMENTS', 'assert_no_reflection', 'reflection_sites', 'scanned_files']

BANNED_CALLS = frozenset({'getattr', 'hasattr', 'setattr', 'delattr', 'vars', 'dir'})
EXCLUDED_SEGMENTS = frozenset({'attic', 'archived'})
_HOOKS = frozenset({'__getattr__', '__getattribute__', '__setattr__', '__delattr__'})
_ORIGINS = frozenset(
    {
        *(f'builtins.{name}' for name in BANNED_CALLS),
        'operator.attrgetter',
        'inspect.getmembers',
        'inspect.getmembers_static',
        *(f'builtins.object.{name}' for name in _HOOKS),
    }
)


def _local_bindings(body: list[ast.stmt]) -> set[str]:
    """Names Python treats as local, without descending into nested scopes."""
    names: set[str] = set()
    pending: list[ast.AST] = list(body)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update(alias.asname or alias.name.split('.')[0] for alias in node.names)
        elif not isinstance(node, ast.Lambda):
            pending.extend(ast.iter_child_nodes(node))
    return names


class _ReflectionScan:
    """Lexical callable origins and the reflection sites they identify."""

    def __init__(self) -> None:
        self.scopes: list[tuple[str, dict[str, str | None]]] = [('module', {})]
        self.found: set[int] = set()

    def origin(self, node: ast.AST | None) -> str | None:
        """An imported/builtin origin, or None for a user binding."""
        if isinstance(node, ast.Name):
            for _kind, bindings in reversed(self.scopes):
                if node.id in bindings:
                    return bindings[node.id]
            return f'builtins.{node.id}' if node.id in BANNED_CALLS | {'object'} else None
        if isinstance(node, ast.Attribute) and (owner := self.origin(node.value)) is not None:
            return f'{owner}.{node.attr}'
        return None

    def bind(self, target: ast.AST, value: str | None) -> None:
        """Bind a local target and record assigned attribute hooks."""
        if isinstance(target, ast.Name):
            self.scopes[-1][1][target.id] = value
            if target.id in _HOOKS:
                self.found.add(target.lineno)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                self.bind(item, None)

    def function_bindings(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> dict[str, str | None]:
        """All function locals shadow enclosing bindings, even before their assignment."""
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                self.visit(default)
        body = [] if isinstance(node, ast.Lambda) else node.body
        bindings: dict[str, str | None] = dict.fromkeys(_local_bindings(body))
        arguments = (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
        bindings.update(dict.fromkeys(arg.arg for arg in arguments))
        for arg in (node.args.vararg, node.args.kwarg):
            if arg is not None:
                bindings[arg.arg] = None
        return bindings

    def scope(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda) -> None:
        """Visit one lexical scope; methods never close over a class namespace."""
        if not isinstance(node, ast.Lambda):
            if node.name in _HOOKS:
                self.found.add(node.lineno)
            self.scopes[-1][1][node.name] = None
            for decorator in node.decorator_list:
                self.visit(decorator)
        is_class = isinstance(node, ast.ClassDef)
        if is_class:
            for base in node.bases:
                self.visit(base)
            bindings: dict[str, str | None] = {}
        else:
            bindings = self.function_bindings(node)
        enclosing = self.scopes[:]
        if not is_class:
            self.scopes[:] = [(kind, values) for kind, values in self.scopes if kind != 'class']
        self.scopes.append(('class' if is_class else 'function', bindings))
        for child in [node.body] if isinstance(node, ast.Lambda) else node.body:
            self.visit(child)
        self.scopes[:] = enclosing

    def import_names(self, node: ast.Import | ast.ImportFrom) -> None:
        """Record import aliases without treating another owner's spelling as a builtin."""
        for alias in node.names:
            if isinstance(node, ast.Import):
                name = alias.asname or alias.name.split('.')[0]
                value = alias.name if alias.asname else alias.name.split('.')[0]
            else:
                name = alias.asname or alias.name
                value = f'{node.module}.{alias.name}' if not node.level else None
            self.scopes[-1][1][name] = value

    def assign(self, node: ast.Assign | ast.AnnAssign) -> None:
        """Propagate simple callable aliases, replacing prior origins on reassignment."""
        if node.value is not None:
            self.visit(node.value)
        value = self.origin(node.value)
        for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
            self.visit(target)
            self.bind(target, value)

    def visit(self, node: ast.AST) -> None:
        """Inspect a node while retaining lexical bindings for its descendants."""
        if isinstance(node, ast.Call) and self.origin(node.func) in _ORIGINS:
            self.found.add(node.lineno)
        if isinstance(node, ast.Attribute) and node.attr == '__dict__':
            self.found.add(node.lineno)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            self.scope(node)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            self.import_names(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            self.assign(node)
        else:
            for child in ast.iter_child_nodes(node):
                self.visit(child)


def reflection_sites(source: str, filename: str) -> list[int]:
    """Unique lines of reflection calls, namespace accesses and hooks in *source*.

    Imports and simple assignments preserve callable origins; lexical bindings shadow builtins.
    Another owner's same-named API (e.g. monkeypatch.setattr or archive.getmembers) is not reflection.
    This recognises declared AST spellings, not arbitrary runtime-generated Python.
    """
    scan = _ReflectionScan()
    scan.visit(ast.parse(source, filename=filename))
    return sorted(scan.found)


def scanned_files(root: Path) -> tuple[str, ...]:
    """Every tracked ``*.py`` under *root* outside an excluded segment, sorted."""
    return tuple(
        sorted(
            rel
            for rel in tracked_files(root)
            if rel.endswith('.py') and not EXCLUDED_SEGMENTS.intersection(PurePosixPath(rel).parts)
        )
    )


def assert_no_reflection(*, root: Path, allowed: Mapping[str, str], floor: int) -> None:
    """Refuse every reflection site outside *allowed*, every stale or unreasoned entry, and an unread tree."""
    files = [rel for rel in scanned_files(root) if (root / rel).is_file()]
    floors.assert_floor(len(files), floor=floor, what='reflection')
    found = {rel: lines for rel in files if (lines := reflection_sites((root / rel).read_text(encoding='utf-8'), rel))}
    new = [f'{rel}:{line}' for rel, lines in found.items() if rel not in allowed for line in lines]
    stale = sorted(set(allowed) - set(found))
    unreasoned = sorted(rel for rel, why in allowed.items() if not why.strip())
    if new or stale or unreasoned:
        msg = (
            f'NO-REFLECTION: attribute/namespace probes, reflective helpers and hooks are banned. '
            f'Replace each with typed access (attribute, isinstance on a Protocol, dataclasses, a dict, '
            f'pytest.raises(AttributeError)) -- never vars()/__dict__. new={new} '
            f'stale allow entries (delete them)={stale} allow entries without a reason={unreasoned}'
        )
        raise AssertionError(msg)
