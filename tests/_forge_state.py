"""A STATEFUL gitea-shaped forge: issues and comments that persist between calls, paged like gitea.

The recorder in ``_forge_fake.py`` replays canned answers, so it cannot show that running a tick twice
leaves ONE issue. This one holds the state, and it answers exactly as gitea does in the detail that
caused the 2026-10-12 flood: every plain issue carries ``"pull_request": null``.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

from lab_commons.dev.forge import Forge
from lab_commons.dev.forgework import Client, ForgeCallFailed
from lab_commons.dev.netverb import Attempt, Diagnosis, Report

API = '/api/v1/repos/o/r'
FORGE = Forge('forge.example.org', 'o', 'r')
NOW_HTTP = 'Mon, 12 Oct 2026 12:00:00 GMT'


class StateForge(Client):
    """A :class:`Client` whose every call is answered from in-memory issues; *fail_lists* refuses listings."""

    def __init__(self) -> None:
        super().__init__(FORGE, 'T', sleep=lambda _s: None)
        self.issues_by_number: dict[int, dict[str, Any]] = {}
        self.comments: dict[int, list[dict[str, Any]]] = {}
        self.fail_lists = False
        self._next_comment = 1000

    def add_issue(self, title: str, body: str = '', *, state: str = 'open', **extra: Any) -> int:  # noqa: ANN401
        number = max(self.issues_by_number, default=0) + 1
        self.issues_by_number[number] = {
            'number': number,
            'title': title,
            'state': state,
            'body': body,
            'html_url': f'https://forge.example.org/o/r/issues/{number}',
            'user': {'login': 'a'},
            'pull_request': None,
            'labels': [],
            'created_at': '2026-10-12T12:00:00+00:00',
        } | extra
        self.comments[number] = []
        return number

    def _page(self, items: list[Any], query: dict[str, str]) -> list[Any]:
        size = int(query.get('limit', '30'))
        page = int(query.get('page', '1'))
        return items[(page - 1) * size : page * size]

    def call(self, method: str, path: str, body: Any = None, landed: Any = None) -> Any:  # noqa: ANN401, C901, PLR0911 -- one router for the fake's whole surface
        self.answered = NOW_HTTP
        route, _, raw_query = path.partition('?')
        query = dict(urllib.parse.parse_qsl(raw_query))
        if route == '/api/v1/user':
            return {'login': 'a'}
        if route == API:
            opened = sum(i['state'] == 'open' for i in self.issues_by_number.values())
            return {'open_issues_count': opened, 'open_pr_counter': 0, 'has_pull_requests': True}
        if route == f'{API}/issues' and method == 'GET':
            if self.fail_lists:
                raise ForgeCallFailed(
                    Report(('GET', path), (Attempt(1, 502, 'bad gateway', Diagnosis.UNCLASSIFIED),), 1)
                )
            state = query.get('state', 'open')
            listed = [i for n, i in sorted(self.issues_by_number.items(), reverse=True) if state in ('all', i['state'])]
            return self._page(listed, query)
        if route == f'{API}/issues' and method == 'POST':
            return self.issues_by_number[self.add_issue(body['title'], body['body'])]
        parts = route.removeprefix(f'{API}/issues/').split('/')
        if parts[0] == 'comments' and method == 'PATCH':
            found = next(c for cs in self.comments.values() for c in cs if c['id'] == int(parts[1]))
            found['body'] = body['body']
            return found
        number = int(parts[0])
        if parts[1:] == ['comments'] and method == 'GET':
            return self._page(self.comments[number], query)
        if parts[1:] == ['comments'] and method == 'POST':
            self._next_comment += 1
            made = {'id': self._next_comment, 'body': body['body'], 'html_url': f'c/{self._next_comment}'}
            self.comments[number].append(made)
            return made
        if not parts[1:] and method == 'PATCH':
            self.issues_by_number[number] |= body
            return self.issues_by_number[number]
        if not parts[1:] and method == 'GET':
            return self.issues_by_number[number]
        msg = f'unrouted {method} {path}'
        raise AssertionError(msg)

    def titled(self, title: str, state: str = 'open') -> list[int]:
        return [n for n, i in self.issues_by_number.items() if i['title'] == title and i['state'] == state]
