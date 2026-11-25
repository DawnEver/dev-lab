"""THE SERVERS EVERY WORKSTATION OPERATES ARE DERIVED: the machine file's ``[[server]]`` rows are a render.

:mod:`dev_lab.dev.opsserver` reads the servers from the machine file's ``[[server]]`` tables. Measured 2026-11-25:
those tables were hand-written into one workstation's file, outside the config source, so every other registered
workstation answered ``'forge-a1' is not a declared [[server]] ([])`` (user ruling 2026-11-25: every registered
workstation, not only one, uses the ops door).

Each fact now lives once in the config source. The family ``[dev] servers`` names the servers and their ADDRESS, the
one fact no host card holds (``servers = { <name> = { address = "<host>" } }``); everything else is the server's own
card, ``hosts/<name>.toml``: the login is its ``[ops.access] account``, the status card URL its ``[ops.status]``
``site`` and ``path`` (:class:`dev_lab.ops.caddy.Status`). :func:`rows` derives the ``[[server]]`` rows from both, and
:func:`dev_lab.dev.devhost.render` writes them into every registered development machine's file -- never an HPC
account's, never an unmanaged machine's. A hand-written ``[[server]]`` that differs is drift named with its door.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from dev_lab.ops.caddy import Status

__all__ = ['KEY', 'OPT_OUT', 'TABLE', 'defects', 'joins', 'rows']

#: The family ``[dev]`` key naming each server and its address.
KEY: Final = 'servers'
#: The host ``[dev]`` key a workstation that cannot be registered DECLARES its non-participation with (user ruling
#: 2026-11-25: a workstation that cannot be registered records that it does not join): ``false`` renders no
#: ``[[server]]`` row, not even a status card, and owes no ``client_keys``. Undeclared is ``true``: a workstation
#: without keys is then a bring-up wall.
OPT_OUT: Final = 'operates_servers'
#: The machine-file array of tables the rows render into (:func:`dev_lab.dev.opsserver.declared_servers`).
TABLE: Final = 'server'
#: Where a server's address is declared, spelled for a refusal.
_WHERE: Final = f'family.toml [dev] {KEY}'


def defects(servers: object, where: str = f'[dev].{KEY}') -> list[str]:
    """Why *servers* is not ``{<name> = {address = "<host>"}}``; ``[]`` when it is."""
    if not isinstance(servers, dict):
        return [f'{where} must be a table of <server> = {{ address = "<host>" }}']
    found: list[str] = []
    for name, entry in servers.items():
        address = entry.get('address') if isinstance(entry, dict) else None
        if not isinstance(entry, dict) or set(entry) != {'address'}:
            found.append(f'{where}.{name} must be {{ address = "<host>" }} only: the rest is hosts/{name}.toml')
        elif not isinstance(address, str) or not address or any(c in address for c in '@ \t/'):
            found.append(f'{where}.{name}.address must be a bare host (no "@", "/" or space), got {address!r}')
    return found


def joins(dev: Mapping[str, Any]) -> bool:
    """Whether the machine of merged ``[dev]`` *dev* operates the family servers (no declared :data:`OPT_OUT`)."""
    return dev.get(OPT_OUT, True) is not False


def rows(clone: Path, servers: Mapping[str, Any]) -> list[dict[str, str]]:
    """The ``[[server]]`` rows of *servers* (the family ``[dev] servers``), each derived from its host card in *clone*.

    Raises:
        ValueError: the declaration is malformed, or a server has no ``hosts/<name>.toml`` with ``[ops.access]``.

    """
    if found := defects(servers):
        raise ValueError('; '.join(found))
    out: list[dict[str, str]] = []
    for name in sorted(servers):
        card = clone / 'hosts' / f'{name}.toml'
        ops = tomllib.loads(card.read_text(encoding='utf-8')).get('ops', {}) if card.is_file() else {}
        account = ops.get('access', {}).get('account')
        if not account:
            msg = (f'{_WHERE} names {name!r}, but hosts/{name}.toml declares no [ops.access] account: declare the '
                   f'server card there, or drop {name!r} from {_WHERE}')  # fmt: skip
            raise ValueError(msg)
        row = {'name': name, 'target': f'{account}@{servers[name]["address"]}'}
        if status := ops.get('status'):
            card_status = Status(**{key: status[key] for key in ('file', 'site', 'path') if key in status})
            row['status'] = f'https://{card_status.site}{card_status.path}'
        out.append(row)
    return out
