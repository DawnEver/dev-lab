"""A forge listing read page by page: one request per page, until a short page or the caller's limit.

A forge caps one page (Gitea serves at most 50, GitHub 100) below a large limit, so a single request silently
returned only the first page -- a listing of 1000 open issues read 50.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Callable, Sequence
from typing import Any, Final

from dev_lab.dev._forge_records import Issue, _issue, is_pull

__all__ = ['ISSUE_PAGE', 'issues', 'paged']

#: One page of a listing: the size both forges serve.
ISSUE_PAGE: Final = 50


def paged(read: Callable[[int, int], list], limit: int) -> tuple:
    """Up to *limit* raw rows: *read(page, size)* answers one page; reading stops at a short page or the limit."""
    size = min(limit, ISSUE_PAGE)
    found: list = []
    for page in range(1, limit // size + 2):
        rows = read(page, size)
        found += rows
        if len(rows) < size or len(found) >= limit:
            break
    return tuple(found[:limit])


def issues(
    call: Callable[[str, str], Any], url: str, state: str, limit: int, labels: Sequence[str] = ()
) -> tuple[Issue, ...]:
    """Issues in *state* carrying every one of *labels*, among the first *limit* rows of *url*.

    *url* is a list query with ``{state}``/``{limit}``. Both forges take ``labels=<a,b>`` by NAME, but Gitea
    IGNORES a name it does not know and answers every issue -- so the rows are filtered again by the labels
    they carry, and an unknown label lists nothing. GitHub lists pull requests under ``issues`` too; they are
    dropped after reading.
    """
    if labels:
        url = f'{url}&labels={urllib.parse.quote(",".join(labels))}'
    rows = paged(lambda page, size: call('GET', f'{url.format(state=state, limit=size)}&page={page}'), limit)
    wanted = set(labels)
    return tuple(
        _issue(row)
        for row in rows
        if not is_pull(row) and wanted <= {str(one['name']) for one in row.get('labels') or ()}
    )
