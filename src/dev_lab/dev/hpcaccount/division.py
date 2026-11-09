"""THE HPC DIVISION: which account plays which role, and what each role does -- data, on the workstation.

User rulings 2026-11-09. The division may change, so it has ONE SOURCE: the WORKSTATION machine file's ``[hpc]``
table, which ``deploy-fleet`` reads and passes to each account's deploy::

    [[hpc.grant]]
    user = "<account>"
    role = "<role>"                      # the account's own [deploy] role must equal it

    [hpc.roles.<role>]                   # optional: with no [hpc.roles], DEFAULT_ROLES ships two
    serves = false                       # runs the forge serve cron
    read_only = true                     # a stored forge credential with push/admin is REFUSED (else reported)
    reader = "<forge login>"             # optional: the read-only login that credential must be

A declared ``[hpc.roles]`` REPLACES the defaults whole (never merged), so the file names every role it uses. The
reader is per role, so one shared read-only login is the same value on each role, and a role may still differ.

lab-commons' :func:`lab_commons.hpc.grants.load_grants` refuses keys it does not know (a grant's ``role``, the
``roles`` table), so :func:`split_hpc` hands it only its own keys until lab-commons carries them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

__all__ = ['DEFAULT_ROLES', 'ROLE_KEYS', 'Division', 'account_role', 'load_division', 'split_hpc']

#: The role table when the workstation declares none: verification serves and is reported; research is refused
#: a writer.
DEFAULT_ROLES: Final[Mapping[str, Mapping[str, Any]]] = {
    'verification': {'serves': True, 'read_only': False},
    'research': {'serves': False, 'read_only': True},
}
#: The keys one ``[hpc.roles.<name>]`` may carry.
ROLE_KEYS: Final = frozenset({'serves', 'read_only', 'reader'})


@dataclass(frozen=True)
class Division:
    """Each account's declared role and the role table."""

    grant_roles: Mapping[str, str]
    roles: Mapping[str, Mapping[str, Any]] = field(default_factory=lambda: DEFAULT_ROLES)

    def role_of(self, user: str) -> str:
        """*user*'s role as its grant declares it; ``''`` when undeclared."""
        return self.grant_roles.get(user, '')

    def refusal(self, user: str) -> str | None:
        """Why *user*'s declared role is not in the table; ``None`` when it is, or none is declared."""
        role = self.role_of(user)
        if role and role not in self.roles:
            return f'{user}: role {role!r} is not in [hpc.roles] {sorted(self.roles)}'
        return None


def _roles(raw: Mapping[str, Mapping[str, Any]] | None) -> Mapping[str, Mapping[str, Any]]:
    if raw is None:
        return DEFAULT_ROLES
    for name, table in raw.items():
        if unknown := set(table) - ROLE_KEYS:
            msg = f'[hpc.roles.{name}] has unknown keys {sorted(unknown)}; known: {sorted(ROLE_KEYS)}'
            raise ValueError(msg)
    return {name: dict(table) for name, table in raw.items()}


def load_division(hpc: Mapping[str, Any]) -> Division:
    """The division the raw ``[hpc]`` table declares; an unknown role key refused naming it."""
    return Division(
        grant_roles={grant['user']: grant.get('role', '') for grant in hpc.get('grant', [])},
        roles=_roles(hpc.get('roles')),
    )


def account_role(role: str, fleet_role: str, passed: Mapping[str, Any] | None) -> Mapping[str, Any] | str:
    """What an account of *role* does, as its deploy decides it; else why the deploy refuses.

    *fleet_role* and *passed* are what ``deploy-fleet`` passed from the workstation (``''``/``None``: a hand-run
    deploy). The workstation is the source: a *role* differing from *fleet_role* is refused naming both, and a
    role with nothing passed must be one of :data:`DEFAULT_ROLES`.
    """
    if fleet_role and role != fleet_role:
        return (
            f"this account's [deploy] role is {role!r}; the workstation's [[hpc.grant]] declares {fleet_role!r}. "
            f'The workstation is the source: set [deploy] role = "{fleet_role}" here'
        )
    if passed is not None:
        return passed
    if role not in DEFAULT_ROLES:
        return f'role {role!r} is not a shipped default {sorted(DEFAULT_ROLES)}: deploy it through deploy-fleet'
    return DEFAULT_ROLES[role]


def split_hpc(hpc: Mapping[str, Any]) -> tuple[dict[str, Any], Division]:
    """``(the [hpc] table lab-commons reads, the division)``: the division's keys taken out of the first."""
    grants = [{key: value for key, value in grant.items() if key != 'role'} for grant in hpc.get('grant', [])]
    table = {key: value for key, value in hpc.items() if key != 'roles'}
    return {**table, 'grant': grants}, load_division(hpc)
