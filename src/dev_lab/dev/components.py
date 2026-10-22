"""A PRODUCT MOUNTS EACH ENGINE ONCE -- ``[tool.lab_commons.components]``, one table per engine.

LIBRARIES FLOAT, PRODUCTS COMPOSE. An engine (``<x>-lab``) depends on its peers by floating git
dependencies, so a library's sha does not fix its peers' source. A PRODUCT's sha must: one verdict per
sha means nothing otherwise. So a product mounts every engine as a git submodule under
``components/<name>`` -- the gitlink IS the pin -- and consumes it by path. lab-commons (the runtime)
and dev-lab (the development system) are never components: each stays a floating git dependency of
everything, the product included.

THE ROW, declared once in the product's ``pyproject.toml``::

    [tool.lab_commons.components.numerics-lab]
    url = "https://<forge>/<owner>/numerics-lab.git"   # the engine's repository
    branch = "main"                                     # the branch a bump follows
    parts = ["base", "linux"]                           # the product's forge parts that verify a bump
    package = "numerics-lab"                            # optional: the Python distribution it provides
    crates = { numerics = "crates/numerics" }           # optional: Cargo crate -> its path in the engine

The mount path is DERIVED, never declared: ``components/<name>`` (:attr:`Component.path`). An unknown
or missing key is refused naming the row, so a typo is never read as a default.

DERIVED, AND CHECKED (:func:`drift`). Three files restate the table and are checked against it rather
than trusted: ``.gitmodules`` (an entry per component: path, url, branch -- :func:`gitmodules_text`
derives it), ``[tool.uv.sources]`` (``<package> = { path = "components/<name>" }``, which overrides the
engine's floating git dependency so the environment holds ONE copy of it) and every Cargo path
dependency into ``components/`` (a declared crate at its declared path). The index must hold a gitlink
at each mount. Only what lies under ``components/`` is policed; a drift names the file and the fix.
``python -m dev_lab.dev.components`` prints the drift and exits 1 on any.
"""

from __future__ import annotations

import argparse
import posixpath
import re
import shutil
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Final

import lab_commons.launch as _door
from lab_commons.hpc.declared import kit_tables
from lab_commons.log import emit

__all__ = [
    'MOUNT',
    'Component',
    'ComponentRefused',
    'components_of',
    'drift',
    'drift_at',
    'gitmodules_text',
    'main',
    'submodules',
]

_GIT: Final = shutil.which('git') or 'git'

#: Where every component is mounted, relative to the product's root.
MOUNT: Final = 'components'

#: An engine's name (R7): ``<x>-lab``.
_ENGINE: Final = re.compile(r'[a-z][a-z0-9]*(-[a-z0-9]+)*-lab')

_REQUIRED: Final = frozenset({'url', 'branch', 'parts'})
_OPTIONAL: Final = frozenset({'package', 'crates'})


class ComponentRefused(ValueError):
    """A ``[tool.lab_commons.components]`` row the schema does not admit; the message names the row and key."""


@dataclass(frozen=True)
class Component:
    """One engine the product mounts: where it comes from, what follows it, and what it provides."""

    name: str
    url: str
    branch: str
    parts: tuple[str, ...]
    package: str = ''
    crates: Mapping[str, str] = field(default_factory=dict)

    @property
    def path(self) -> str:
        """The mount, relative to the product root: ``components/<name>``."""
        return f'{MOUNT}/{self.name}'


def components_of(pyproject: str) -> tuple[Component, ...]:
    """Every component *pyproject* declares, in declaration order; ``()`` when it declares none.

    Raises:
        ComponentRefused: a row is malformed; the message names the row and the key.

    """
    table = kit_tables(pyproject).get('components', {})
    if not isinstance(table, dict):
        msg = '[tool.lab_commons.components] is one table per engine: [tool.lab_commons.components.<name>]'
        raise ComponentRefused(msg)
    return tuple(_row(name, raw) for name, raw in table.items())

#: The family kits: the runtime (lab-commons) and the development system (dev-lab); `dev-lab` matches <x>-lab.
_NEVER_COMPONENTS: Final = frozenset({'lab-commons', 'dev-lab'})


