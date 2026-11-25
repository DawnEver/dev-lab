"""Every retired ``[ops]`` shape, REFUSED by name with its migration (FORMATS-MIGRATE-ONCE, no-backward-compatibility).

:func:`dev_lab.ops.config.load` hands the raw ``[ops]`` table to :func:`refuse` before it builds the typed config, so
the live door and the config-source CI (:mod:`dev_lab.ops.configcheck`, ``structure_only``) refuse the same shapes.
A host's file is migrated ONCE, in its reviewed source, and lands through ``config apply``; nothing upgrades it on
read. A key of a role table outside :data:`RETIRED` is the role's own "unknown keys" refusal.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Final

from dev_lab.dev._forgebackends import GITHUB, backend_for
from dev_lab.dev.forge import forge_of_url

__all__ = ['RETIRED', 'Retired', 'refuse']


@dataclass(frozen=True)
class Retired:
    """One retired key ``[ops.<table>] <key>``: what retired it and where its fact lives now (``migrate``)."""

    table: str
    key: str
    migrate: str


#: Every retired key, each refused with its migration.
RETIRED: Final = (
    Retired('upgrade', 'overrides', 'delete it: the family revisions come from the dev-lab lock'),
    Retired('breakglass', 'totp', 'move it to [ops.consent] totp (#311: the consent issuer holds the TOTP seed)'),
    Retired('breakglass', 'wave_hours', "delete it: a wave's window is its breakglass.wave credential's param "
                                        '(#311); the ceiling is [ops.breakglass] wave_ceiling'),
    Retired('breakglass', 'max_merges', "delete it: a wave's merge cap is its breakglass.wave credential's param "
                                        '(#311); the ceiling is [ops.breakglass] max_merges_max'),
    Retired('breakglass', 'lockout_after', 'move it to [ops.consent] lockout_after (#311: the issuer locks codes out)'),
    Retired('breakglass', 'lockout_minutes', 'move it to [ops.consent] lockout = "<n> min" (#311)'),
    Retired('forge', 'read_only', 'declare each login as [ops.forge.accounts.<login>] role = "read", '
                                  'repos = ["<owner>/<name>", ...] (#402)'),
)  # fmt: skip

#: The roles that act on GitHub as an App since #403, never with a standing token.
_APP_ROLES: Final = ('breakglass', 'judge')


def _on_github(host: str) -> bool:
    return backend_for(forge_of_url(f'https://{host}/o/r.git')) is GITHUB


def _github_tokens(ops: Mapping[str, Any]) -> Iterator[str]:
    for role in _APP_ROLES:
        table = ops.get(role)
        tokens = table.get('tokens') if isinstance(table, Mapping) else None
        for host in sorted(tokens) if isinstance(tokens, Mapping) else ():
            if _on_github(host):
                yield (
                    f'[ops.{role}.tokens] {host} is retired (#403: a standing GitHub token): declare '
                    f'[ops.{role}.apps] "{host}" = {{app_id = <id>, key_file = "<path>"}} and delete the token'
                )


def _found(ops: Mapping[str, Any]) -> Iterator[str]:
    for row in RETIRED:
        table = ops.get(row.table)
        if isinstance(table, Mapping) and row.key in table:
            yield f'[ops.{row.table}] {row.key} is retired: {row.migrate}'
    yield from _github_tokens(ops)


def refuse(ops: Mapping[str, Any]) -> None:
    """Raise :class:`ValueError` naming EVERY retired shape *ops* holds, each with its migration; else return."""
    if found := list(_found(ops)):
        raise ValueError('; '.join(found))
