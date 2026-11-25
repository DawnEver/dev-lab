"""Lexical callable origins shared by the reflection and tolerance guards.

Imports and simple assignments preserve origins; parameters and other local bindings shadow them.
This is the existing reflection reader's binding mechanism, not a runtime import resolver. Each
caller declares the builtin names it recognizes and judges the returned origins by its own policy.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection

__all__ = ['call_origins']


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


class _CallOrigins:
    def __init__(self, builtins: Collection[str]) -> None:
        self.builtins = frozenset(builtins)
        self.scopes: list[tuple[str, dict[str, str | None]]] = [('module', {})]
        self.calls: list[tuple[ast.Call, str | None]] = []

    def origin(self, node: ast.AST | None) -> str | None:
        if isinstance(node, ast.Name):
            for _kind, bindings in reversed(self.scopes):
                if node.id in bindings:
                    return bindings[node.id]
            return f'builtins.{node.id}' if node.id in self.builtins else None
        if isinstance(node, ast.Attribute) and (owner := self.origin(node.value)) is not None:
            return f'{owner}.{node.attr}'
        return None

    def bind(self, target: ast.AST, value: str | None) -> None:
        if isinstance(target, ast.Name):
            self.scopes[-1][1][target.id] = value
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
        for alias in node.names:
            if isinstance(node, ast.Import):
                name = alias.asname or alias.name.split('.')[0]
                value = alias.name if alias.asname else alias.name.split('.')[0]
            else:
                name = alias.asname or alias.name
                value = f'{node.module}.{alias.name}' if not node.level else None
            self.scopes[-1][1][name] = value

    def assign(self, node: ast.Assign | ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit(node.value)
        value = self.origin(node.value)
        for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
            self.visit(target)
            self.bind(target, value)

    def visit(self, node: ast.AST) -> None:
        if isinstance(node, ast.Call):
            self.calls.append((node, self.origin(node.func)))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            self.scope(node)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            self.import_names(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            self.assign(node)
        else:
            for child in ast.iter_child_nodes(node):
                self.visit(child)


def call_origins(tree: ast.AST, *, builtins: Collection[str]) -> tuple[tuple[ast.Call, str | None], ...]:
    """Calls and imported/builtin origins in lexical traversal order; ``None`` means an unknown/user binding.

    The builtin vocabulary is explicitly the caller's. No consumer policy, source walk or I/O lives here.
    """
    scan = _CallOrigins(builtins)
    scan.visit(tree)
    return tuple(scan.calls)
