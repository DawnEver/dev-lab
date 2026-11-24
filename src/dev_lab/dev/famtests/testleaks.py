r"""A TEST WRITES ONLY WHERE SOMETHING REMOVES IT: ``tmp_path``, never a temp entry nobody cleans or a host root.

Measured 2026-11-24 on one workstation: 8.9 GB in ``%TEMP%`` from the family's suites (a ``mkdtemp`` per run,
never removed) and whole trees at ``C:\var\tmp``, ``C:\results``, ``C:\src\repos`` -- a POSIX-rooted literal
that Windows resolves against the current drive. pytest's ``tmp_path`` is created under the session's base temp,
which :mod:`dev_lab.dev.testtemp` reclaims when the session ends, so it is the one place a test writes.

This body reads a test file's AST and names the line of each:

* ``mkdtemp(...)`` / ``mkstemp(...)`` -- an entry with no owner to remove it;
* ``NamedTemporaryFile(..., delete=False)`` -- the same, by request;
* ``gettempdir()`` -- a path into the shared temp dir that ``tmp_path`` already gives, cleaned;
* a string literal naming a host root: ``/tmp`` or ``/var/tmp`` (alone or as a path's head), or a bare drive
  root (``C:\``, ``C:/``). A remote's POSIX path (``/r/src/repos/x`` in a rendered command) is not one, and
  neither is an argument of a ``Pure*Path`` (it names a path and can never write one).

``TemporaryDirectory`` and ``NamedTemporaryFile`` that deletes are not named: their exit removes them.

WHAT THIS DOES NOT PROVE: a root built at run time (``Path('/') / 'var'``, an env read), or a relative path
joined onto the cwd, is invisible to a literal scan -- :mod:`dev_lab.dev.tmpsweep` names what those leave.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ['HOST_ROOT', 'UNOWNED_CALLS', 'WORDS', 'leaks']

#: Calls that create an entry nothing removes.
UNOWNED_CALLS: Final = frozenset({'mkdtemp', 'mkstemp', 'gettempdir'})
#: A literal naming a host root: ``/tmp`` or ``/var/tmp`` alone or as a path's head, or a bare drive root.
HOST_ROOT: Final = re.compile(r'^(?:/(?:var/)?tmp(?:/.*)?|[A-Za-z]:[\\/])$', re.DOTALL)
#: A source naming none of these cannot hold a finding, so it is never parsed.
WORDS: Final = ('mkdtemp', 'mkstemp', 'gettempdir', 'delete=False', '/tmp', ':\\', ':/')  # noqa: S108

_KEEP: Final = 'NamedTemporaryFile'
_PURE: Final = frozenset({'PurePath', 'PurePosixPath', 'PureWindowsPath'})


def _called(func: ast.expr) -> str:
    return func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ''


def _kept(node: ast.Call) -> bool:
    return any(
        kw.arg == 'delete' and isinstance(kw.value, ast.Constant) and kw.value.value is False for kw in node.keywords
    )


def _inert(tree: ast.Module) -> set[int]:
    """The ids of every constant that names no written path: a docstring, a ``Pure*Path`` argument."""
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _called(node.func) in _PURE:
            found.update(id(arg) for arg in node.args)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            head = node.body[0]
            if isinstance(head, ast.Expr) and isinstance(head.value, ast.Constant):
                found.add(id(head.value))
    return found


def _lines(tree: ast.Module) -> Iterator[int]:
    prose = _inert(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _called(node.func)
            if name in UNOWNED_CALLS or (name == _KEEP and _kept(node)):
                yield node.lineno
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in prose
            and HOST_ROOT.match(node.value)
        ):
            yield node.lineno


def leaks(source: str) -> tuple[int, ...]:
    """The sorted, distinct lines of *source* that create an unowned temp entry or name a host root."""
    return tuple(sorted(set(_lines(ast.parse(source)))))
