"""The forge HOSTS ISSUE: the one issue every serving host keeps its card on, found or opened exactly once.

A blind or partial listing is refused rather than read as empty (:class:`HostsIssueLost`), so two hosts never
open two issues. The cards themselves are :mod:`dev_lab.dev.forgehosts`.

ONE ISSUE, FOUND OR REFUSED, NEVER GUESSED. The issue is the OLDEST one carrying :data:`HOSTS_MARKER`
(or, for an issue opened before the marker, titled :data:`HOSTS_TITLE`), read off EVERY page of the
listing in EVERY state -- a closed home is still the home. A lookup that fails raises; it is never read
as "none exists", because that reading opened a fresh issue on every tick of every host (128 on three
repos, 2026-10-12). Two hosts racing to open the first one re-read after the create and both write to
the oldest; the loser is closed by ``forge tidy`` (:mod:`dev_lab.dev.forgetidy`).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from dev_lab.dev.forgepulls import (
    Marker,
    issues,
    marker,
)
from dev_lab.dev.forgework import Client

#: The title of the issue every host card hangs on.
HOSTS_TITLE: Final = 'forge hosts'


#: The hidden line in the hosts issue's body it is found by.
HOSTS_MARKER: Final = marker(Marker.HOSTS)


#: The text every hosts issue this module opened carries, marker or not: how a machine-made one is told apart.
HOSTS_ORIGIN: Final = '(dev_lab.dev.forgehosts)'


class HostsIssueLost(RuntimeError):
    """The hosts issue was just created and the listing still does not show it: refuse, never open another."""


def is_private(client: Client) -> bool:
    """Whether the forge says this repository is private; an answer without the flag is read as public."""
    repo = client.call('GET', client.repo)
    return isinstance(repo, Mapping) and repo.get('private') is True


def public_siblings(client: Client) -> tuple[str, ...]:
    """The names of this repository's owner's repos the forge says are public (dev-lab#791 wall 3); one page of 100.

    Both forges answer ``/users/<owner>/repos``; a row without the flag is read as public, like :func:`is_private`.
    """
    owner = client.repo.strip('/').split('/')[1]  # ``/repos/<owner>/<repo>``
    rows = client.call('GET', f'/users/{owner}/repos?per_page=100')
    if not isinstance(rows, list):
        return ()
    published = (row for row in rows if isinstance(row, Mapping) and row.get('private') is not True)
    return tuple(str(row['name']) for row in published if row.get('name'))


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
    """Open the hosts issue after a full listing found none; refuse a blind listing (:class:`HostsIssueLost`)."""
    _seen_all_open(client)
    body = f'{HOSTS_MARKER}\nOne comment per serving host, edited in place each tick {HOSTS_ORIGIN}.'
    client.issue_create(HOSTS_TITLE, body)
    number = hosts_issue(client)  # the oldest, so two hosts racing to open it agree on one
    if number is None:
        msg = f'the {HOSTS_TITLE!r} issue just created is not in the listing; refusing to open another'
        raise HostsIssueLost(msg)
    return number
