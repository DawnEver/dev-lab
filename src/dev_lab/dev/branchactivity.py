"""IDLE-IS-ACTIVITY: how long an origin branch has been idle is read off its last PUSH or PR activity, never a commit.

dev-lab #611 (2026-11-26). The prune, the branch policy and the integrator read idleness off the tip's committer date,
so a branch rebased or carrying an old commit read days idle the minute it was pushed, and the one-day retention
ruling retired live lanes. A committer date is when a commit was MADE; nothing about it says whether anyone still
works on the branch. What does: the forge's record of the last push to the ref, and the last update of a pull
request whose head it is.

:func:`last_activity` reads both and answers the newer, or ``None`` -- UNKNOWN -- when the forge records neither (a
Gitea forge exposes no push time; a branch with no PR then has no activity on record). UNKNOWN is never read as
idle: a caller lists such a branch as UNKNOWN and does nothing to it.

A committer date stays useful as a LOWER BOUND: a commit is pushed after it is made, so a branch whose tip was
committed inside the bound is not idle, and :func:`idle_hours` asks the forge only about the rest.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from dev_lab.dev._forgebackends import GITHUB
from dev_lab.dev.forgefailure import ForgeCallFailed

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = ['UNKNOWN', 'Activity', 'activity_of', 'idle_hours', 'last_activity']

#: How an unread activity is said wherever an idle age is printed.
UNKNOWN: Final = 'UNKNOWN'
_HOUR_S: Final = 3600.0
_NOT_FOUND: Final = 404

#: A branch name -> when it was last pushed or its PR last updated; ``None`` when the forge records neither.
type Activity = Callable[[str], datetime | None]


def _stamp(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    return datetime.fromisoformat(raw).astimezone(UTC)


def _missing(failed: ForgeCallFailed) -> bool:
    attempts = failed.report.attempts
    return bool(attempts) and attempts[-1].returncode == _NOT_FOUND


def _pushed(client: Client, branch: str) -> datetime | None:
    """GitHub's activity record of the ref (pushes, force pushes); Gitea records none -- ``None``."""
    if client.backend is not GITHUB:
        return None
    query = urllib.parse.urlencode({'ref': f'refs/heads/{branch}', 'per_page': '1'})
    try:
        listed = client.call('GET', f'{client.repo}/activity?{query}')
    except ForgeCallFailed as failed:
        if _missing(failed):
            return None
        raise
    return _stamp(listed[0].get('timestamp')) if isinstance(listed, list) and listed else None


def _pr_updated(client: Client, branch: str, integration: str) -> datetime | None:
    """The newest ``updated_at`` of a pull request whose head is *branch*, in any state; ``None`` when there is none."""
    if client.backend is GITHUB:
        query = urllib.parse.urlencode({'state': 'all', 'head': f'{client.forge.owner}:{branch}', 'per_page': '100'})
        raws: Any = client.call('GET', f'{client.repo}/pulls?{query}')
    else:
        path = f'{client.repo}/pulls/{urllib.parse.quote(integration, safe="")}/{urllib.parse.quote(branch, safe="/")}'
        try:
            raws = [client.call('GET', path)]
        except ForgeCallFailed as failed:
            if _missing(failed):
                return None
            raise
    stamps = [found for raw in raws or () if isinstance(raw, dict) and (found := _stamp(raw.get('updated_at')))]
    return max(stamps, default=None)


def last_activity(client: Client, branch: str, integration: str) -> datetime | None:
    """When *branch* was last pushed or a PR of it last updated -- the newer -- else ``None`` (UNKNOWN).

    Raises:
        ForgeCallFailed: the forge failed for a reason other than "not found".

    """
    found = [at for at in (_pushed(client, branch), _pr_updated(client, branch, integration)) if at is not None]
    return max(found, default=None)


def activity_of(client: Client, integration: str) -> Activity:
    """:func:`last_activity` of *client*'s branches against *integration*, as the callable the judges take."""
    return lambda branch: last_activity(client, branch, integration)


def idle_hours(branch: str, committed: datetime, *, now: datetime, bound: float, activity: Activity) -> float | None:
    """Hours *branch* has been idle at *now*; ``None`` when UNKNOWN.

    Inside *bound* by its commit (*committed*, a lower bound on its last push) it is that age, and the forge is not
    asked; past it, the age of its :data:`Activity`.
    """
    floor = (now - committed).total_seconds() / _HOUR_S
    if floor < bound:
        return floor
    at = activity(branch)
    return None if at is None else (now - at).total_seconds() / _HOUR_S
