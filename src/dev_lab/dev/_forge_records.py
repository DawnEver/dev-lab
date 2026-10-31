"""The forge's records -- issue, comment, pull request -- identical in shape whichever forge answered.

Re-exported by :mod:`dev_lab.dev.forgework`, the client that reads them off the wire.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

__all__ = ['Comment', 'Issue', 'PullRequest', 'comment_of', 'is_pull', 'pull_of']


def is_pull(raw: Mapping[str, Any]) -> bool:
    """Whether a listed issue is a pull request: its ``pull_request`` is not null -- even `{}` marks a pull.

    Gitea sends ``"pull_request": null`` on every plain issue, so testing the key's presence read
    every issue as a pull: ``issue list`` printed nothing and the hosts lookup found no issue and
    opened a new one every tick (128 ``forge hosts`` issues on three repos, 2026-10-12).
    """
    return raw.get('pull_request') is not None


@dataclass(frozen=True)
class Issue:
    """An issue, identical in shape whichever forge answered."""

    number: int
    title: str
    state: str
    body: str
    url: str
    author: str


@dataclass(frozen=True)
class Comment:
    """A comment on an issue."""

    id: int
    body: str
    url: str
    #: The login the FORGE records as its writer -- never a claim the body makes about itself.
    author: str = ''


@dataclass(frozen=True)
class PullRequest:
    """A pull request, identical in shape whichever forge answered."""

    number: int
    title: str
    state: str
    body: str
    url: str
    author: str
    head: str
    base: str
    #: The head's commit; a fork's head branch is not in this repository, its commit is (``pull/N/head``).
    head_sha: str = ''
    #: The labels on the PR -- where a user's designation (``priority:user``, ``priority:<n>``) is read.
    labels: tuple[str, ...] = ()
    #: Whether the forge holds it as a draft (gitea: ``draft``, or a ``WIP:``/``[WIP]`` title prefix).
    draft: bool = False
    #: Whether the forge merged it (gitea ``merged``, GitHub ``merged_at``): a CLOSED one without it was refused.
    merged: bool = False


#: Gitea's default title prefixes marking a PR work in progress (its ``WORK_IN_PROGRESS_PREFIXES``).
_WIP_PREFIXES: Final = ('WIP:', '[WIP]')


def _issue(raw: Mapping[str, Any]) -> Issue:
    return Issue(
        raw['number'], raw['title'], raw['state'], raw.get('body') or '', raw['html_url'], raw['user']['login']
    )


def pull_of(raw: Mapping[str, Any]) -> PullRequest:
    """A forge's pull-request JSON as a :class:`PullRequest`."""
    issue = _issue(raw)
    return PullRequest(
        *dataclasses.astuple(issue),
        raw['head']['ref'],
        raw['base']['ref'],
        raw['head'].get('sha') or '',
        tuple(str(label['name']) for label in raw.get('labels') or ()),
        bool(raw.get('draft')) or issue.title.upper().startswith(_WIP_PREFIXES),
        bool(raw.get('merged') or raw.get('merged_at')),
    )


def comment_of(raw: Mapping[str, Any]) -> Comment:
    """A forge's comment JSON as a :class:`Comment`."""
    return Comment(raw['id'], raw.get('body') or '', raw['html_url'], (raw.get('user') or {}).get('login', ''))
