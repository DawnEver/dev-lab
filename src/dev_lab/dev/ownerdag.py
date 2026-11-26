"""OWNER-DAG: a repo's actual imports against the owner graph its root ``dependencies.toml`` declares.

User-approved 2026-11-25 (principles ``everything-in-its-place`` and ``no-detour``). The declaration and its shape
are :mod:`dev_lab.dev.deptable`'s; a repo without the file is not judged, and every entry says so. This module reads
the tracked tree (nothing is imported or run) and refuses, naming the file, the name and the row:

* PYTHON (read with :mod:`dev_lab.dev.pyfacts`, so ``os.environ`` after ``import os`` counts). The
  owners are the child packages of the repo's package (``src/<[project].name>``, ``-`` read as ``_``; or
  ``<name>`` at the root): an owner importing an owner its ``[python.owners]`` row does not list; two children of
  one package inside an owner importing each other (siblings, at every depth; a nested package's table is keyed by
  its path, ``[python.siblings."compile/transform"]``) unless ``[python.siblings."<package
  path>"]`` lists the edge -- default none; any importer from another owner of a path ``[python.importers]`` names
  unless it lies under one of that row's importers (a narrowing below the owner edge, never a widening);
  ``<package>_native.<crate>`` imported by an owner that neither owns the crate (``[python.native]``) nor lists its
  owner, a crate no row names, or the bare native module; a third-party or family name no ``[python.packages]`` row
  names, or one used outside its row's paths; a restricted ``[python.stdlib]`` name used outside its paths (a
  dotted member such as ``os.system``, a builtin as ``builtins.open``, a private module such as ``_thread``). A child
  package with no row is refused, and so is every dependencies.toml path no layout.toml row declares (layout.toml is
  the one source of which directories may exist; a declared owner not created yet passes, and whether a path exists
  is DECLARED-LAYOUT's to judge). A test file is judged like any other, ``tests`` or ``tests/unit`` naming it as a
  path; an import of a repo-local name (``tests``, a sibling module) is not judged.
* RUST: :mod:`dev_lab.dev.rustdeps` (Cargo dependencies and std paths).
* THE DECLARATION ITSELF: :mod:`dev_lab.dev.depcites` -- a package, stdlib name or crate a row's reason cites and
  no row grants, before any code uses it.

WHAT IT CANNOT SEE: a dynamic import, a name rebound locally, an attribute reached through an assignment.
Where it runs: the always-on family check (:func:`check`), every ``verify`` (:func:`refusal`), and the CLI
(``python -m dev_lab.dev.ownerdag``). Pass-through hops are :mod:`dev_lab.dev.passthrough` (NO-DETOUR).
"""

from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final

from lab_commons.log import emit

from dev_lab.dev import depcites, deptable, pyfacts, rustdeps
from dev_lab.dev._layout_table import Layout, LayoutNotDeclared, declared_layout, declares
from dev_lab.dev.deptable import ALL, Declared, DependenciesError, Grant, edge_to
from dev_lab.dev.rules import tracked_files

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

__all__ = [
    'DOOR',
    'RULE_ID',
    'PythonTree',
    'check',
    'holds',
    'judged',
    'main',
    'owner_of_name',
    'owner_of_path',
    'problems',
    'python_tree',
    'refusal',
    'sibling_hop',
]

RULE_ID: Final = 'OWNER-DAG'
DOOR: Final = (
    'when the dependency is wanted, declare it in dependencies.toml (an owner edge, or a package/stdlib/crate row '
    'saying why); when it is not, move the code to the one owner responsible for it -- never a pointer or a copy; '
    'a cycle or a sibling import is broken by moving what both need down to their parent'
)
_DETAILS: Final = 'details: docs-src/dev/refusals.md#owner-dag (dev-lab)'
_FILE: Final = deptable.FILE
_UNDECLARED: Final = 'which no layout.toml row declares'


@dataclass(frozen=True, slots=True)
class PythonTree:
    """Where the owners live: the package's import name, its repo-relative directory, its native module."""

    package: str
    directory: str
    native: str


def python_tree(root: Path) -> PythonTree | None:
    """The package ``[project].name`` names, at ``src/<name>`` or ``<name>``; ``None`` when neither exists."""
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
    return None


