"""THE FAMILY'S ONE STATIC IMPORT-EDGE READER for architecture tests: what a module imports, read off its source.

A layering test, a door-ownership test and a "who imports X" census all ask the same question, and each repo
had grown its own ``ast`` walk with its own blind spots. Read once, here, never executing the inspected code:

* EVERY NESTING DEPTH: ``ast.walk`` collects a function-body import. "Lazy imports are banned, so the
  module-level graph is the dependency relation" was measured false in a consumer repo (over a thousand
  function-body imports under a file-level waiver).
* BOTH SPELLINGS: ``from .b import f`` carries its package in ``node.level``; a reader dropping relative
  imports cut every shared test double off from its importers.
* SRC LAYOUT (:func:`module_name`): a file under ``src/`` is named without the prefix.
* ATTRIBUTE USES (:func:`dotted_uses`): ``import os`` then ``os.environ`` is a use of ``os.environ`` -- an attribute
  chain from a name an import binds, so a rule on a module attribute sees the spelling code actually uses.

:func:`read` answers all of it in one walk; :func:`cycle` names one cycle of an import graph, for every check
that refuses one.

Which tests a CHANGE reaches is a different, path-level question -- :mod:`dev_lab.dev.footprint`.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from importlib.util import resolve_name
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

__all__ = ['Reading', 'bindings', 'cycle', 'dotted_uses', 'import_edges', 'imports_of', 'module_name', 'read']


def module_name(root: Path, path: Path) -> str:
    """The dotted name *path* imports as: ``src/`` dropped, ``__init__`` folded into its package."""
    parts = list(path.relative_to(root).with_suffix('').parts)
    if parts[0] == 'src' and len(parts) > 1:
        parts = parts[1:]
    if parts[-1] == '__init__' and len(parts) > 1:
        parts = parts[:-1]
    return '.'.join(parts)


@dataclass(frozen=True, slots=True)
class Reading:
    """One module read once: its tree, every dotted name it uses (:func:`dotted_uses`), what each import binds."""

    tree: ast.Module
    uses: frozenset[str]
    bound: dict[str, str]


def _scan(tree: ast.AST, package: str) -> tuple[set[str], dict[str, str], list[ast.Attribute]]:
    """One walk: every absolute name imported, what each local alias stands for, and every attribute node."""
    names: set[str] = set()
    bound: dict[str, str] = {}
    attributes: list[ast.Attribute] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            attributes.append(node)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
                local = alias.asname or alias.name.partition('.')[0]
                bound[local] = alias.name if alias.asname else local
        elif isinstance(node, ast.ImportFrom):
            base = resolve_name('.' * node.level + (node.module or ''), package) if node.level else node.module or ''
            if base:
                names.add(base)
                for alias in node.names:
                    if alias.name != '*':
                        names.add(f'{base}.{alias.name}')
                        bound[alias.asname or alias.name] = f'{base}.{alias.name}'
    return names, bound, attributes


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
    return frozenset(_scan(ast.parse(source), package)[0])


def read(source: str, module: str, *, is_package: bool = False) -> Reading:
    """*source* (the module *module*) read in ONE walk: its tree, :func:`dotted_uses`, :func:`bindings`.

    Raises like :func:`import_edges`.
    """
    tree = ast.parse(source)
    names, bound, attributes = _scan(tree, module if is_package else module.rpartition('.')[0])
    for node in attributes:
        chain: list[str] = []
        head: ast.expr = node
        while isinstance(head, ast.Attribute):
            chain.append(head.attr)
            head = head.value
        if isinstance(head, ast.Name) and head.id in bound:
            names.add('.'.join([bound[head.id], *reversed(chain)]))
    return Reading(tree, frozenset(names), bound)


def bindings(source: str, module: str, *, is_package: bool = False) -> dict[str, str]:
    """Each local name an import in *source* binds -> the absolute name it stands for; raises like import_edges."""
    return read(source, module, is_package=is_package).bound


def dotted_uses(source: str, module: str, *, is_package: bool = False) -> frozenset[str]:
    """:func:`import_edges` plus every attribute chain read from a name an import binds, resolved to absolute names.

    ``import os`` + ``os.environ.get`` yields ``os.environ`` and ``os.environ.get``; ``from p import m`` + ``m.f``
    yields ``p.m.f``. A name rebound locally (a parameter shadowing an import) is not told apart. Raises like
    :func:`import_edges`.
    """
    return read(source, module, is_package=is_package).uses


def cycle(graph: Mapping[str, Iterable[str]]) -> list[str] | None:
    """One cycle of *graph* as ``[a, b, ..., a]``, else ``None`` (iterative DFS, deterministic order)."""
    state: dict[str, int] = {}  # 1: on the stack, 2: done
    for start in sorted(graph):
        if start in state:
            continue
        path, stack = [start], [iter(sorted(graph[start]))]
        state[start] = 1
        while stack:
            nxt = next(stack[-1], None)
            if nxt is None:
                state[path.pop()] = 2
                stack.pop()
            elif state.get(nxt) == 1:
                return [*path[path.index(nxt) :], nxt]
            elif nxt not in state:
                state[nxt] = 1
                path.append(nxt)
                stack.append(iter(sorted(graph.get(nxt, ()))))
    return None


def imports_of(root: Path, path: Path) -> frozenset[str]:
    """:func:`import_edges` of the file *path* under *root*, named by :func:`module_name`."""
    return import_edges(
        path.read_text(encoding='utf-8'), module_name(root, path), is_package=path.name == '__init__.py'
    )
