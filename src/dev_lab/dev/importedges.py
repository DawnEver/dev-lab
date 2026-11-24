"""THE FAMILY'S ONE STATIC IMPORT-EDGE READER: which module imports which, read off the source by ``ast``.

Architecture tests (layering, door ownership) and change-based test selection
(:mod:`dev_lab.dev.changeselect`) both need the same relation, so it is read once, here.

* EVERY NESTING DEPTH: ``ast.walk`` collects a function-body import as an edge. "Lazy imports are banned,
  so the module-level graph is the dependency relation" was measured false in a consumer repo (over a
  thousand function-body imports under a file-level waiver).
* BOTH SPELLINGS: ``from .b import f`` carries its package in ``node.level``; dropping relative imports
  cut every shared test double off from its importers.
* SRC LAYOUT: a file under ``src/`` is named without the prefix; any other file is named from the root.

Names are STRINGS and resolve to a module only when that module is in the tree (:func:`edges`): a name
the tree lacks (a third-party import) is no edge.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

__all__ = ['closure', 'edges', 'imports_of', 'module_name', 'python_files']

#: Trees never read for edges: environments, caches and build outputs, not the project's source.
_SKIPPED: Final[frozenset[str]] = frozenset(
    {
        '.git',
        '.venv',
        'venv',
        'node_modules',
        'target',
        'output',
        'build',
        'dist',
        '__pycache__',
        '.claude',
    }
)


def python_files(root: Path) -> tuple[Path, ...]:
    """Every ``*.py`` under *root* outside :data:`_SKIPPED` and hidden directories, sorted."""
    return tuple(
        sorted(
            path
            for path in root.rglob('*.py')
            if not any(part in _SKIPPED or part.startswith('.') for part in path.relative_to(root).parts[:-1])
        )
    )


def module_name(root: Path, path: Path) -> str:
    """The dotted name *path* imports as: ``src/`` dropped, ``__init__`` folded into its package."""
    parts = list(path.relative_to(root).with_suffix('').parts)
    if parts[0] == 'src' and len(parts) > 1:
        parts = parts[1:]
    if parts[-1] == '__init__' and len(parts) > 1:
        parts = parts[:-1]
    return '.'.join(parts)


def _package(root: Path, path: Path) -> str:
    name = module_name(root, path)
    return name if path.name == '__init__.py' else name.rpartition('.')[0]


def imports_of(root: Path, path: Path) -> frozenset[str]:
    """Every dotted name *path* imports, at any depth; ``from X import y`` yields ``X`` and ``X.y``."""
    try:
        tree = ast.parse(path.read_text(encoding='utf-8', errors='replace'))
    except SyntaxError:
        return frozenset()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ''
            if node.level:
                package = _package(root, path).split('.')
                anchor = '.'.join(package[: len(package) - node.level + 1])
                base = f'{anchor}.{base}' if base else anchor
            if base:
                names.add(base)
                names.update(f'{base}.{alias.name}' for alias in node.names if alias.name != '*')
    return frozenset(names)


def _resolve(name: str, index: frozenset[str]) -> str | None:
    while name:
        if name in index:
            return name
        name = name.rpartition('.')[0]
    return None


def edges(root: Path, files: Iterable[Path] | None = None) -> dict[str, frozenset[str]]:
    """``{module: the in-tree modules it imports}`` over *files* (default :func:`python_files`)."""
    chosen = python_files(root) if files is None else tuple(files)
    index = frozenset(module_name(root, path) for path in chosen)
    graph: dict[str, frozenset[str]] = {}
    for path in chosen:
        name = module_name(root, path)
        resolved = {_resolve(imported, index) for imported in imports_of(root, path)}
        graph[name] = frozenset(found for found in resolved if found is not None and found != name)
    return graph


def closure(graph: dict[str, frozenset[str]], seeds: Iterable[str]) -> set[str]:
    """*seeds* and everything they reach through *graph*."""
    seen: set[str] = set()
    stack = list(seeds)
    while stack:
        name = stack.pop()
        if name not in seen:
            seen.add(name)
            stack.extend(graph.get(name, ()))
    return seen
