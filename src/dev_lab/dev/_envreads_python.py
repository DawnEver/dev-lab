"""ENV-IS-READ-ONCE's Python reader: which lines reach the environment through ``os``, and which decide a test runs.

The rule, its classes and its doors are :mod:`dev_lab.dev.envreads`; this module only reads Python source.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Final

__all__ = ['python_reads', 'python_switches']

#: The calls whose condition argument decides whether a test runs, and the calls a skipping branch makes.
_CONDITION_CALLS: Final = frozenset({'skipif', 'xfail'})
_SKIP_CALLS: Final = frozenset({'skip', 'skipif', 'xfail', 'importorskip'})
_ENVIRONS: Final = frozenset({'environ', 'environb'})
_GETENVS: Final = frozenset({'getenv', 'getenvb'})
_OS_NAMES: Final = frozenset({'environ', 'environb', 'getenv', 'getenvb', 'putenv', 'unsetenv'})


@dataclass(frozen=True, slots=True)
class _Os:
    """How one source reaches ``os``: the names bound to the module, and each local name imported from it."""

    modules: frozenset[str]
    members: dict[str, str]

    def member(self, node: ast.AST) -> str:
        """The :data:`_OS_NAMES` member *node* names (``os.environ``, an imported ``getenv`` alias), else ``''``."""
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in self.modules:
            return node.attr if node.attr in _OS_NAMES else ''
        return self.members.get(node.id, '') if isinstance(node, ast.Name) else ''


def _os_bindings(tree: ast.AST) -> _Os:
    modules: set[str] = set()
    members: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.asname or alias.name for alias in node.names if alias.name == 'os'}
        elif isinstance(node, ast.ImportFrom) and node.module == 'os' and not node.level:
            members |= {alias.asname or alias.name: alias.name for alias in node.names if alias.name in _OS_NAMES}
    return _Os(frozenset(modules), members)


def _read_lines(tree: ast.AST, bound_os: _Os) -> set[int]:
    return {node.lineno for node in ast.walk(tree) if isinstance(node, ast.expr) and bound_os.member(node)}


def python_reads(source: str) -> tuple[int, ...]:
    """The lines of *source* reaching the environment through ``os`` (the shapes: :mod:`dev_lab.dev.envreads`)."""
    tree = ast.parse(source)
    return tuple(sorted(_read_lines(tree, _os_bindings(tree))))


def _named_read_lines(tree: ast.AST, bound_os: _Os) -> set[int]:
    """Lines reading ONE variable by name -- ``environ[..]``, ``environ.get(..)``, ``getenv(..)``, ``.. in environ``.

    Handing the whole environment to a child (``{**os.environ}``, ``dict(os.environ)``) reads no variable's value.
    """
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            hit = bound_os.member(node.value) in _ENVIRONS
        elif isinstance(node, ast.Call):
            func = node.func
            get = isinstance(func, ast.Attribute) and func.attr == 'get' and bound_os.member(func.value) in _ENVIRONS
            hit = get or bound_os.member(func) in _GETENVS
        elif isinstance(node, ast.Compare):
            hit = any(
                isinstance(op, ast.In | ast.NotIn) and bound_os.member(right) in _ENVIRONS
                for op, right in zip(node.ops, node.comparators, strict=True)
            )
        else:
            hit = False
        if hit and isinstance(node, ast.expr):
            lines.add(node.lineno)
    return lines


def _callee(node: ast.AST) -> str:
    if not isinstance(node, ast.Call):
        return ''
    func = node.func
    return func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ''


def _conditions(tree: ast.AST) -> list[ast.expr]:
    """Every expression deciding whether a test runs: a ``skipif``/``xfail`` condition, a skipping branch's test."""
    found: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _callee(node) in _CONDITION_CALLS:
            found += [*node.args, *(kw.value for kw in node.keywords if kw.arg == 'condition')]
        elif isinstance(node, ast.If | ast.IfExp | ast.While):
            branches = [node.body, node.orelse] if isinstance(node, ast.IfExp) else [*node.body, *node.orelse]
            if any(_callee(inner) in _SKIP_CALLS for branch in branches for inner in ast.walk(branch)):
                found.append(node.test)
    return found


def python_switches(source: str) -> tuple[int, ...]:
    """The lines of *source* whose environment read decides whether a test runs (class C).

    The class is :mod:`dev_lab.dev.envreads`'s.
    """
    tree = ast.parse(source)
    bound_os = _os_bindings(tree)
    bound: dict[str, set[int]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign | ast.AnnAssign | ast.NamedExpr) or node.value is None:
            continue
        if lines := _named_read_lines(node.value, bound_os):
            for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                if isinstance(target, ast.Name):
                    bound.setdefault(target.id, set()).update(lines)
    found: set[int] = set()
    for condition in _conditions(tree):
        found |= _named_read_lines(condition, bound_os)
        found |= {line for name in ast.walk(condition) if isinstance(name, ast.Name) for line in bound.get(name.id, ())}
    return tuple(sorted(found))