def owner_of_path(tree: PythonTree, rel: str) -> str | None:
    """The owner (child package) the repo-relative file *rel* lies in, else ``None``."""
    parts = PurePosixPath(rel).parts
    base = PurePosixPath(tree.directory).parts
    return parts[len(base)] if parts[: len(base)] == base and len(parts) > len(base) + 1 else None


def owner_of_name(tree: PythonTree, decl: Declared, name: str) -> str | None:
    """The owner the absolute name *name* belongs to: a child package, or a native crate's owner; else ``None``."""
    parts = name.split('.')
    if parts[0] == tree.package and len(parts) > 1 and parts[1] in decl.owners:
        return parts[1]
    if parts[0] == tree.native and len(parts) > 1:
        return decl.native.get(parts[1])
    return None


def holds(holders: Iterable[str], rel: str) -> bool:
    """Whether the repo-relative path *rel* lies at or below one of *holders* (``*`` holds everything)."""
    return any(h in {ALL, rel} or rel.startswith(h + '/') for h in holders)


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


def _child_of(scope: _Scope, rel: str, name: str) -> tuple[str, str] | None:
    """``(parent, child)`` when *name* lies in a child package of *rel*'s package (a child may import its parent)."""
    mine = list(PurePosixPath(rel).relative_to(scope.tree.directory).with_suffix('').parts)[:-1]
    theirs = name.split('.')[1:]
    if len(theirs) <= len(mine) or theirs[: len(mine)] != mine:
        return None
    child = theirs[: len(mine) + 1]
    if not (scope.root / scope.tree.directory / Path(*child)).is_dir():
        return None
    return '/'.join(mine), '/'.join(child)


@dataclass(frozen=True, slots=True)
class _Scope:
    """What every Python judgment reads: the checkout, its declaration, its package, its repo-local top names."""

    root: Path
    decl: Declared
    tree: PythonTree
    tops: frozenset[str]
    layout: Layout | None
    local: dict[tuple[Path, str], bool] = field(default_factory=dict)

    def beside(self, rel: str, top: str) -> bool:
        """Whether *top* is a module or package beside the importer *rel* (asked once per directory and name)."""
        folder = (self.root / rel).parent
        if (folder, top) not in self.local:
            self.local[folder, top] = (folder / f'{top}.py').is_file() or (folder / top).is_dir()
        return self.local[folder, top]

    def declared(self, rel: str) -> bool:
        """Whether layout.toml declares the repo path *rel* (never the disk: a declared path may not exist yet)."""
        return self.layout is not None and declares(rel, self.layout)

    def in_package(self, path: str) -> bool:
        """Whether *path* names a package a row declares under the package, or a module that exists there.

        A row declares directories and formats, never one module, so a module path is known by its file.
        """
        base = f'{self.tree.directory}/{path}'
        package = self.declared(base) if self.layout is not None else (self.root / base).is_dir()
        return package or (self.root / f'{base}.py').is_file()

    def importer(self, entry: str) -> str:
        """The repo path an importer entry names: under the package when it is there, else itself (``tests/unit``)."""
        return f'{self.tree.directory}/{entry}' if self.in_package(entry) else entry


def _maximal(names: frozenset[str]) -> list[str]:
    """The names no other name extends -- ``from a import b`` judges ``a.b``, never the bare ``a`` it also yields."""
    return sorted(n for n in names if not any(o.startswith(n + '.') for o in names))


def _row(rows: Mapping[str, Grant], name: str) -> tuple[str, Grant] | None:
    """The longest dotted-prefix row of *rows* naming *name*."""
    keys = [k for k in rows if name == k or name.startswith(k + '.')]
    return (key := max(keys, key=len), rows[key]) if keys else None


def _importers(scope: _Scope, rel: str, name: str) -> str | None:
    """The ``[python.importers]`` refusal: *name* lies under a row whose importers do not hold *rel*."""
    path = '/'.join(name.split('.')[1:])
    keys = [k for k in scope.decl.importers if path == k or path.startswith(k + '/')]
    if not keys or owner_of_path(scope.tree, rel) == (key := max(keys, key=len)).split('/')[0]:
        return None
    who = scope.decl.importers[key]
    if holds([scope.importer(w) for w in who], rel):
        return None
    return f'imports {name}, but [python.importers] "{key}" allows only {", ".join(who)}'


