"""An HPC ACCOUNT's host file -- the third host kind of the config source, beside a server and a development machine.

USER RULING 2026-11-15: every HPC account has its own layer, one way: FAMILY -> ACCOUNT -> LOCAL. The family file
declares the cluster (``[hpc.clusters.<name>]``) and the account's grant (``[[hpc.grant]]`` user, cluster, slurm
account, role) once; ``hosts/<cluster>-<user>.toml`` declares only what is true of that account alone:

- ``[deploy]`` -- where and what it deploys (:mod:`dev_lab.dev.hpcaccount.spec`), WITHOUT ``role``: the role is the
  grant's, and the render derives it (:func:`derived`);
- ``[schedule]`` (its tick), ``[hpc.paging]`` (its pages), ``[capabilities.*]`` (what it runs), ``[priority]``
  (whose jobs it serves first).

The file's NAME names its grant: an account file whose ``<cluster>-<user>`` is no family grant is refused, and so is
a key the family file already holds. :func:`dev_lab.ops.configcheck.check_host` calls :func:`check`;
:func:`dev_lab.dev.devhost.render` layers :func:`derived` over the file.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, Final

from dev_lab.dev.devschema import app_tables
from dev_lab.dev.hpcaccount.grantslice import granted_root
from dev_lab.dev.hpcaccount.spec import parse
from dev_lab.dev.testcost import BUDGET_TABLE, budget_defects

__all__ = ['TABLES', 'TABLES_DOOR', 'check', 'derived', 'grant_of', 'is_account']

#: What an account file may declare; an empty table is open (its own module checks its keys).
TABLES: Final[Mapping[str, Any]] = {
    'deploy': {},
    'schedule': {},
    'env': {},
    'capabilities': {},
    'priority': {},
    'storage': {'reach': {}},  # which storage remotes this account reaches (lab_commons.storage)
    'hpc': {'paging': {}},
    'writeroots': {},  # the account's writable-root allowlist (dev_lab.dev.writeroots, ruling R8)
    'test_budget': {},  # the account's test budget (dev_lab.dev.testcost.budget_defects checks its keys)
}
#: Where an account table is opened: the door an undeclared one's refusal names.
TABLES_DOOR: Final = 'dev_lab.dev.accounthost.TABLES'
#: ``[deploy]`` keys the family grant owns: stated in an account file they would be a second copy.
_DERIVED: Final = ('role', 'slurm_account', 'partitions')


def is_account(host: Mapping[str, Any]) -> bool:
    """Whether a parsed host file is an HPC account's: it deploys (``[deploy]``) and is neither server nor machine."""
    return 'deploy' in host and 'ops' not in host and 'dev' not in host


def grant_of(name: str, family: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The family grant the account file *name* (``<cluster>-<user>``) is; ``None`` when no grant is."""
    for grant in family.get('hpc', {}).get('grant', []):
        if name == f'{grant.get("cluster", "")}-{grant.get("user", "")}':
            return grant
    return None


def derived(name: str, family: Mapping[str, Any]) -> dict[str, Any]:
    """What the render adds to account *name* from its family grant; ``{}`` for no grant.

    ``[deploy] role`` and ``[hpc] reach``: an account reaches its own grant, so the roles it may use are its own
    role -- without it ``lab_commons.hpc`` refuses every grant on the account (HPC-ACCESS-BY-ROLE).
    """
    grant = grant_of(name, family)
    if not grant or not grant.get('role'):
        return {}
    return {'deploy': {'role': grant['role']}, 'hpc': {'reach': [grant['role']]}}


def _leaves(table: Mapping[str, Any], prefix: str = '') -> Iterator[str]:
    for key, value in table.items():
        if isinstance(value, Mapping):
            yield from _leaves(value, f'{prefix}{key}.')
        else:
            yield f'{prefix}{key}'


def _undeclared(table: Mapping[str, Any], schema: Mapping[str, Any], prefix: str = '') -> Iterator[str]:
    """Each undeclared dotted key of *table*, with the keys its level declares and where one is opened."""
    for key, value in table.items():
        if key not in schema:
            level = f'[{prefix[:-1]}] declares' if prefix else 'an account file declares'
            tables = ', '.join(sorted(schema))
            yield f'{prefix}{key} is not an account table -- {level} {tables}; open one in {TABLES_DOOR}'
        elif schema[key] and isinstance(value, Mapping):
            yield from _undeclared(value, schema[key], f'{prefix}{key}.')


def check(path: Path, host: Mapping[str, Any], family: Mapping[str, Any]) -> list[str]:
    """Defects of the account file at *path* (parsed: *host*) against the *family* file."""
    name = path.stem
    found = []
    grant = grant_of(name, family)
    if grant is None:
        found.append(f'{name} names no family grant: an account file is hosts/<cluster>-<user>.toml of a [[hpc.grant]]')
    elif 'schedule' in host and grant.get('role') != 'verification':
        found.append(
            f'[schedule] on a {grant.get("role") or "role-less"} account: the tick period exists only for a serving '
            '(verification) account -- delete the table (SCHEDULER-ONLY-FOR-SERVING)'
        )
    found += [f"deploy.{key} is the family grant's; the render derives it" for key in _DERIVED if key in host['deploy']]
    found += [
        f'{key} restates the family file; it lives there once'
        for key in sorted(set(_leaves(host)) & set(_leaves(family)))
    ]
    opened = {**TABLES, **{app: {} for app in app_tables(family)}}
    found += list(_undeclared(host, opened))
    found += budget_defects(host.get(BUDGET_TABLE, {}))
    try:  # an unstated root is the grant's cluster root (dev-lab #878): the family declaration is the source
        parse(host, path, root=granted_root(family.get('hpc'), name))
    except ValueError as bad:
        found.append(str(bad))
    return found
