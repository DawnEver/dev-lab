"""The REFS a part is produced under: ``[tool.dev_lab.parts.refs.<resource>]``, per resource and scope.

A scarce resource (a vendor licence, a lab box) may limit the refs its parts are produced for: under each
resource the part's need-set holds, a scope key lists the fnmatch patterns a ref must match, e.g.::

    [tool.dev_lab.parts.refs.jmag]
    full = ["integrate/main", "main"]

:mod:`dev_lab.dev.forgeschedule` reads it; the rest of a part's declaration is :mod:`dev_lab.dev.platformparts`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dev_lab.dev.partrows import needs_of_row
from dev_lab.dev.platformparts import declared_strings, declared_tables

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['part_refs']

_EXAMPLE = '["integrate/main", "main"]'


def part_refs(root: Path, platform: str, scope: str) -> dict[str, tuple[str, ...]]:
    """The ref filters (fnmatch patterns) *platform*'s part at *scope* is produced under, keyed by the resource.

    One per resource the part needs that declares a filter at *scope*; empty when none does.

    Raises:
        UndeclaredPart: a declaration is present and not a non-empty list of strings.

    """
    declared = declared_tables(root, name='parts').get('refs', {})
    filters: dict[str, tuple[str, ...]] = {}
    for resource in sorted(needs_of_row(platform) & declared.keys()):
        if (patterns := declared[resource].get(scope)) is not None:
            table = f'tool.dev_lab.parts.refs.{resource}'
            filters[resource] = tuple(declared_strings(patterns, table, scope, _EXAMPLE, required=True))
    return filters