def _within_owner(scope: _Scope, rel: str, name: str) -> str | None:
    """Inside one owner: a parent importing its child, or a sibling import its table does not list."""
    if (child := _child_of(scope, rel, name)) is not None:
        return f'{child[0]} imports its own child {child[1]} ({name}); a parent never imports its children'
    if (hop := sibling_hop(scope.root, scope.tree, rel, name)) is None:
        return None
    parent, child_name, other = hop
    if edge_to(scope.decl.siblings.get(parent, {}).get(child_name, ()), other):
        return None
    return (
        f'{parent}/{child_name} imports its sibling {parent}/{other}, but [python.siblings."{parent}"] {child_name} '
        f'does not list {other}'
    )


def _internal(scope: _Scope, rel: str, name: str) -> str | None:
    decl = scope.decl
    mine, theirs = owner_of_path(scope.tree, rel), owner_of_name(scope.tree, decl, name)
    if theirs is None:
        return None
    if mine is not None and mine == theirs:
        return _within_owner(scope, rel, name)
    if mine is not None and not edge_to(decl.owners[mine], theirs):
        return f'owner {mine} imports {name} (owner {theirs}), but [python.owners] {mine} does not list {theirs}'
    return _importers(scope, rel, name)


def _native(scope: _Scope, rel: str, name: str) -> str | None:
    parts, mine = name.split('.'), owner_of_path(scope.tree, rel)
    if len(parts) == 1:
        return f'imports the bare native module {name}; import the crate module {name}.<crate>'
    if parts[1] not in scope.decl.native:
        return f'imports {name}, but {parts[1]} is no [python.native] row'
    theirs = scope.decl.native[parts[1]]
    if mine is None or mine == theirs or edge_to(scope.decl.owners[mine], theirs):
        return None
    return f'owner {mine} imports {name}, whose crate {parts[1]} belongs to owner {theirs}, which it does not list'


def _external(scope: _Scope, rel: str, name: str) -> str | None:
    top = name.partition('.')[0]
    if top in scope.tops or scope.beside(rel, top):
        return None
    stdlib = top in sys.stdlib_module_names
    table, rows = ('stdlib', scope.decl.stdlib) if stdlib else ('packages', scope.decl.packages)
    if (found := _row(rows, name)) is None:
        return None if stdlib else f'imports {name}, which no [python.packages] row names'
    key, grant = found
    if holds(grant.holders, rel):
        return None
    return f'uses {name}, but [python.{table}] {key} allows it only in {", ".join(grant.holders) or "nowhere"}'


def _judge(scope: _Scope, rel: str, name: str) -> str | None:
    top = name.partition('.')[0]
    if top == scope.tree.package:
        return _internal(scope, rel, name)
    return _native(scope, rel, name) if top == scope.tree.native else _external(scope, rel, name)


def _local_tops(files: Iterable[str], tree: PythonTree) -> frozenset[str]:
    """Top-level names the repo itself provides (``tests``, a root module) -- never a third-party package."""
    tops = {PurePosixPath(f).parts[0].removesuffix('.py') for f in files if f.endswith('.py')}
    tops |= {PurePosixPath(f).parts[1].removesuffix('.py') for f in files if f.startswith('src/') and f.count('/') > 1}
    return frozenset(tops - {'src'}) | {tree.package, tree.native}


def _python_problems(root: Path, decl: Declared, files: list[str], layout: Layout | None) -> list[str]:
    if not (decl.owners or decl.native or decl.packages or decl.stdlib or decl.importers):
        return []
    tree = python_tree(root)
    if tree is None:
        return [
            (
                '[python.*] is declared, but pyproject.toml [project].name names no package at src/<name> or '
                f'<name> (read: {_project_name(root)!r} -> src/{_project_name(root)})'
            )
        ]
    scope = _Scope(root, decl, tree, _local_tops(files, tree), layout)
    out = _stale_rows(scope, files)
    for rel, one in sorted(pyfacts.facts(root, (f for f in files if f.endswith('.py'))).items()):
        if one.error is not None:
            out.append(f'{rel}: does not parse ({one.error}), so its imports cannot be judged')
        out += [f'{rel}: {why}' for name in _maximal(one.uses) if (why := _judge(scope, rel, name))]
    return list(dict.fromkeys(out))


