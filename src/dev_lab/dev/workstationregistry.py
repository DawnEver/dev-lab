"""WHICH WORKSTATION SERVES THE FORGE: the synced registry's ``roles``, read for this machine.

ONE PLACE says which workstation serves the forge (user ruling 2026-10-22): the registry named by the
machine file's ``[workstation] registry = "<hosts.json>"``. :mod:`dev_lab.dev.workstation` refuses to deploy
or serve without the ``forge`` role, and :mod:`dev_lab.dev.automode` reads the same table for its fleet facts.
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Final

from lab_commons.config import config_path, section

__all__ = ['FORGE_ROLE', 'REGISTRY_TABLE', 'NoRegistry', 'forge_refusal', 'this_computer']

#: The machine-file table naming the synced workstation registry: ``[workstation] registry = "<hosts.json>"``.
REGISTRY_TABLE: Final = 'workstation'
#: The registry role that makes a workstation a ``forge serve`` host (user ruling 2026-10-22: one host alone).
FORGE_ROLE: Final = 'forge'


class NoRegistry(ValueError):
    """No workstation registry is declared here, so whether this machine serves the forge is undeclared."""


def this_computer() -> str:
    """The OS name of this machine: ``COMPUTERNAME``, else the host name."""
    return os.environ.get('COMPUTERNAME') or socket.gethostname()


def forge_refusal(computer: str) -> str | None:
    """``None`` when the registry gives *computer* the ``forge`` role; else why it may not serve.

    This machine's entry is the one whose ``computer`` (the OS name, ``COMPUTERNAME``) equals *computer*,
    case-insensitively, else the one whose ``name`` does -- ``computer`` first because it is read off the
    machine, ``name`` a label. No ``[workstation] registry`` raises :class:`NoRegistry`: a workstation never
    serves by omission.
    """
    declared = section(REGISTRY_TABLE).get('registry')
    if not isinstance(declared, str) or not declared:
        msg = (
            f'no [{REGISTRY_TABLE}] registry in {config_path()}: declare the synced hosts.json there; '
            f'only a host whose entry carries role "{FORGE_ROLE}" serves the forge'
        )
        raise NoRegistry(msg)
    registry = Path(declared).expanduser()
    try:
        hosts = json.loads(registry.read_text(encoding='utf-8-sig'))['hosts']
    except (OSError, ValueError, KeyError, TypeError) as bad:
        return f'registry {registry} unreadable ({bad}); not serving until it reads'
    key = computer.casefold()
    entry = next((h for h in hosts if str(h.get('computer', '')).casefold() == key), None) or next(
        (h for h in hosts if str(h.get('name', '')).casefold() == key), None
    )
    if entry is None:
        return f'no entry for computer {computer!r} in {registry}; add one with role "{FORGE_ROLE}" to serve'
    roles = list(entry.get('roles') or [])
    if FORGE_ROLE in roles:
        return None
    return f'{registry} roles of {entry.get("name")}: {roles}; add "{FORGE_ROLE}" to serve'