def _row(name: str, raw: object) -> Component:
    if name in _NEVER_COMPONENTS:
        msg = f'{name} is never a component: it stays a floating git dependency of every repo'
        raise ComponentRefused(msg)
    if not _ENGINE.fullmatch(name):
        msg = f'component {name!r}: an engine is named <x>-lab'
        raise ComponentRefused(msg)
    if not isinstance(raw, dict):
        msg = f'component {name}: one table of keys {sorted(_REQUIRED | _OPTIONAL)}'
        raise ComponentRefused(msg)
    if missing := sorted(_REQUIRED - set(raw)):
        msg = f'component {name}: missing {missing}'
        raise ComponentRefused(msg)
    if unknown := sorted(set(raw) - _REQUIRED - _OPTIONAL):
        derived = ' (the mount path is derived: components/<name>)' if 'path' in unknown else ''
        msg = f'component {name}: unknown {unknown}{derived}'
        raise ComponentRefused(msg)
    return Component(
        name=name,
        url=_text(name, raw, 'url'),
        branch=_text(name, raw, 'branch'),
        parts=_parts(name, raw['parts']),
        package=_text(name, raw, 'package') if 'package' in raw else '',
        crates=_crates(name, raw.get('crates', {})),
    )


def _text(name: str, raw: Mapping[str, Any], key: str) -> str:
    value = raw[key]
    if not isinstance(value, str) or not value.strip():
        msg = f'component {name}: {key} is a non-empty string, not {value!r}'
        raise ComponentRefused(msg)
    return value


def _parts(name: str, value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(part, str) and part for part in value):
        msg = f'component {name}: parts is a list of part names, not {value!r}'
        raise ComponentRefused(msg)
    if not value:
        msg = f'component {name}: parts names at least one part; a bump nothing verifies is never green'
        raise ComponentRefused(msg)
    return tuple(value)


def _crates(name: str, value: object) -> dict[str, str]:
    if not isinstance(value, dict) or not all(isinstance(v, str) for v in value.values()):
        msg = f'component {name}: crates maps a crate name to its path in the engine, not {value!r}'
        raise ComponentRefused(msg)
    for crate, path in value.items():
        inner = PurePosixPath(path)
        if not path or inner.is_absolute() or '..' in inner.parts:
            msg = f'component {name}: crate {crate} path {path!r} must be inside the engine'
            raise ComponentRefused(msg)
    return dict(value)


#: The Cargo tables whose entries may carry a ``path`` (``target.<cfg>.<table>`` is walked too).
_CARGO_TABLES: Final = ('dependencies', 'dev-dependencies', 'build-dependencies')

_SECTION: Final = re.compile(r'\s*\[\s*submodule\s+"(?P<name>[^"]+)"\s*\]\s*$')
_SETTING: Final = re.compile(r'\s*(?P<key>[A-Za-z][\w-]*)\s*=\s*(?P<value>.*?)\s*$')


def gitmodules_text(components: tuple[Component, ...]) -> str:
    """The ``.gitmodules`` the table derives: one entry per component, named by its mount path."""
    return ''.join(
        f'[submodule "{row.path}"]\n\tpath = {row.path}\n\turl = {row.url}\n\tbranch = {row.branch}\n'
        for row in components
    )


def submodules(text: str) -> dict[str, dict[str, str]]:
    """``{path: {key: value}}`` of a ``.gitmodules`` *text*; an entry without a path is keyed by its name."""
    found: dict[str, dict[str, str]] = {}
    current: dict[str, str] = {}
    for line in text.splitlines():
        if heading := _SECTION.match(line):
            current = found.setdefault(heading['name'], {})
        elif (setting := _SETTING.match(line)) and found:
            current[setting['key'].lower()] = setting['value']
    return {entry.get('path', name): entry for name, entry in found.items()}


def drift(
    components: tuple[Component, ...],
    *,
    gitmodules: str,
    pyproject: str,
    cargo: Mapping[str, str],
    gitlinks: frozenset[str],
) -> tuple[str, ...]:
    """Every way the product's mounts disagree with its table, each naming the file and the fix; ``()`` agrees.

    *cargo* maps each ``Cargo.toml``'s repo-relative path to its text; *gitlinks* is every path the
    index holds as a submodule commit. Only what lies under ``components/`` is policed: a product may
    hold other submodules and other path dependencies.
    """
    declared = {row.path for row in components}
    return (
        *_gitmodules_drift(components, submodules(gitmodules)),
        *(
            f'{row.path} is declared and the index holds no gitlink there'
            for row in components
            if row.path not in gitlinks
        ),
        *(f'{path} is a gitlink no component declares' for path in sorted(gitlinks - declared) if _mounted(path)),
        *_uv_drift(components, pyproject),
        *_cargo_drift(components, cargo),
    )


def _mounted(path: str) -> bool:
    return PurePosixPath(path).parts[:1] == (MOUNT,)


