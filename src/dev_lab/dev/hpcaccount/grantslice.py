"""The ``[hpc]`` slice of a machine file: the grants and login hosts it declares, read, rendered and cut out.

Split from :mod:`dev_lab.dev.hpcaccount.spec` (the ``[deploy]`` declaration): this reads the OTHER table
of the same file.

ONE READER (:func:`machine_table`): an account's machine file is a render naming its ``[family] source``, and the
grant, its cluster and the cluster's root live in that family file alone. Every read here goes through the layered
view (:func:`dev_lab.dev.devdeclared.layered`), so no family leaf is written back into the machine file -- a leaf
both hold is refused by ``lab_commons.config.section``, which every tick calls (probed 2026-11-22).
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from lab_commons.hpc.grants import declared_grants

from dev_lab.dev._machinefile import dumps
from dev_lab.dev.devdeclared import OWN_TABLE, layered

__all__ = [
    'grant_refusal',
    'grant_setup',
    'granted_root',
    'login_hosts',
    'machine_table',
    'own_grant',
    'render_grant',
    'without_hpc',
]


def machine_table(path: Path) -> dict[str, Any]:
    """The machine file at *path* over the family file it names: the whole machine, as every reader here sees it."""
    return layered(tomllib.loads(path.read_text(encoding='utf-8'))) if path.is_file() else {}


def own_grant(hpc: Mapping[str, Any] | None, host: str = '') -> Mapping[str, Any] | None:
    """The ``[[hpc.grant]]`` row of the account named *host* (``<cluster>-<user>``), else the table's only one.

    ``None`` for no such row, or several with no *host*: another account's grant is never taken.
    """
    rows = [r for r in (hpc or {}).get('grant', []) if not host or host == f'{r.get("cluster")}-{r.get("user")}']
    return rows[0] if len(rows) == 1 else None


def granted_root(hpc: Mapping[str, Any] | None, host: str = '') -> str:
    """The root an account's own grant declares: its cluster's ``[hpc.clusters.<cluster>] root``; ``''`` when none.

    THE ONE RESOLVER of an unstated ``[deploy] root``, over any ``[hpc]`` table: the slice deploy-fleet passes, the
    family's whole table under a render. The grant is :func:`own_grant`'s; none resolves nothing -- another
    cluster's root is never taken. ``{user}`` in a family root is the grant's user.

    Measured 2026-11-20 (deploy), 2026-11-21 (configcheck), 2026-11-22 (drift, then the tick): each reader of a
    ``[deploy]`` that states no root refused "no root declared" until it resolved the root its own way.
    """
    row = own_grant(hpc, host)
    if row is None:
        return ''
    cluster = (hpc or {}).get('clusters', {}).get(row.get('cluster'), {})
    return str(cluster.get('root', '')).replace('{user}', str(row.get('user', '')))


def render_grant(table: Mapping[str, Any]) -> str:
    """*table* (an ``[hpc]`` slice) as the machine-file text :mod:`lab_commons.hpc.grants` reads."""
    return '\n' + dumps({'hpc': dict(table)})


def _own(path: Path, user: str = '') -> tuple[dict[str, Any], Mapping[str, Any] | None]:
    """The ``[hpc]`` the machine at *path* reads, and its own grant row: its ``[devhost] host``'s, else *user*'s."""
    table = machine_table(path)
    hpc = table.get('hpc', {})
    if host := table.get(OWN_TABLE, {}).get('host', ''):
        return hpc, own_grant(hpc, host)
    return hpc, next((row for row in hpc.get('grant', []) if row.get('user') == user), None)


def login_hosts(path: Path, table: Mapping[str, Any] | None) -> frozenset[str]:
    """The login hosts of the account's cluster -- in the passed ``[hpc]`` slice *table*, else the machine at *path*.

    A machine naming its account (``[devhost] host``) reads its own grant's cluster alone; one that names none
    reads every cluster it declares.
    """
    clusters = (table or {}).get('clusters', {})
    if table is None:
        hpc, row = _own(path)
        clusters = hpc.get('clusters', {})
        clusters = {row.get('cluster'): clusters.get(row.get('cluster'), {})} if row else clusters
    return frozenset(host for cluster in clusters.values() for host in cluster.get('hosts', ()))


def grant_refusal(path: Path) -> str:
    """Why this kit cannot load the ``[hpc]`` the machine at *path* reads (``''``: it loads)."""
    try:
        declared_grants(machine_table(path).get('hpc', {}))
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
    """The set-up of this account's cluster (:func:`_own`; *user* names it where the machine file does not)."""
    hpc, row = _own(path, user)
    if row is None:
        return ()
    grants, _ = declared_grants(hpc)
    mine = (row.get('user'), row.get('cluster'))
    return next((grant.setup for grant in grants if (grant.user, grant.cluster_name) == mine), ())
