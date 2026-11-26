"""The declared half of OWNER-DAG: a repo's root ``dependencies.toml`` read by its SHAPE and validated.

User-approved 2026-11-25 (principles ``everything-in-its-place`` and ``no-detour``). A repo opts in by holding
:data:`FILE` at its root (frozen beside ``layout.toml`` where the repo freezes); without it the repo is not judged.
The file names only PERMISSION -- versions stay in ``pyproject.toml`` / ``Cargo.toml`` and their locks. The checker
keys to the tables, never to an owner's name, so a repo renames its owners freely::

    [python.owners]              # owner -> the owners it may import; acyclic. An owner is a child package of
    contracts = []               # the repo's package (src/<[project].name>)
    compile = ["contracts", { name = "models", adds = "translation" }]   # adds: what a forwarding hop adds
    [python.siblings.compile]    # inside one package (an owner, or "owner/child" at any depth): child -> the
    emit = ["transform"]         # sibling children it may import; default none; acyclic; an edge may carry adds
    [python.importers]           # a path under the package -> the ONLY importers from other owners (paths under
    "contracts/formats" = ["compile/emit", "tests"]  # the package, else repo paths); narrows, never widens
    [python.packages]            # third-party / family package (dotted prefix) -> repo paths ("*" = everywhere);
    numpy = { owners = ["*"], reason = "..." }       # an unlisted one is refused everywhere
    sympy = { owners = ["src/pkg/compile"], load = "deferred", reason = "4.9 s import; ..." }  # imported only
                                 # inside a function, and only a deferred row may be (NO-LAZY-IMPORT made declarative)
    [python.stdlib]              # restricted standard-library names (dotted prefix); unlisted = allowed
    "os.environ" = { owners = [], reason = "..." }   # [] = nowhere
    [rust.external]              # external crate -> crates; kind normal (default) | build | dev; features required;
    rayon = { crates = ["assemble"], reason = "..." }   # dev_crates: crates granted it for tests only
    serde_json = { crates = ["contracts"], dev_crates = ["*"], reason = "..." }
    [rust.std]                   # restricted std paths or tokens (unsafe, extern "C") -> crates; unlisted = allowed
    "std::env" = { crates = [], reason = "..." }

There is no crate table: a workspace crate lives at ``rust/crates/<owner path>`` (``rust/crates/compile/assemble``,
named ``compile_assemble``), so it IS a stage of the Python owner graph, and its Cargo edges are judged by the same
``[python.owners]`` / ``[python.siblings.*]`` edges (:func:`hop`); ``<package>_native.<crate>`` is that stage too.
A stage whose implementation is only a crate (no Python folder) is a sibling like any other (NATIVE-FIRST).

Every row of a grant table says why (``reason``). A cycle, an edge naming no row, an unknown key or table, and a
value of the wrong shape are refused here, naming the row; whether rows match the TREE is :mod:`dev_lab.dev.ownerdag`.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, NoReturn

from dev_lab.dev.importedges import cycle

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

__all__ = [
    'ADDS',
    'ALL',
    'FILE',
    'KINDS',
    'LOADS',
    'RETIRED',
    'Declared',
    'DependenciesError',
    'Edge',
    'Grant',
    'Hop',
    'declared',
    'edge_to',
    'hop',
    'load',
]

FILE: Final = 'dependencies.toml'
ALL: Final = '*'
#: What a hop may add (principle ``no-detour``): a translation, a policy, or one point of control.
ADDS: Final = frozenset({'translation', 'policy', 'control'})
KINDS: Final = frozenset({'normal', 'build', 'dev'})
#: When a Python package row's import runs: at module load (default), or only inside a function (heavy-optional).
LOADS: Final = frozenset({'eager', 'deferred'})
#: Tables a newer shape replaced, each with its door (refused by name, never read).
RETIRED: Final = {
    ('rust', 'crates'): 'the crate graph derives from crate paths: put the crate at rust/crates/<owner path> and '
    'declare its edges in [python.owners] / [python.siblings."<package>"]',
    ('python', 'native'): 'a native crate is the stage its path names (<package>_native.<owner>_<child> is '
    'rust/crates/<owner>/<child>); delete the table',
}
_RULE: Final = 'OWNER-DAG'
_SHAPE: Final = {
    'python': {'owners', 'siblings', 'importers', 'packages', 'stdlib'},
    'rust': {'external', 'std'},
}
_EDGE_KEYS: Final = frozenset({'name', 'adds'})
_DETAILS: Final = 'details: docs-src/dev/refusals.md#owner-dag (dev-lab)'


class DependenciesError(ValueError):
    """The repo's ``dependencies.toml`` is not the declared shape; the message names the row and the door."""


