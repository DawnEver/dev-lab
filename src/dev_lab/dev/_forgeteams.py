"""Whether an org TEAM grants a login write on a repository: the half of ``Client.can_write`` Gitea needs.

Gitea answers ``collaborators/{login}/permission`` with ``none`` for a login whose write comes from an org team scoped
to repository units (2026-11-06: every internal motronics PR read as external, so nothing auto-merged). A team grants
write when its ``permission`` -- or its ``units_map`` entry for the backend's writer unit -- is a writer permission.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dev_lab.dev.forgefailure import ForgeCallFailed

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = ['team_grants_write']


def team_grants_write(client: Client, quoted: str) -> bool:
    """Whether a team of *client*'s repository granting write on its backend's writer unit lists the quoted login.

    Raises :class:`ForgeCallFailed` when the team listing is refused; a refused membership read is "not a member".
    """
    unit, writers = client.backend.writer_unit, client.backend.writer_permissions
    granting = [
        team['id']
        for team in client.call('GET', f'{client.repo}/teams') or []
        if isinstance(team, dict)
        and (team.get('permission') in writers or (team.get('units_map') or {}).get(unit) in writers)
    ]
    return any(_member(client, f'{client.backend.api_root}/teams/{team}/members/{quoted}') for team in granting)


def _member(client: Client, path: str) -> bool:
    try:
        client.call('GET', path)
    except ForgeCallFailed:  # a refused membership read (404 for a non-member) is "not a member"
        return False
    return True
