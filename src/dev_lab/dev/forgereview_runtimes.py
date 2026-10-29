"""REVIEW-RUNTIMES: where THIS host keeps the interpreters a review command names, ``[runtimes.<name>]``.

The repo says WHAT runs (``{runtimes.<name>.<key>}`` in the command); the host says WHERE, in its machine file.
Not ``[capabilities]``: a capability is a resource a part needs and admission counts; a runtime is only a path
(user ruling 2026-10-28). A command still spelling ``{capabilities.<name>.<key>}`` is refused naming its
replacement, and so is a runtime the family retired outright.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Final

from lab_commons.config import section

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = [
    'HOST_FIELD',
    'RETIRED_FIELD',
    'RETIRED_RUNTIMES',
    'RUNTIMES_TABLE',
    'host_runtimes',
    'retired_field',
    'retired_table',
    'runtime_names',
]

#: The machine-file table a host declares WHERE its runtimes live in: ``[runtimes.<name>] <key> = "<path>"``.
RUNTIMES_TABLE: Final = 'runtimes'

#: A placeholder for a value THIS host declares: ``{runtimes.<name>.<key>}`` (``~`` expanded).
HOST_FIELD: Final = re.compile(r'\{runtimes\.(?P<name>[a-z][a-z0-9_]*)\.(?P<key>[a-z][a-z0-9_]*)\}')

#: The retired spelling of a host value, refused naming its ``{runtimes.<name>.<key>}`` replacement.
RETIRED_FIELD: Final = re.compile(r'\{capabilities\.(?P<name>[a-z][a-z0-9_]*)\.(?P<key>[a-z][a-z0-9_]*)\}')

#: Host values the family retired, each refused in a command naming what replaced it.
RETIRED_RUNTIMES: Final = {
    'sharp_review': 'ai-lab packages the method: drop it (the family command needs none)',
}


def retired_field(args: Iterable[str]) -> str | None:
    """The first retired host value in *args*, as ``<field> is retired: <remedy>``; None when every one is live."""
    for arg in args:
        for field in (*RETIRED_FIELD.finditer(arg), *HOST_FIELD.finditer(arg)):
            name, key = field['name'], field['key']
            why = RETIRED_RUNTIMES.get(name)
            if why is None and RETIRED_FIELD.fullmatch(field[0]):
                why = f'{{{RUNTIMES_TABLE}.{name}.{key}}} ([{RUNTIMES_TABLE}.{name}] {key} in the machine file)'
            if why is not None:
                return f'{field[0]} is retired: {why}'
    return None


def host_runtimes() -> dict[str, dict[str, Any]]:
    """The machine file's ``[runtimes]``: ``{name: {key: value}}``; a row that is not a table is refused."""
    table = section(RUNTIMES_TABLE)
    if bad := sorted(name for name, row in table.items() if not isinstance(row, dict)):
        msg = f'the machine file: [{RUNTIMES_TABLE}] {", ".join(bad)} must each be a table ([{RUNTIMES_TABLE}.<name>])'
        raise ValueError(msg)
    return {name: dict(row) for name, row in table.items()}


def runtime_names(command: Iterable[str]) -> frozenset[str]:
    """Every ``<name>`` *command* reads as ``{runtimes.<name>.<key>}``: the runtimes it needs a host to declare."""
    return frozenset(field['name'] for arg in command for field in HOST_FIELD.finditer(arg))


def retired_table(
    command: Iterable[str], runtimes: Mapping[str, Any], capabilities: Mapping[str, Any] | None = None
) -> str | None:
    """The remedy when a runtime *command* needs is still spelled ``[capabilities.<name>]`` in the machine file.

    *capabilities* defaults to this host's ``[capabilities]``; None when every needed runtime is not so spelled.
    """
    held = section('capabilities') if capabilities is None else capabilities
    if stale := sorted(n for n in runtime_names(command) if n not in runtimes and n in held):
        tables = ', '.join(f'[capabilities.{n}]' for n in stale)
        return f'the machine file still spells {tables}; run workstation deploy to move it to [{RUNTIMES_TABLE}]'
    return None
