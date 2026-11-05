"""REVIEW-RUNTIMES: where THIS host keeps the interpreters a review command names, ``[runtimes.<name>]``.

The repo says WHAT runs (``{runtimes.<name>.<key>}`` in the command); the host says WHERE, in its machine file.
Not ``[capabilities]``: a capability is a resource a part needs and admission counts; a runtime is only a path
(user ruling 2026-10-28). A command still spelling ``{capabilities.<name>.<key>}`` is refused naming its
replacement, and so is a runtime the family retired outright. A runtime the family DERIVES is never the machine
file's: ``[runtimes.ai_lab]`` is refused (:data:`DERIVED_RUNTIMES`), its interpreter built from the lock
(:mod:`dev_lab.dev.reviewruntime`).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Final

from lab_commons.config import section

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = [
    'DERIVED_RUNTIMES',
    'HOST_FIELD',
    'RETIRED_FIELD',
    'RETIRED_RUNTIMES',
    'RUNTIMES_TABLE',
    'host_runtimes',
    'retired_field',
    'retired_table',
    'runtime_names',
    'runtimes_with',
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


#: Runtimes no host declares, each with where it comes from instead: a machine file naming one is refused.
DERIVED_RUNTIMES: Final = {
    'ai_lab': (
        "built from the ai-lab commit the installed dev-lab's uv.lock pins, under <forge home>/runtimes "
        '(dev_lab.dev.reviewruntime, 2026-11-05: a hand-built path drifted from the pin); delete the table, or run '
        'workstation deploy'
    ),
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
    """The machine file's ``[runtimes]``: ``{name: {key: value}}``; a non-table row or a derived runtime is refused."""
    table = section(RUNTIMES_TABLE)
    if bad := sorted(name for name, row in table.items() if not isinstance(row, dict)):
        msg = f'the machine file: [{RUNTIMES_TABLE}] {", ".join(bad)} must each be a table ([{RUNTIMES_TABLE}.<name>])'
        raise ValueError(msg)
    if derived := sorted(set(table) & set(DERIVED_RUNTIMES)):
        msg = '; '.join(f'the machine file: [{RUNTIMES_TABLE}.{n}] is retired: {DERIVED_RUNTIMES[n]}' for n in derived)
        raise ValueError(msg)
    return {name: dict(row) for name, row in table.items()}


def runtimes_with(here: Mapping[str, Mapping[str, Any]], given: Iterable[str]) -> dict[str, dict[str, Any]]:
    """*here* (the machine file's ``[runtimes]``) with each ``NAME.KEY=VALUE`` of *given* over it."""
    out = {name: dict(row) for name, row in here.items()}
    for one in given:
        where, equals, value = one.partition('=')
        name, dot, key = where.partition('.')
        if not (equals and dot and name and key):
            msg = f'--runtime {one!r} is not NAME.KEY=VALUE'
            raise ValueError(msg)
        out.setdefault(name, {})[key] = value
    return out


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
