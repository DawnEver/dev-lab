"""OWNER-DAG over Rust: each crate's Cargo dependencies and std uses against ``[rust.*]`` of ``dependencies.toml``.

A crate is every tracked ``Cargo.toml`` with a ``[package]`` (its name with ``-`` read as ``_``), wherever it lies.
Cargo is authoritative for crate edges -- a ``use`` of a crate the manifest does not declare does not compile -- so
the graph is read from ``[dependencies]`` and ``[build-dependencies]`` (also under ``[target.<cfg>]``), a renamed
dependency by its ``package``, an inherited one (``workspace = true``) with the workspace's features. Refused, by
manifest and name:

* a workspace crate dependency its ``[rust.crates]`` row does not list (``[dev-dependencies]`` are tests: free);
* an external crate no ``[rust.external]`` row names, one the row does not allow in this crate, one of another
  kind (a ``normal`` row grants ``[dependencies]`` and ``[dev-dependencies]``, its ``dev_crates`` only the
  latter; ``build`` and ``dev`` only their own), or one missing a feature the row requires;
* in the crate's ``src/`` (``#[cfg(test)]`` items, ``tests/``, ``benches/`` and ``build.rs`` are not judged), a
  restricted ``[rust.std]`` path -- ``use`` trees expanded, ``core``/``alloc`` read as ``std``, the longest row
  wins -- or token (``unsafe``, ``extern "C"``) outside the row's crates;
* a crate with no ``[rust.crates]`` row, and a row or holder naming a crate neither in the tree nor declared by
  a layout.toml ``<crate>/Cargo.toml`` row (a crate not created yet is allowed).

Source reading is :mod:`dev_lab.dev.rustsource`'s.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, Final

from dev_lab.dev import rustsource
from dev_lab.dev._layout_table import allowed
from dev_lab.dev.deptable import ALL, Declared, Grant, edge_to

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping
    from pathlib import Path

    from dev_lab.dev._layout_table import Layout

__all__ = ['Crate', 'crates', 'problems']

_MANIFEST: Final = 'Cargo.toml'
_SECTIONS: Final = {'dependencies': 'normal', 'build-dependencies': 'build', 'dev-dependencies': 'dev'}
#: Which dependency kinds a ``[rust.external]`` row of each kind grants.
_GRANTS: Final = {'normal': {'normal', 'dev'}, 'build': {'build'}, 'dev': {'dev'}}


@dataclass(frozen=True, slots=True)
class Crate:
    """A crate in the tree: its name (``_`` for ``-``), its repo-relative directory, its parsed manifest."""

    name: str
    directory: str
    manifest: Mapping[str, Any]

    @property
    def manifest_path(self) -> str:
        """The repo-relative ``Cargo.toml``."""
        return f'{self.directory}/{_MANIFEST}' if self.directory else _MANIFEST


def _norm(name: str) -> str:
    return name.replace('-', '_')


def _manifests(root: Path, files: Iterable[str]) -> Iterator[tuple[str, dict[str, Any] | str]]:
    for rel in files:
        if PurePosixPath(rel).name == _MANIFEST:
            try:
                yield rel, tomllib.loads((root / rel).read_text(encoding='utf-8'))
            except (OSError, ValueError) as exc:
                yield rel, f'{rel}: does not parse: {exc}'


def crates(root: Path, files: Iterable[str]) -> dict[str, Crate]:
    """Every crate the tracked *files* hold, by name."""
    out: dict[str, Crate] = {}
    for rel, data in _manifests(root, files):
        package = data.get('package') if isinstance(data, dict) else None
        if isinstance(package, dict) and isinstance(package.get('name'), str):
            directory = str(PurePosixPath(rel).parent).removeprefix('.')
            out[_norm(package['name'])] = Crate(_norm(package['name']), directory, data)
    return out


def _dependencies(manifest: Mapping[str, Any]) -> Iterator[tuple[str, str, Any]]:
    tables = [manifest, *(t for t in manifest.get('target', {}).values() if isinstance(t, dict))]
    for table in tables:
        for section, kind in _SECTIONS.items():
            for key, spec in table.get(section, {}).items():
                yield kind, key, spec


def _real_name(key: str, spec: object, workspace: Mapping[str, Any]) -> str:
    if isinstance(spec, dict) and spec.get('workspace') is True and isinstance(workspace.get(key), dict):
        spec = workspace[key]
    return _norm(spec['package'] if isinstance(spec, dict) and isinstance(spec.get('package'), str) else key)


def _features(key: str, spec: object, workspace: Mapping[str, Any]) -> set[str]:
    own = set(spec.get('features', [])) if isinstance(spec, dict) else set()
    inherited = workspace.get(key) if isinstance(spec, dict) and spec.get('workspace') is True else None
    return own | (set(inherited.get('features', [])) if isinstance(inherited, dict) else set())


def _allowed(grant: Grant, crate: str) -> bool:
    return ALL in grant.holders or crate in grant.holders


def _only(grant: Grant) -> str:
    return ', '.join(grant.holders) or 'nowhere'


def _external(crate: Crate, kind: str, real: str, have: set[str], decl: Declared) -> str | None:
    grant = decl.external.get(real)
    head = f'{crate.manifest_path}: crate {crate.name} depends on {real} ({kind})'
    if grant is None:
        return f'{head}, which no [rust.external] row names'
    if kind not in _GRANTS[grant.kind]:
        return f'{head}, but [rust.external] {real} is kind {grant.kind}'
    tests_only = kind == 'dev' and (ALL in grant.dev_holders or crate.name in grant.dev_holders)
    if not tests_only and not _allowed(grant, crate.name):
        return f'{head}, but [rust.external] {real} allows it only in {_only(grant)}'
    if missing := sorted(set(grant.features) - have):
        return f'{head} without the required feature(s) {missing} ({grant.reason})'
    return None


def _under(path: str, key: str) -> bool:
    if path.endswith('::*'):
        return key.startswith(path[:-1]) or path[:-3] == key or path[:-3].startswith(key + '::')
    return path == key or path.startswith(key + '::')


def _std_problems(root: Path, decl: Declared, crate: Crate, files: Iterable[str]) -> list[str]:
    paths = [k for k in decl.std if '::' in k]
    tokens = [k for k in decl.std if '::' not in k]
    prefix = f'{crate.directory}/src/' if crate.directory else 'src/'
    out: list[str] = []
    for rel in sorted(f for f in files if f.startswith(prefix) and f.endswith('.rs')):
        code = rustsource.code_of((root / rel).read_text(encoding='utf-8'))
        hits: dict[str, set[str]] = {}
        for used in rustsource.paths_used(code):
            keys = [k for k in paths if _under(used, k)]
            for key in keys if used.endswith('::*') else sorted(keys, key=len)[-1:]:
                hits.setdefault(key, set()).add(used)
        hits.update({k: {k} for k in tokens if rustsource.has_token(code, k)})
        out += [
            f'{rel}: crate {crate.name} uses {", ".join(sorted(used))}, but [rust.std] {key} allows it only in '
            f'{_only(decl.std[key])}'
            for key, used in sorted(hits.items())
            if not _allowed(decl.std[key], crate.name)
        ]
    return out


def _stale_rows(decl: Declared, found: Mapping[str, Crate], layout: Layout | None) -> list[str]:
    """Rows naming a crate neither in the tree nor declared by a layout.toml ``<crate>/Cargo.toml`` row."""
    planned = {
        pattern.rpartition('/')[2]
        for pattern, allows in (layout.rows.items() if layout is not None else ())
        if allowed(_MANIFEST, allows)
    }
    nowhere = 'which is no crate in the tree and which no layout.toml <crate>/Cargo.toml row declares'
    named = [('crates', name, name) for name in decl.crates]
    named += [
        (t, k, h)
        for t, rows in (('external', decl.external), ('std', decl.std))
        for k, g in rows.items()
        for h in g.holders
    ]
    return [
        f'dependencies.toml [rust.{table}] {key} names crate {name}, {nowhere}'
        for table, key, name in named
        if name != ALL and name not in found and name not in planned
    ]


def problems(root: Path, decl: Declared, files: Iterable[str], *, layout: Layout | None = None) -> list[str]:
    """Every Rust refusal over the repo-relative *files*; nothing when no ``[rust.*]`` table is declared.

    A row may name a crate not created yet when *layout* (the repo's layout.toml) declares its ``Cargo.toml``.
    """
    if not (decl.crates or decl.external or decl.std):
        return []
    files = sorted(files)
    out = [m for _, m in _manifests(root, files) if isinstance(m, str)]
    found = crates(root, files)
    workspace: dict[str, Any] = {}
    for _, data in _manifests(root, files):
        if isinstance(data, dict):
            workspace.update(data.get('workspace', {}).get('dependencies', {}))
    out += [
        f'{c.manifest_path}: crate {c.name} has no [rust.crates] row'
        for c in found.values()
        if c.name not in decl.crates
    ]
    out += _stale_rows(decl, found, layout)
    for crate in sorted(found.values(), key=lambda c: c.name):
        for kind, key, spec in _dependencies(crate.manifest):
            real = _real_name(key, spec, workspace)
            if real not in found:
                out += [why] if (why := _external(crate, kind, real, _features(key, spec, workspace), decl)) else []
            elif kind != 'dev' and crate.name in decl.crates and edge_to(decl.crates[crate.name], real) is None:
                out.append(
                    f'{crate.manifest_path}: crate {crate.name} depends on {real}, but [rust.crates] {crate.name} '
                    'does not list it'
                )
        if decl.std:
            out += _std_problems(root, decl, crate, files)
    return list(dict.fromkeys(out))