def _gitmodules_drift(components: tuple[Component, ...], entries: Mapping[str, Mapping[str, str]]) -> list[str]:
    problems = []
    for row in components:
        entry = entries.get(row.path)
        wanted = {'url': row.url, 'branch': row.branch}
        if entry is None:
            problems.append(f'.gitmodules has no entry at {row.path}; derived: {gitmodules_text((row,))!r}')
        elif {key: entry.get(key, '') for key in wanted} != wanted:
            problems.append(f'.gitmodules {row.path} says {dict(entry)}; the table says {wanted}')
    declared = {row.path for row in components}
    stray = sorted(path for path in entries if _mounted(path) and path not in declared)
    return problems + [f'.gitmodules mounts {path}, which no component declares' for path in stray]


def _uv_drift(components: tuple[Component, ...], pyproject: str) -> list[str]:
    sources = tomllib.loads(pyproject).get('tool', {}).get('uv', {}).get('sources', {})
    problems = [
        f'[tool.uv.sources] {row.package} is {sources.get(row.package)!r}; the table derives {{ path = "{row.path}" }}'
        for row in components
        if row.package and [_normal(entry.get('path')) for entry in _entries(sources.get(row.package))] != [row.path]
    ]
    provides = {row.path: row.package for row in components}
    for package, value in sorted(sources.items()):
        for entry in _entries(value):
            path = _normal(entry.get('path'))
            if _mounted(path) and provides.get(path) != package:
                problems.append(
                    f'[tool.uv.sources] {package} points into {path}; no component declares it provides that'
                )
    return problems


def _entries(value: object) -> list[Mapping[str, Any]]:
    listed = value if isinstance(value, list) else [value]
    return [entry for entry in listed if isinstance(entry, dict)]


def _normal(path: object) -> str:
    return posixpath.normpath(path) if isinstance(path, str) and path else ''


def _cargo_drift(components: tuple[Component, ...], cargo: Mapping[str, str]) -> list[str]:
    wanted = {f'{row.path}/{inner}': (row.name, crate) for row in components for crate, inner in row.crates.items()}
    used: set[str] = set()
    problems = []
    for manifest, text in sorted(cargo.items()):
        for crate, entry in _path_dependencies(tomllib.loads(text)):
            target = _normal(posixpath.join(posixpath.dirname(manifest), str(entry['path'])))
            if not _mounted(target):
                continue
            if wanted.get(target, ('', ''))[1] != str(entry.get('package', crate)):
                problems.append(
                    f'{manifest}: {crate} = {{ path = "{entry["path"]}" }} is no crate a component declares'
                )
            else:
                used.add(target)
    unused = sorted(set(wanted) - used)
    return problems + [
        f'component {wanted[t][0]} declares crate {wanted[t][1]} at {t}; no Cargo.toml uses it' for t in unused
    ]


def _path_dependencies(manifest: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    tables = [manifest.get(name, {}) for name in _CARGO_TABLES]
    tables.append(manifest.get('workspace', {}).get('dependencies', {}))
    for target in manifest.get('target', {}).values():
        tables += [target.get(name, {}) for name in _CARGO_TABLES]
    return [
        (crate, entry)
        for table in tables
        for crate, entry in table.items()
        if isinstance(entry, dict) and 'path' in entry
    ]


def drift_at(root: Path) -> tuple[str, ...]:
    """:func:`drift` over the checkout at *root*: its pyproject, ``.gitmodules``, Cargo manifests and index."""
    pyproject = (root / 'pyproject.toml').read_text(encoding='utf-8')
    gitmodules = root / '.gitmodules'
    staged = [line.partition('\t') for line in _git(root, 'ls-files', '--stage', '-z').split('\0') if '\t' in line]
    gitlinks = frozenset(path for meta, _, path in staged if meta.startswith('160000 '))
    manifests = [path for _, _, path in staged if posixpath.basename(path) == 'Cargo.toml' and not _mounted(path)]
    return drift(
        components_of(pyproject),
        gitmodules=gitmodules.read_text(encoding='utf-8') if gitmodules.is_file() else '',
        pyproject=pyproject,
        cargo={path: (root / path).read_text(encoding='utf-8') for path in manifests},
        gitlinks=gitlinks,
    )


def _git(root: Path, *args: str) -> str:
    argv = [_GIT, '-C', str(root), *args]
    return _door.run(argv, capture_output=True, text=True, encoding='utf-8', errors='replace', check=True).stdout


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m dev_lab.dev.components [--root R]``: each drift printed; 0 when the mounts agree, else 1."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.components', description=main.__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd(), help='the product checkout (default: here)')
    args = parser.parse_args(argv)
    problems = drift_at(args.root)
    for problem in problems:
        emit(f'components: {problem}', err=True)
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