@dataclass(frozen=True, slots=True)
class Edge:
    """One permitted dependency, and what the hop adds when it only forwards (``None``: it forwards nothing)."""

    name: str
    adds: str | None = None


@dataclass(frozen=True, slots=True)
class Grant:
    """A package or std row: who may use it (repo paths for Python, crates for Rust; ``*`` = all) and why."""

    holders: tuple[str, ...]
    reason: str
    kind: str = 'normal'
    features: tuple[str, ...] = ()
    #: ``[rust.external]`` only: crates granted it as a ``[dev-dependencies]`` (tests) beyond *holders*.
    dev_holders: tuple[str, ...] = ()
    #: ``[python.*]`` only: ``deferred`` -- imported only inside a function (:data:`LOADS`).
    load: str = 'eager'


@dataclass(frozen=True, slots=True)
class Declared:
    """The whole declaration, one mapping per table; an absent table is empty."""

    owners: Mapping[str, tuple[Edge, ...]]
    siblings: Mapping[str, Mapping[str, tuple[Edge, ...]]]
    importers: Mapping[str, tuple[str, ...]]
    packages: Mapping[str, Grant]
    stdlib: Mapping[str, Grant]
    external: Mapping[str, Grant]
    std: Mapping[str, Grant]


def _refuse(why: str) -> NoReturn:
    msg = f'{_RULE}: {FILE}: {why} -- fix the row in {FILE} (each row says why)\n{_DETAILS}'
    raise DependenciesError(msg)


def declared(root: Path) -> bool:
    """Whether *root* opts in: it holds a root :data:`FILE`."""
    return (root / FILE).is_file()


def edge_to(edges: tuple[Edge, ...], name: str) -> Edge | None:
    """The edge of *edges* permitting *name* (its own row, else a ``*`` row), else ``None``."""
    return next((e for e in edges if e.name == name), None) or next((e for e in edges if e.name == ALL), None)


@dataclass(frozen=True, slots=True)
class Hop:
    """The declared edge a dependency from one package path to another crosses.

    *table* is ``python.owners``, ``python.siblings."<parent>"``, or ``child`` (a parent reaching into its own
    child, never permitted); *origin* -> *target* is the edge, *edges* the origin's row.
    """

    table: str
    origin: str
    target: str
    edges: tuple[Edge, ...]

    @property
    def permitted(self) -> bool:
        """Whether the declaration permits this hop."""
        return self.table != 'child' and edge_to(self.edges, self.target) is not None


def hop(decl: Declared, mine: tuple[str, ...], theirs: tuple[str, ...]) -> Hop | None:
    """The edge package path *mine* depending on *theirs* crosses; ``None`` when it crosses none (itself, an ancestor).

    Paths are owner paths (``("compile", "assemble")``), a Python package's or a crate's alike: ONE graph.
    """
    i = 0
    while i < min(len(mine), len(theirs)) and mine[i] == theirs[i]:
        i += 1
    if i == len(theirs):
        return None
    if i == len(mine):
        return Hop('child', '/'.join(mine), '/'.join(theirs[: i + 1]), ())
    if i == 0:
        return Hop('python.owners', mine[0], theirs[0], decl.owners.get(mine[0], ()))
    parent = '/'.join(mine[:i])
    return Hop(f'python.siblings."{parent}"', mine[i], theirs[i], decl.siblings.get(parent, {}).get(mine[i], ()))


