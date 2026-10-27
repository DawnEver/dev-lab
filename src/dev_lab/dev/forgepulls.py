"""Pull requests and their comments on the forge -- the verbs the integration tick needs, one shape per forge.

Built on :class:`~dev_lab.dev.forgework.Client`, whose backend already hides gitea vs GitHub: both
forges number a PR as an issue, answer ``/pulls`` with the same head/base shape, edit a PR's base
with ``PATCH /pulls/N {"base": ...}`` and edit a comment with ``PATCH /issues/comments/ID``. The one
difference -- the page-size parameter -- is the backend's, so no caller here branches on the forge.

ONE COMMENT PER SUBJECT, UPDATED IN PLACE. :func:`comment_upsert` finds its comment by a HIDDEN
MARKER (an HTML comment both forges render invisibly) and edits it; it posts only when none exists
and writes nothing when the body is already what it would write. That is what makes a tick
idempotent: running it twice leaves one comment, not two.

EVERY MARKER KIND IS A :class:`Marker` MEMBER, and :func:`marker` takes nothing else, so the enum IS the set
of kinds the writers emit -- not a second list kept beside them. A marker on the forge whose kind no member
names was written by a retired writer, and ``forge tidy`` deletes its comment (:func:`marker_kinds`).
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
from collections.abc import Mapping
from datetime import UTC, timedelta
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

from dev_lab.dev._forge_journal import Durable, Probe, since
from dev_lab.dev.forgework import Comment, ForgeCallFailed, PullRequest, comment_of, is_pull, pull_of

if TYPE_CHECKING:
    from pathlib import Path

    from dev_lab.dev.forgework import Client

__all__ = [
    'ListingIncomplete',
    'Marker',
    'comment_list',
    'comment_upsert',
    'forget_issue',
    'issues',
    'marker',
    'marker_kinds',
    'pages',
    'pr_list',
    'pr_retarget',
    'pulls_off',
]

_NOT_FOUND: Final = 404
_MARKER: Final = re.compile(r'<!-- lab-commons:([^:\s]+)(?::\S*)? -->')
#: A listing's page size, and the pages read before it is refused as incomplete.
_PAGE: Final = 50
_PAGES: Final = 100


class ListingIncomplete(RuntimeError):
    """A listing still full at its page bound: what it did not read may hold the object being looked for."""


def pages(client: Client, path: str, query: Mapping[str, str]) -> list[Any]:
    """Every page of the listing at *path*; one still full at the bound is :class:`ListingIncomplete`."""
    found: list[Any] = []
    for page in range(1, _PAGES + 1):
        params = dict(query) | {client.backend.page_param: str(_PAGE), 'page': str(page)}
        listed = client.call('GET', f'{path}?{urllib.parse.urlencode(params)}')
        found += listed
        if len(listed) < _PAGE:
            return found
    msg = f'{path} still lists past {_PAGES} pages of {_PAGE}; refusing a partial read'
    raise ListingIncomplete(msg)


def issues(client: Client, *, state: str = 'all') -> tuple[Mapping[str, Any], ...]:
    """Every issue in *state*, raw, off the listing (never the lagging search index), pulls excluded, oldest first.

    A client with a :attr:`~dev_lab.dev.forgework.Client.cache_dir` reads only the issues UPDATED since its
    last read (``since=``, both forges) and merges them into the cache (:func:`_cached_issues`); without one,
    every issue in *state* is read afresh.
    """
    if client.cache_dir is None:
        listed = pages(client, f'{client.repo}/issues', {'state': state, 'type': 'issues'})
        held = {int(raw['number']): raw for raw in listed if not is_pull(raw)}
    else:
        held = _cached_issues(client, client.cache_dir)
    return tuple(held[number] for number in sorted(held) if state in {'all', held[number].get('state')})


#: How far before the forge's clock at a read the next read starts, so an issue updated while it ran is read again.
ISSUE_OVERLAP: Final = timedelta(minutes=2)


def _cache_file(client: Client, home: Path) -> Path:
    return home / f'issues-{client.forge.owner}-{client.forge.repo}.json'


def _cached_issues(client: Client, home: Path) -> dict[int, Mapping[str, Any]]:
    """The cache of every issue, refreshed by one ``since=`` read of what changed after its cursor.

    THE INCIDENT (2026-10-24): every tick of five accounts' hosts re-read every issue ever opened, page by
    page -- 958 calls and 2775 s of server time in ten minutes on one repository. The cursor is the forge's
    own clock (the ``Date`` of the read) less :data:`ISSUE_OVERLAP`, so a host's skewed clock cannot skip an
    update. A cold or unreadable cache reads in full once. The file is replaced whole, so a concurrent reader
    sees the old cache or the new one; the writer that loses a race leaves the earlier cursor, read again.
    """
    path = _cache_file(client, home)
    try:
        saved = json.loads(path.read_text(encoding='utf-8'))
        cursor, held = str(saved['cursor']), {int(key): raw for key, raw in saved['issues'].items()}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        cursor, held = '', {}
    query = {'state': 'all', 'type': 'issues'} | ({'since': cursor} if cursor else {})
    listed = pages(client, f'{client.repo}/issues', query)
    held |= {int(raw['number']): raw for raw in listed if not is_pull(raw)}
    if cursor and _ghosts(client, held):
        listed = pages(client, f'{client.repo}/issues', {'state': 'all', 'type': 'issues'})
        held = {int(raw['number']): raw for raw in listed if not is_pull(raw)}
    if client.answered:
        read_at = parsedate_to_datetime(client.answered).astimezone(UTC) - ISSUE_OVERLAP
        _save(path, {'cursor': read_at.strftime('%Y-%m-%dT%H:%M:%SZ'), 'issues': held})
    return held


def _ghosts(client: Client, held: Mapping[int, Mapping[str, Any]]) -> bool:
    """Whether *held* lists more open issues than the repository counts: one was DELETED since the cursor.

    A ``since=`` read never says an issue is gone, and only the deleting host can :func:`forget_issue`.
    Gitea's ``open_issues_count`` excludes pulls (``open_pr_counter`` beside it); GitHub's counts them, so
    the check is gitea's only.
    """
    repo = client.call('GET', client.repo)
    if not isinstance(repo, Mapping) or 'open_pr_counter' not in repo:
        return False
    return sum(raw.get('state') == 'open' for raw in held.values()) > int(repo['open_issues_count'])


def _save(path: Path, saved: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    spare = path.with_name(f'{path.name}.{os.getpid()}.tmp')
    spare.write_text(json.dumps(saved), encoding='utf-8')
    spare.replace(path)


def forget_issue(client: Client, number: int) -> None:
    """Drop DELETED issue *number* from the cache: a ``since=`` read never says an issue is gone."""
    if client.cache_dir is None:
        return
    path = _cache_file(client, client.cache_dir)
    try:
        saved = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return
    saved['issues'].pop(str(number), None)
    _save(path, saved)


class Marker(StrEnum):
    """Every kind of hidden marker a writer emits; a kind on the forge no member names is retired."""

    HOSTS = 'forge-hosts'  #: the hosts issue's body (:mod:`dev_lab.dev.forgehosts`)
    HOST = 'host'  #: one card comment per serving host, keyed by the host (:mod:`dev_lab.dev.forgehosts`)
    INTEGRATION = 'integration'  #: a child PR's one integration comment (:mod:`dev_lab.dev.forgeintegration`)
    TIDY = 'tidy'  #: ``forge tidy``'s one summary comment (:mod:`dev_lab.dev.forgetidy`)
    REVIEW = 'review'  #: one review round per PR head, keyed by the sha (:mod:`dev_lab.dev.forgereview`)
    DISPOSITION = 'review-disposition'  #: the integrator's disposition of a finding, keyed by its id (``forge review``)
    SECURITY_RELEASE = 'security-release'  #: the integrator's release of new exemptions (``forge security``)
    LANDED = 'landed'  #: a landed PR's one closing comment, keyed by the head sha (:mod:`dev_lab.dev.prlanded`)
    POLLER = 'poller'  #: the hosts issue's one poller lease (:mod:`dev_lab.dev.forgepoller`)


def marker(kind: Marker, key: str = '') -> str:
    """The hidden line a comment of *kind* (about *key*, when one kind has several) is found by."""
    return f'<!-- lab-commons:{Marker(kind)}{f":{key}" if key else ""} -->'


def marker_kinds(text: str) -> tuple[str, ...]:
    """The kind of every hidden marker in *text*, registered or not."""
    return tuple(_MARKER.findall(text))


def pr_list(client: Client, *, state: str = 'open') -> tuple[PullRequest, ...]:
    """Every pull request in *state*, lowest number first; none when the repository disables pull requests.

    Gitea answers ``/pulls`` 404 for a repository with PRs switched off (:func:`pulls_off`); a 404 for
    any other reason still raises.
    """
    try:
        raw = pages(client, f'{client.repo}/pulls', {'state': state})
    except ForgeCallFailed as failed:
        if pulls_off(client, failed):
            return ()
        raise
    return tuple(sorted((pull_of(item) for item in raw), key=lambda pr: pr.number))


def pulls_off(client: Client, failed: ForgeCallFailed) -> bool:
    """Whether *failed* is gitea's 404 for a repository whose pull requests are switched off.

    The 404 is read back against the repository's own ``has_pull_requests`` flag, so a 404 for any
    other reason is not mistaken for it.
    """
    last = failed.report.attempts[-1].returncode if failed.report.attempts else 0
    return last == _NOT_FOUND and client.call('GET', client.repo).get('has_pull_requests') is False


def pr_retarget(client: Client, number: int, base: str) -> PullRequest:
    """Point PR *number* at *base*; the head is untouched."""
    return pull_of(client.call('PATCH', f'{client.repo}/pulls/{number}', {'base': base}))


def comment_list(client: Client, number: int) -> tuple[Comment, ...]:
    """Every comment on issue or PR *number*, oldest first."""
    return tuple(comment_of(raw) for raw in pages(client, f'{client.repo}/issues/{number}/comments', {}))


def comment_upsert(
    client: Client, number: int, *, kind: Marker, key: str = '', text: str
) -> tuple[str, Comment | None]:
    """Keep ONE comment of *kind* (about *key*) on *number* saying *text*: ``created``, ``updated`` or ``unchanged``.

    The body is state, so it carries no provenance line -- otherwise a re-run from another machine
    would rewrite a comment whose content did not change.
    """
    line = marker(kind, key)
    body = f'{line}\n{text}'
    found = next((comment for comment in comment_list(client, number) if line in comment.body), None)
    if found is None:
        path = f'{client.repo}/issues/{number}/comments'
        listed = f'{path}?since={since(client.clock())}'
        made = client.call('POST', path, {'body': body}, durable=Durable(probe=Probe(listed, {'body': body})))
        return 'created', comment_of(made)
    if found.body.strip() == body.strip():
        return 'unchanged', found
    return 'updated', comment_of(client.call('PATCH', f'{client.repo}/issues/comments/{found.id}', {'body': body}))
