"""An account machine file's ``[hpc]`` slice: its grants, login hosts and set-up, read and rewritten.

Split from :mod:`dev_lab.dev.hpcaccount.spec` at the module-size band (2026-11-21): ``spec`` holds the
``[deploy]`` declaration, this module the ``[hpc]`` one beside it in the same file.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from lab_commons.hpc.grants import declared_grants

from dev_lab.dev._machinefile import dumps
from dev_lab.dev.devdeclared import layered


def render_grant(table: Mapping[str, Any]) -> str:
    """*table* (an ``[hpc]`` slice) as the machine-file text :mod:`lab_commons.hpc.grants` reads."""
    return '\n' + dumps({'hpc': dict(table)})


def _hpc_of(path: Path) -> dict[str, Any]:
    """The ``[hpc]`` a reader of the machine file at *path* sees: its own over the family file's (grants stay there)."""
    return layered(tomllib.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}).get('hpc', {})


def login_hosts(path: Path, table: Mapping[str, Any] | None) -> frozenset[str]:
    """Every login host a cluster declares -- in the passed ``[hpc]`` slice *table*, else the machine file at *path*."""
    hpc = table if table is not None else _hpc_of(path)
    return frozenset(host for cluster in hpc.get('clusters', {}).values() for host in cluster.get('hosts', ()))


def grant_refusal(path: Path) -> str:
    """Why this kit cannot load the ``[hpc]`` slice of the machine file at *path* (``''``: it loads)."""
    try:
        declared_grants(_hpc_of(path))
    except ValueError as refused:
        return str(refused)
    return ''


#: A TOML table or array-of-tables header line; group 1 is the table's dotted name.
_HEADER: Final = re.compile(r'^\s*\[\[?\s*([^\]]+?)\s*\]\]?\s*(#.*)?$')


def without_hpc(text: str) -> str:
    """*text* without its ``[hpc]`` slice -- every ``[hpc]``, ``[hpc.*]`` and ``[[hpc.*]]`` table; the rest kept."""
    kept: list[str] = []
    inside = False
    for line in text.splitlines():
        if header := _HEADER.match(line):
            name = header.group(1)
            inside = name == 'hpc' or name.startswith('hpc.')
        if not inside:
            kept.append(line)
    return '\n'.join(kept).rstrip('\n') + '\n'


def grant_setup(path: Path, user: str) -> tuple[str, ...]:
    """The set-up of *user*'s cluster, as the machine file at *path* declares it -- the cluster's own environment."""
    hpc = _hpc_of(path)
    if not any(grant.get('user') == user for grant in hpc.get('grant', [])):
        return ()
    grants, _ = declared_grants(hpc)
    return next((grant.setup for grant in grants if grant.user == user), ())
