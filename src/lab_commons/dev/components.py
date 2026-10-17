"""A PRODUCT MOUNTS EACH ENGINE ONCE -- ``[tool.lab_commons.components]``, one table per engine.

LIBRARIES FLOAT, PRODUCTS COMPOSE. An engine (``<x>-lab``) depends on its peers by floating git
dependencies, so a library's sha does not fix its peers' source. A PRODUCT's sha must: one verdict per
sha means nothing otherwise. So a product mounts every engine as a git submodule under
``components/<name>`` -- the gitlink IS the pin -- and consumes it by path. lab-commons is never a
component: it stays a floating git dependency of everything, the product included.

THE ROW, declared once in the product's ``pyproject.toml``::

    [tool.lab_commons.components.numerics-lab]
    url = "https://<forge>/<owner>/numerics-lab.git"   # the engine's repository
    branch = "main"                                     # the branch a bump follows
    parts = ["base", "linux"]                           # the product's forge parts that verify a bump
    package = "numerics-lab"                            # optional: the Python distribution it provides
    crates = { numerics = "crates/numerics" }           # optional: Cargo crate -> its path in the engine

The mount path is DERIVED, never declared: ``components/<name>`` (:attr:`Component.path`). An unknown
or missing key is refused naming the row, so a typo is never read as a default.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Final

from lab_commons.hpc.declared import kit_tables

__all__ = ['MOUNT', 'Component', 'ComponentRefused', 'components_of']

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


def _row(name: str, raw: object) -> Component:
    if name == 'lab-commons':
        msg = 'lab-commons is never a component: it stays a floating git dependency of every repo'
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
