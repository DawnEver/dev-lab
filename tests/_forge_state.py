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
        self.deny_delete = False
        self.private = True  # the repository's visibility, as the forge's `private` flag answers it
        self.login = 'a'  # who the token authenticates as: every comment it writes is authored by it
        self._next_comment = 1000

    def add_issue(self, title: str, body: str = '', *, state: str = 'open', **extra: object) -> int:
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

    def titled(self, title: str, state: str = 'open') -> list[int]:
        return [n for n, i in self.issues_by_number.items() if i['title'] == title and i['state'] == state]

    @staticmethod
    def _page(items: list[dict[str, Any]], query: dict[str, str]) -> list[dict[str, Any]]:
        size = int(query.get('limit', '30'))
        page = int(query.get('page', '1'))
        return items[(page - 1) * size : page * size]

    @staticmethod
    def _shape(route: str) -> tuple[str, int]:
        """The route's kind and the number in it (0 when none)."""
        fixed = {'/api/v1/user': 'user', API: 'repo', f'{API}/issues': 'issues'}
        if route in fixed:
            return fixed[route], 0
        head, _, tail = route.removeprefix(f'{API}/issues/').partition('/')
        if head == 'comments':
            return 'comment', int(tail)
        return ('comments' if tail == 'comments' else 'issue'), int(head)

    def _listed(self, query: dict[str, str]) -> list[dict[str, Any]]:
        if self.fail_lists:
            failed = Attempt(1, 502, 'bad gateway', Diagnosis.UNCLASSIFIED)
            raise ForgeCallFailed(Report(('GET', 'issues'), (failed,), 1))
        state = query.get('state', 'open')
        newest = sorted(self.issues_by_number.items(), reverse=True)
        listed = [i | {'comments': len(self.comments[n])} for n, i in newest if state in ('all', i['state'])]
        return self._page(listed, query)

    def _comment(self, number: int, body: dict[str, Any]) -> dict[str, Any]:
        self._next_comment += 1
        made = {
            'id': self._next_comment,
            'body': body['body'],
            'html_url': f'c/{self._next_comment}',
            'user': {'login': self.login},
        }
        self.comments[number].append(made)
        return made

    def _edit_comment(self, comment_id: int, body: dict[str, Any]) -> dict[str, Any]:
        found = next(c for cs in self.comments.values() for c in cs if c['id'] == comment_id)
        found['body'] = body['body']
        return found

    def _delete_comment(self, comment_id: int) -> None:
        for listed in self.comments.values():
            listed[:] = [c for c in listed if c['id'] != comment_id]

    def _delete(self, number: int) -> None:
        if self.deny_delete:  # gitea answers a non-admin token 403
            refused = Attempt(1, 403, 'token does not have at least one of required scope(s)', Diagnosis.FORGE_REFUSED)
            raise ForgeCallFailed(Report(('DELETE', 'issue'), (refused,), 1))
        del self.issues_by_number[number]

    def _edit_issue(self, number: int, body: dict[str, Any]) -> dict[str, Any]:
        self.issues_by_number[number] |= body
        return self.issues_by_number[number]

    def call(self, method: str, path: str, body: object = None, durable: object = None) -> object:
        """Answer from the in-memory state, as gitea would; a create needs no read-back here."""
        del durable
        self.answered = NOW_HTTP
        route, _, raw_query = path.partition('?')
        query = dict(urllib.parse.parse_qsl(raw_query))
        sent: dict[str, Any] = body if isinstance(body, dict) else {}
        kind, number = self._shape(route)
        opened = sum(i['state'] == 'open' for i in self.issues_by_number.values())
        handlers = {
            ('GET', 'user'): lambda: {'login': self.login},
            ('GET', 'repo'): lambda: {
                'open_issues_count': opened,
                'open_pr_counter': 0,
                'has_pull_requests': True,
                'private': self.private,
            },
            ('GET', 'issues'): lambda: self._listed(query),
            ('POST', 'issues'): lambda: self.issues_by_number[self.add_issue(sent['title'], sent['body'])],
            ('GET', 'issue'): lambda: self.issues_by_number[number],
            ('PATCH', 'issue'): lambda: self._edit_issue(number, sent),
            ('GET', 'comments'): lambda: self._page(self.comments[number], query),
            ('POST', 'comments'): lambda: self._comment(number, sent),
            ('PATCH', 'comment'): lambda: self._edit_comment(number, sent),
            ('DELETE', 'issue'): lambda: self._delete(number),
            ('DELETE', 'comment'): lambda: self._delete_comment(number),
        }
        return handlers[method, kind]()