def _stale_rows(scope: _Scope, files: list[str]) -> list[str]:
    """Rows against layout.toml (never the disk), and a child package in the tree no owner row names."""
    decl, under = scope.decl, f'{scope.tree.directory}/'
    out = [
        f'{p} is an owner no [python.owners] row names'
        for p in _children(scope.tree, files)
        if p not in _rows(scope.tree, decl)
    ]
    if scope.layout is None:
        return out
    named: list[tuple[str, str, bool]] = [
        (f'[python.owners] {o}', f'{under}{o}', scope.declared(f'{under}{o}')) for o in decl.owners
    ]
    for parent, rows in decl.siblings.items():
        named.append((f'[python.siblings."{parent}"]', f'{under}{parent}', scope.declared(f'{under}{parent}')))
        if named[-1][2]:
            children = sorted({n for child, edges in rows.items() for n in (child, *(e.name for e in edges))} - {ALL})
            path = f'{under}{parent}/'
            named += [(f'[python.siblings."{parent}"]', f'{path}{c}', scope.declared(f'{path}{c}')) for c in children]
    for key, who in decl.importers.items():
        named.append((f'[python.importers] "{key}"', f'{under}{key}', scope.in_package(key)))
        named += [(f'[python.importers] "{key}"', f'importer {w}', scope.declared(scope.importer(w))) for w in who]
    for table, grants in (('packages', decl.packages), ('stdlib', decl.stdlib)):
        named += [
            (f'[python.{table}] {key}', h, scope.declared(h))
            for key, grant in grants.items()
            for h in grant.holders
            if h != ALL
        ]
    return out + [f'{_FILE} {row} names {path}, {_UNDECLARED}' for row, path, ok in named if not ok]


def _project_name(root: Path) -> str:
    try:
        return str(tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))['project']['name'])
    except (OSError, ValueError, KeyError):
        return '<no [project].name>'


def _children(tree: PythonTree, files: Iterable[str]) -> list[str]:
    base = len(PurePosixPath(tree.directory).parts)
    found = {PurePosixPath(f).parts[: base + 1] for f in files if f.endswith('.py') and owner_of_path(tree, f)}
    return sorted('/'.join(parts) for parts in found)


def _rows(tree: PythonTree, decl: Declared) -> set[str]:
    return {f'{tree.directory}/{o}' for o in decl.owners}


def problems(root: Path, decl: Declared, files: Iterable[str]) -> list[str]:
    """Every OWNER-DAG refusal over the repo-relative *files* (Python, then Rust), each naming file, name and row."""
    files = sorted(files)
    try:
        layout, out = declared_layout(root), []
    except LayoutNotDeclared as exc:
        layout = None
        out = [f'{_FILE} paths are layout.toml rows, but {root.name} declares no usable layout.toml ({exc})']
    out += depcites.problems(decl)
    return out + _python_problems(root, decl, files, layout) + rustdeps.problems(root, decl, files, layout=layout)


def judged(root: Path, judge: Callable[[Path, Declared, Iterable[str]], list[str]]) -> list[str] | None:
    """*judge*'s refusals over *root*'s tracked tree; ``None`` when undeclared; a malformed declaration is refused."""
    try:
        decl = deptable.load(root)
    except DependenciesError as exc:
        return [str(exc)]
    if decl is None:
        return None
    return judge(root, decl, (f for f in tracked_files(root) if (root / f).is_file()))


def _report(found: list[str]) -> str:
    return '\n'.join([f'{RULE_ID}: {len(found)} refusal(s)', *found, f'door: {DOOR}', _DETAILS])


def check(root: Path) -> None:
    """The always-on family check: raise naming every refusal in *root*'s tracked tree (when declared)."""
    if found := judged(root, problems):
        raise AssertionError(_report(found))


def refusal(root: Path) -> str | None:
    """What ``verify`` refuses on; ``None`` when clean or undeclared (not judged)."""
    if not deptable.declared(root):
        return None
    found = judged(root, problems)
    return _report(found) if found else None


def main(argv: list[str] | None = None, *, cwd: Path | None = None) -> int:
    """Judge the tracked tree; exit 1 on a refusal, 0 when clean or undeclared (and say which)."""
    del argv
    root = cwd or Path.cwd()
    if not deptable.declared(root):
        emit(f'{RULE_ID}: {root.name} holds no {deptable.FILE}, so this repo is not judged (opt-in)', flush=True)
        return 0
    if not (found := judged(root, problems)):
        return 0
    emit(_report(found), flush=True)
    return 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
