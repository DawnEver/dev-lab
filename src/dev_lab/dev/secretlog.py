"""NEVER-LOG-SECRETS: a log line never carries a credential's value, only its hash.

A token, key, password or fingerprint is written as its hash or not at all (user ruling, moved into the family
registry 2026-11-24).

THE READING IS SYNTACTIC AND DELIBERATELY NARROW: a call to an output sink (:data:`SINKS` -- ``emit``, ``print``,
a ``logging`` method, ``write``) whose formatted argument interpolates a NAME that spells a secret
(:data:`SECRET_NAME`) directly. Wrapping the value in any call (``sha256(token)``, ``fingerprint_hash(key)``,
``len(token)``) is the sanctioned form and is not a finding; the scan cannot see a secret passed under an
innocent name, which is why the rule also lives in review.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ['SECRET_NAME', 'SINKS', 'secret_interpolations']

#: The call names that write a line somewhere a person or a file keeps it.
SINKS: Final = frozenset({'emit', 'print', 'debug', 'info', 'warning', 'error', 'exception', 'critical', 'write'})
#: An identifier that names a credential's VALUE (not its path, name or presence).
SECRET_NAME: Final = re.compile(
    r'(?:^|_)(?:token|secret|password|passwd|api_key|apikey|private_key|fingerprint)(?:$|_)', re.IGNORECASE
)
_NOT_A_VALUE: Final = re.compile(r'(?:_|^)(?:path|file|name|names|env|var|kind|ref|rel|dir|len|count|id|ids)$')


def _leaf(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
        return node.slice.value
    return None


def _secret_values(node: ast.AST) -> Iterator[str]:
    for part in ast.walk(node):
        if isinstance(part, ast.FormattedValue):
            name = _leaf(part.value)
            if name and SECRET_NAME.search(name) and not _NOT_A_VALUE.search(name):
                yield name


def _sink(call: ast.Call) -> bool:
    func = call.func
    name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ''
    return name in SINKS


def secret_interpolations(source: str) -> tuple[tuple[int, str], ...]:
    """``(line, name)`` for every sink call in *source* interpolating a secret-named value unwrapped."""
    found = [
        (node.lineno, name)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and _sink(node)
        for arg in (*node.args, *(keyword.value for keyword in node.keywords))
        for name in _secret_values(arg)
    ]
    return tuple(sorted(set(found)))