def _edge(table: str, owner: str, item: object) -> Edge:
    """One list item of an edge row: a bare name, or ``{ name, adds }``."""
    if isinstance(item, str):
        return Edge(item)
    if not isinstance(item, dict):
        _refuse(f'[{table}] {owner}: {item!r} is neither a name nor {{ name, adds }}')
    if unknown := sorted(set(item) - _EDGE_KEYS):
        _refuse(f'[{table}] {owner}: unknown key(s) {unknown}; an edge is {{ name, adds }}')
    edge = Edge(str(item.get('name', '')), item.get('adds'))
    if edge.adds not in ADDS:
        _refuse(f'[{table}] {owner} -> {edge.name}: adds {edge.adds!r}, not one of {sorted(ADDS)}')
    return edge


def _edges(table: str, rows: Mapping[str, Any], *, closed: bool = True) -> dict[str, tuple[Edge, ...]]:
    """*rows* as edges, acyclic; *closed*: every target is itself a row (a sibling with no edges needs none)."""
    out: dict[str, tuple[Edge, ...]] = {}
    for owner, value in rows.items():
        if not isinstance(value, list):
            _refuse(f'[{table}] {owner} must be a list of names or {{ name, adds }} tables, not {value!r}')
        edges = [_edge(table, owner, item) for item in value]
        names = [e.name for e in edges]
        if owner in names:
            _refuse(f'[{table}] {owner} lists itself')
        if closed and (ghost := next((n for n in names if n != ALL and n not in rows), None)):
            _refuse(f'[{table}] {owner} lists {ghost!r}, which is no [{table}] row')
        if twice := next((n for n in names if names.count(n) > 1), None):
            _refuse(f'[{table}] {owner} lists {twice!r} twice')
        out[owner] = tuple(edges)
    graph = {k: {n for e in v for n in ((set(rows) - {k}) if e.name == ALL else {e.name})} for k, v in out.items()}
    if (found := cycle(graph)) is not None:
        _refuse(f'[{table}] forms a cycle: {" -> ".join(found)}; move what both need down to one owner')
    return out


def _grant(table: str, name: str, row: object, holder: str, allowed: set[str]) -> Grant:
    if not isinstance(row, dict):
        _refuse(f'[{table}] {name} must be {{ {holder} = [...], reason = "..." }}, not {row!r}')
    if unknown := sorted(set(row) - allowed):
        _refuse(f'[{table}] {name}: unknown key(s) {unknown}; allowed {sorted(allowed)}')
    spec: dict[str, object] = row  # a TOML table: string keys
    holders, reason = _names(spec.get(holder)), spec.get('reason')
    if holders is None or not all(holders):
        _refuse(f'[{table}] {name} {holder} must be a list of names ("*" = every one), not {spec.get(holder)!r}')
    if not isinstance(reason, str) or not reason.strip():
        _refuse(f'[{table}] {name} has no reason; every row says why')
    kind, features, load = spec.get('kind', 'normal'), _names(spec.get('features', [])), spec.get('load', 'eager')
    if not isinstance(load, str) or load not in LOADS:
        _refuse(f'[{table}] {name}: load {load!r}, not one of {sorted(LOADS)}')
    if not isinstance(kind, str) or kind not in KINDS:
        _refuse(f'[{table}] {name}: kind {kind!r}, not one of {sorted(KINDS)}')
    if features is None:
        _refuse(f'[{table}] {name} features must be a list of feature names, not {spec.get("features")!r}')
    dev = _dev_crates(table, name, spec.get('dev_crates', []))
    if dev and (kind != 'normal' or ALL in holders):
        _refuse(f'[{table}] {name}: dev_crates adds test-only crates to a normal row; this row already grants them')
    return Grant(tuple(h.strip('/') if h != ALL else h for h in holders), reason, kind, features, dev, load)


