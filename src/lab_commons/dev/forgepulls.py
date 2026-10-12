"""Pull requests and their comments on the forge -- the verbs the integration tick needs, one shape per forge.

Built on :class:`~lab_commons.dev.forgework.Client`, whose backend already hides gitea vs GitHub: both
forges number a PR as an issue, answer ``/pulls`` with the same head/base shape, edit a PR's base
with ``PATCH /pulls/N {"base": ...}`` and edit a comment with ``PATCH /issues/comments/ID``. The one
difference -- the page-size parameter -- is the backend's, so no caller here branches on the forge.

ONE COMMENT PER SUBJECT, UPDATED IN PLACE. :func:`comment_upsert` finds its comment by a HIDDEN
MARKER (an HTML comment both forges render invisibly) and edits it; it posts only when none exists
and writes nothing when the body is already what it would write. That is what makes a tick
idempotent: running it twice leaves one comment, not two.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Final

from lab_commons.dev.forgework import Comment, ForgeCallFailed, PullRequest, comment_of, is_pull, pull_of

if TYPE_CHECKING:
    from lab_commons.dev.forgework import Client

__all__ = [
    'ListingIncomplete',
    'comment_list',
    'comment_upsert',
    'issues',
    'marker',
    'pages',
    'pr_list',
    'pr_retarget',
    'pulls_off',
]

_NOT_FOUND: Final = 404
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
    """Every issue in *state*, raw, off the listing (never the lagging search index), pulls excluded."""
    return tuple(
        raw for raw in pages(client, f'{client.repo}/issues', {'state': state, 'type': 'issues'}) if not is_pull(raw)
    )


def marker(subject: str) -> str:
    """The hidden line a comment about *subject* is found by."""
    return f'<!-- lab-commons:{subject} -->'


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


def comment_upsert(client: Client, number: int, *, subject: str, text: str) -> tuple[str, Comment | None]:
    """Keep ONE comment about *subject* on *number* saying *text*: ``created``, ``updated`` or ``unchanged``.

    The body is state, so it carries no provenance line -- otherwise a re-run from another machine
    would rewrite a comment whose content did not change.
    """
    line = marker(subject)
    body = f'{line}\n{text}'
    found = next((comment for comment in comment_list(client, number) if line in comment.body), None)
    if found is None:
        return 'created', comment_of(client.call('POST', f'{client.repo}/issues/{number}/comments', {'body': body}))
    if found.body.strip() == body.strip():
        return 'unchanged', found
    return 'updated', comment_of(client.call('PATCH', f'{client.repo}/issues/comments/{found.id}', {'body': body}))
