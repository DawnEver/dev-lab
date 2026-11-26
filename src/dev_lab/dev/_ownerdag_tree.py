"""WHERE THE OWNERS LIVE: the package tree, and which owner a repo path or an imported name belongs to.

The geometry :mod:`dev_lab.dev.ownerdag` judges edges over, read too by the pass-through, coverage and type doors.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from dev_lab.dev._layout_table import LayoutNotDeclared, declared_layout, declares
from dev_lab.dev.deptable import Declared

__all__ = ['PythonTree', 'native_stage', 'owner_of_name', 'owner_of_path', 'package_path', 'python_tree', 'sibling_hop']


@dataclass(frozen=True, slots=True)
class PythonTree:
    """Where the owners live: the package's import name, its repo-relative directory, its native module."""

    package: str
    directory: str
    native: str


def python_tree(root: Path) -> PythonTree | None:
    """The package ``[project].name`` names, at ``src/<name>`` or ``<name>``; ``None`` when neither exists.

    A package layout.toml declares but the tree does not hold yet (a skeleton: rows before code) is at its row.
    """
    try:
        name = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8')).get('project', {}).get('name')
    except (OSError, ValueError):
        return None
    if not isinstance(name, str) or not name:
        return None
    package = name.replace('-', '_').replace('.', '_')
    for directory in (f'src/{package}', package):
        if (root / directory).is_dir():
            return PythonTree(package, directory, f'{package}_native')
    try:
        layout = declared_layout(root)
    except LayoutNotDeclared:
        return None
    directory = next((d for d in (f'src/{package}', package) if declares(d, layout)), None)
    return None if directory is None else PythonTree(package, directory, f'{package}_native')


def owner_of_path(tree: PythonTree, rel: str) -> str | None:
    """The owner (child package) the repo-relative file *rel* lies in, else ``None``."""
    parts = PurePosixPath(rel).parts
    base = PurePosixPath(tree.directory).parts
    return parts[len(base)] if parts[: len(base)] == base and len(parts) > len(base) + 1 else None


def package_path(tree: PythonTree, rel: str) -> tuple[str, ...] | None:
    """The owner path of the package holding the repo-relative file *rel* (``("alpha", "one")``).

    ``None`` outside every owner: a file of the package root, or outside the package.
    """
    return (
        tuple(PurePosixPath(rel).parent.parts[len(PurePosixPath(tree.directory).parts) :])
        if owner_of_path(tree, rel)
        else None
    )


def native_stage(tree: PythonTree, stages: Mapping[str, tuple[str, ...]], name: str) -> tuple[str, ...] | None:
    """The stage (owner path) of the crate ``<package>_native.<crate>`` *name* imports, else ``None``."""
    parts = name.split('.')
    return stages.get(parts[1]) if parts[0] == tree.native and len(parts) > 1 else None


def owner_of_name(
    tree: PythonTree, decl: Declared, name: str, stages: Mapping[str, tuple[str, ...]] | None = None
) -> str | None:
    """The owner the absolute name *name* belongs to: a child package, or a native crate's stage's; else ``None``."""
    parts = name.split('.')
    if parts[0] == tree.package and len(parts) > 1 and parts[1] in decl.owners:
        return parts[1]
    stage = native_stage(tree, stages or {}, name)
    return stage[0] if stage else None


def sibling_hop(root: Path, tree: PythonTree, rel: str, name: str) -> tuple[str, str, str] | None:
    """``(parent, importer's child, imported child)`` when *rel* and *name* lie in two children of one package.

    Inside an owner only; *parent* is that package's path under the package root (``alpha``, ``alpha/one``).
    """
    mine = list(PurePosixPath(rel).relative_to(tree.directory).with_suffix('').parts)[:-1]  # the file's package
    theirs = name.split('.')[1:]
    i = 0
    while i < min(len(mine), len(theirs)) and mine[i] == theirs[i]:
        i += 1
    if i == 0 or i >= len(mine) or i >= len(theirs) or not (root / tree.directory / Path(*theirs[: i + 1])).is_dir():
        return None
    return '/'.join(mine[:i]), mine[i], theirs[i]