def _names(value: object) -> tuple[str, ...] | None:
    """*value* as a tuple of strings, else ``None`` (not a list, or an item that is no string)."""
    if not isinstance(value, list):
        return None
    items: list[object] = list(value)  # pyright: ignore[reportUnknownArgumentType]
    names = tuple(i for i in items if isinstance(i, str))
    return names if len(names) == len(items) else None


def _dev_crates(table: str, name: str, value: object) -> tuple[str, ...]:
    names: list[str] = []
    for item in value if isinstance(value, list) else [None]:  # pyright: ignore[reportUnknownVariableType]
        if not isinstance(item, str) or not item:
            _refuse(f'[{table}] {name} dev_crates must be a list of crate names ("*" = every one), not {value!r}')
        names.append(item)
    return tuple(names)


def _grants(table: str, rows: Mapping[str, Any], holder: str, *, rust_external: bool = False) -> dict[str, Grant]:
    allowed = {holder, 'reason', *(('kind', 'features', 'dev_crates') if rust_external else ())}
    if table.startswith('python.'):
        allowed.add('load')
    return {name: _grant(table, name, row, holder, allowed) for name, row in rows.items()}


def _under_owner(table: str, path: str, owners: Mapping[str, object]) -> str:
    if path.strip('/').split('/')[0] not in owners:
        _refuse(f'[{table}] {path!r} lies under no [python.owners] row; it is a path under the package')
    return path.strip('/')


def _siblings(raw: Mapping[str, Any], owners: Mapping[str, object]) -> dict[str, dict[str, tuple[Edge, ...]]]:
    out: dict[str, dict[str, tuple[Edge, ...]]] = {}
    for parent, rows in raw.items():
        if not isinstance(rows, dict):
            _refuse(f'[python.siblings] {parent!r} must be a table of child -> siblings, not {rows!r}')
        key = _under_owner('python.siblings', parent, owners)
        out[key] = _edges(f'python.siblings."{parent}"', rows, closed=False)
    return out


def _importers(raw: Mapping[str, Any], owners: Mapping[str, object]) -> dict[str, tuple[str, ...]]:
    out: dict[str, tuple[str, ...]] = {}
    for child, who in raw.items():
        key = _under_owner('python.importers', child, owners)
        if not isinstance(who, list) or not who or not all(isinstance(w, str) and w.strip('/') for w in who):
            _refuse(f'[python.importers] {child} must be a non-empty list of importer paths, not {who!r}')
        out[key] = tuple(w.strip('/') for w in who)
    return out


def _read(path: Path) -> dict[str, Any]:
    """The file's tables, each checked against the shape."""
    try:
        data = tomllib.loads(path.read_text(encoding='utf-8'))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        _refuse(f'does not parse: {exc}')
    for top, value in data.items():
        if top not in _SHAPE or not isinstance(value, dict):
            _refuse(f'unknown table [{top}]; the shape is {sorted(_SHAPE)}')
        for sub in value:
            if (door := RETIRED.get((top, sub))) is not None:
                _refuse(f'[{top}.{sub}] is retired: {door}')
            if sub not in _SHAPE[top] or not isinstance(value[sub], dict):
                _refuse(f'unknown table [{top}.{sub}]; [{top}] holds {sorted(_SHAPE[top])}')
    return data


def load(root: Path) -> Declared | None:
    """*root*'s declaration; ``None`` without :data:`FILE`. Raises :class:`DependenciesError` naming the row."""
    path = root / FILE
    if not path.is_file():
        return None
    data = _read(path)
    python, rust = data.get('python', {}), data.get('rust', {})
    owners = _edges('python.owners', python.get('owners', {}))
    return Declared(
        owners=owners,
        siblings=_siblings(python.get('siblings', {}), owners),
        importers=_importers(python.get('importers', {}), owners),
        packages=_grants('python.packages', python.get('packages', {}), 'owners'),
        stdlib=_grants('python.stdlib', python.get('stdlib', {}), 'owners'),
        external=_grants('rust.external', rust.get('external', {}), 'crates', rust_external=True),
        std=_grants('rust.std', rust.get('std', {}), 'crates'),
    )
