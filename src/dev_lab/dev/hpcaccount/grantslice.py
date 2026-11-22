"""The ``[hpc]`` slice of a machine file: the grants and login hosts it declares, read, rendered and cut out.

Split from :mod:`dev_lab.dev.hpcaccount.spec` (the ``[deploy]`` declaration): this reads the OTHER table
of the same file.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from lab_commons.hpc.grants import declared_grants

from dev_lab.dev._machinefile import dumps

__all__ = ['grant_refusal', 'grant_setup', 'granted_root', 'has_grant', 'login_hosts', 'render_grant', 'without_hpc']


def granted_root(hpc: Mapping[str, Any] | None, host: str = '') -> str:
    """The root an account's own grant declares: its cluster's ``[hpc.clusters.<cluster>] root``; ``''`` when none.

    THE ONE RESOLVER of an unstated ``[deploy] root``, over any ``[hpc]`` table: the slice deploy-fleet passes, the
    slice the account's machine file holds, the family's whole table. The grant is the one named *host*
    (``<cluster>-<user>``), else the table's only one; no grant, or several with no *host*, resolves nothing --
    another cluster's root is never taken. ``{user}`` in a family root is the grant's user.

    Measured 2026-11-20 (deploy), 2026-11-21 (configcheck), 2026-11-22 (drift, then the tick): each reader of a
    ``[deploy]`` that states no root refused "no root declared" until it resolved the root its own way.
    """
    table = hpc or {}
    rows = [row for row in table.get('grant', []) if not host or host == f'{row.get("cluster")}-{row.get("user")}']
    if len(rows) != 1:
        return ''
    cluster = table.get('clusters', {}).get(rows[0].get('cluster'), {})
    return str(cluster.get('root', '')).replace('{user}', str(rows[0].get('user', '')))


def render_grant(table: Mapping[str, Any]) -> str:
    """*table* (an ``[hpc]`` slice) as the machine-file text :mod:`lab_commons.hpc.grants` reads."""
    return '\n' + dumps({'hpc': dict(table)})


def _hpc_of(path: Path) -> dict[str, Any]:
    return (tomllib.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}).get('hpc', {})


def login_hosts(path: Path, table: Mapping[str, Any] | None) -> frozenset[str]:
    """Every login host a cluster declares -- in the passed ``[hpc]`` slice *table*, else the machine file at *path*."""
    hpc = table if table is not None else _hpc_of(path)
    return frozenset(host for cluster in hpc.get('clusters', {}).values() for host in cluster.get('hosts', ()))


def has_grant(path: Path, user: str) -> bool:
    """Whether the machine file at *path* already grants *user*."""
    return any(grant.get('user') == user for grant in _hpc_of(path).get('grant', []))


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
