"""THE FAMILY'S ONE STATIC IMPORT-EDGE READER for architecture tests: what a module imports, read off its source.

A layering test, a door-ownership test and a "who imports X" census all ask the same question, and each repo
had grown its own ``ast`` walk with its own blind spots. Read once, here, never executing the inspected code:

* EVERY NESTING DEPTH: ``ast.walk`` collects a function-body import. "Lazy imports are banned, so the
  module-level graph is the dependency relation" was measured false in a consumer repo (over a thousand
  function-body imports under a file-level waiver).
* BOTH SPELLINGS: ``from .b import f`` carries its package in ``node.level``; a reader dropping relative
  imports cut every shared test double off from its importers.
* SRC LAYOUT (:func:`module_name`): a file under ``src/`` is named without the prefix.

Which tests a CHANGE reaches is a different, path-level question -- :mod:`dev_lab.dev.footprint`.
"""

from __future__ import annotations

import ast
from importlib.util import resolve_name
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['import_edges', 'imports_of', 'module_name']


def module_name(root: Path, path: Path) -> str:
    """The dotted name *path* imports as: ``src/`` dropped, ``__init__`` folded into its package."""
    parts = list(path.relative_to(root).with_suffix('').parts)
    if parts[0] == 'src' and len(parts) > 1:
        parts = parts[1:]
    if parts[-1] == '__init__' and len(parts) > 1:
        parts = parts[:-1]
    return '.'.join(parts)


def import_edges(source: str, module: str, *, is_package: bool = False) -> frozenset[str]:
    """Every absolute name *source* (the module *module*) imports, at any depth, never executing it.

    ``from X import y`` yields ``X`` and ``X.y``; a relative import is resolved against *module*'s package
    (*is_package*: *module* is itself a package's ``__init__``). Local aliases do not change an edge; assignments,
    dynamic imports and re-exports are not followed.

    Raises:
        SyntaxError: *source* does not parse -- a hidden edge is never reported as no edge.
        ImportError: a relative import climbs above the top-level package.

    """
    package = module if is_package else module.rpartition('.')[0]
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = resolve_name('.' * node.level + (node.module or ''), package) if node.level else node.module or ''
            if base:
                names.add(base)
                names.update(f'{base}.{alias.name}' for alias in node.names if alias.name != '*')
    return frozenset(names)


def imports_of(root: Path, path: Path) -> frozenset[str]:
    """:func:`import_edges` of the file *path* under *root*, named by :func:`module_name`."""
    return import_edges(
        path.read_text(encoding='utf-8'), module_name(root, path), is_package=path.name == '__init__.py'
    )
