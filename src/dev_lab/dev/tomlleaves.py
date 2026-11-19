"""The leaf keys of a parsed TOML table by path, and their ``[table].key`` spelling.

Split from :mod:`dev_lab.dev.devhost`, which compares a machine file's leaves with each layer's to name the owner.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = ['dotted', 'leaves']


def leaves(table: Mapping[str, Any], prefix: tuple[str, ...] = ()) -> dict[tuple[str, ...], Any]:
    """Every leaf key of *table* by its path; a list, a scalar or an empty table is a leaf."""
    out: dict[tuple[str, ...], Any] = {}
    for key, value in table.items():
        if isinstance(value, Mapping) and value:
            out.update(leaves(value, (*prefix, key)))
        else:
            out[(*prefix, key)] = value
    return out


def dotted(path: tuple[str, ...]) -> str:
    """*path* spelled ``[table].key.subkey``."""
    return f'[{path[0]}]' + ''.join(f'.{part}' for part in path[1:])
