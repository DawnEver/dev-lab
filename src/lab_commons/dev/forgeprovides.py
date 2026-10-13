"""WHAT A HOST PROVIDES -- the capability side of a claim, declared once per machine and read onto its card.

A part is ``tests/<platform>`` or ``tests/<engine>`` (:mod:`lab_commons.hpc.platforms`). Which OS a host
runs is measured; what else it can produce is declared in THIS MACHINE's file
(:mod:`lab_commons.config`), one table per capability::

    [capabilities.jmag]
    seats = 4          # how many solver jobs this box runs at once -- its COMPUTE, not a licence count

    [capabilities.dev_checkout]

A part NEEDS its engine, or -- for an OS part -- every host capability whose ``on`` list names that OS
(:func:`needs`). A host lacking one is never offered the part (:func:`lacking`), and the queue names
the capability no live host provides (:func:`unserved`): BLOCKED, never red, never skipped. The
cluster's linux part needs nothing a bare per-sha tree lacks, so a host without ``dev_checkout`` keeps
claiming it. A host serves its own OS plus every engine it provides that the repository declares a
producer for (:func:`served_parts`); a cluster seat runs no engine part.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from lab_commons.dev.forgeschedule import NO_HOST
from lab_commons.hpc.platforms import PART_NAME, PLATFORMS, Table

__all__ = ['NO_PROVIDER', 'declared_parts', 'lacking', 'needs', 'provided', 'served_parts', 'unserved']

#: How a part no host may claim is labelled: ``no host provides <capability>``.
NO_PROVIDER: Final = f'{NO_HOST} provides'

_WHERE: Final = 'the machine file'


def provided(table: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """The machine file's ``[capabilities]``: ``{name: facts}``; a malformed row is refused by name."""
    out: dict[str, dict[str, Any]] = {}
    for name, facts in table.items():
        seats = facts.get('seats', 1) if isinstance(facts, dict) else None
        if not PART_NAME.match(name) or not isinstance(seats, int) or isinstance(seats, bool) or seats < 1:
            msg = f'{_WHERE}: [capabilities.{name}] must be a table named {PART_NAME.pattern}, seats a positive int'
            raise ValueError(msg)
        out[name] = dict(facts)
    return out


def needs(table: Table, part: str) -> tuple[str, ...]:
    """The capabilities a host must provide to produce *part* under *table*."""
    if part in table.engines:
        return (part,)
    return tuple(name for name in table.hosts if part in table.rows[name])


def lacking(needed: Sequence[str], provides: Mapping[str, Any]) -> str:
    """``''`` when *provides* covers *needed*, else ``no host provides <the first missing>``."""
    missing = [name for name in needed if name not in provides]
    return f'{NO_PROVIDER} {missing[0]}' if missing else ''


def served_parts(
    platform: str, provides: Mapping[str, Any], declared: Sequence[str], *, cluster: bool
) -> tuple[str, ...]:
    """*platform*, then every engine *declared* a producer for that *provides* covers; a cluster: *platform* alone."""
    if cluster:
        return (platform,)
    return (platform, *sorted(name for name in declared if name not in PLATFORMS and name in provides))


def unserved(part: str, needed: Sequence[str], hosts: Sequence[tuple[str, Mapping[str, Any]]]) -> str:
    """Why no live host of *hosts* (``(platform, provides)``) may claim *part*; ``''`` when one may."""
    serving = [provides for platform, provides in hosts if platform == part or part in provides]
    if not serving:
        return f'{NO_PROVIDER} {part}' if part not in PLATFORMS else f'{NO_HOST} serves {part}'
    if any(not lacking(needed, provides) for provides in serving):
        return ''
    return lacking([name for name in needed if not any(name in provides for provides in serving)] or needed, {})


def declared_parts(root: Path) -> tuple[str, ...]:
    """The parts *root* declares a producer for: ``parts.produce`` keys, plus linux with ``hpc``."""
    manifest = root / 'pyproject.toml'
    if not manifest.is_file():
        return ()
    declared = tomllib.loads(manifest.read_text(encoding='utf-8')).get('tool', {}).get('lab_commons', {})
    found = set(declared.get('parts', {}).get('produce', {}))
    if declared.get('hpc'):
        found.add('linux')
    return tuple(sorted(found))
