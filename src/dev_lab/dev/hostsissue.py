"""THE HOSTS ISSUE: the one ``forge hosts`` issue every host card hangs on (:mod:`dev_lab.dev.forgehosts`).

It is the OLDEST issue carrying :data:`HOSTS_MARKER` (or, opened before the marker, titled :data:`HOSTS_TITLE`),
read off every page of the listing; a listing that is blind or partial refuses rather than opening a second one.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Final

from dev_lab.dev.forgepulls import Marker, issues, marker

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = [
    'HOSTS_MARKER',
    'HOSTS_ORIGIN',
    'HOSTS_TITLE',
    'HostsIssueLost',
    'hosts_issue',
    'hosts_issues',
    'is_hosts',
    'open_hosts_issue',
]

#: The title of the issue every host card hangs on.
HOSTS_TITLE: Final = 'forge hosts'

#: The hidden line in the hosts issue's body it is found by.
HOSTS_MARKER: Final = marker(Marker.HOSTS)

#: The text every hosts issue this module opened carries, marker or not: how a machine-made one is told apart.
HOSTS_ORIGIN: Final = '(dev_lab.dev.forgehosts)'


class HostsIssueLost(RuntimeError):
    """The hosts issue was just created and the listing still does not show it: refuse, never open another."""


def is_hosts(raw: Mapping[str, Any]) -> bool:
    """Whether a listed issue is a hosts issue: it carries the marker, or the title from before the marker."""
    return HOSTS_MARKER in (raw.get('body') or '') or raw.get('title') == HOSTS_TITLE


def hosts_issues(client: Client) -> tuple[Mapping[str, Any], ...]:
    """Every hosts issue in every state, oldest first; a failed or partial read raises."""
    return tuple(sorted((raw for raw in issues(client, state='all') if is_hosts(raw)), key=lambda raw: raw['number']))


def _seen_all_open(client: Client) -> None:
    """Refuse a listing that shows fewer open issues than the repository counts: it is blind, not empty.

    Gitea's repository carries ``open_issues_count`` (pulls excluded, counted beside as
    ``open_pr_counter``); GitHub's counts pulls in, so the check is gitea's only. The count is read
    BEFORE the listing, so an issue opened in between cannot make an honest listing look short.
    """
    repo = client.call('GET', client.repo)
    if 'open_pr_counter' not in repo:
        return
    listed = sum(raw['state'] == 'open' for raw in issues(client, state='open'))
    if listed < repo['open_issues_count']:
        seen = f'the listing shows {listed} open issues and the repository counts {repo["open_issues_count"]}'
        msg = f'{seen}; refusing to open a {HOSTS_TITLE!r} issue a blind lookup did not find'
        raise HostsIssueLost(msg)


def hosts_issue(client: Client) -> int | None:
    """The number of the hosts issue -- the oldest -- ``None`` only when the full listing holds none."""
    found = hosts_issues(client)
    return found[0]['number'] if found else None


def open_hosts_issue(client: Client) -> int:
    """Open the hosts issue and return its number: refused when the listing is blind or does not show it."""
    _seen_all_open(client)
    body = f'{HOSTS_MARKER}\nOne comment per serving host, edited in place each tick {HOSTS_ORIGIN}.'
    client.issue_create(HOSTS_TITLE, body)
    number = hosts_issue(client)  # the oldest, so two hosts racing to open it agree on one
    if number is None:
        msg = f'the {HOSTS_TITLE!r} issue just created is not in the listing; refusing to open another'
        raise HostsIssueLost(msg)
    return number
