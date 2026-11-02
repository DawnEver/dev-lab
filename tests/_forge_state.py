"""A STATEFUL forge: issues, pull requests, comments and commit statuses that persist between calls, paged.

Gitea-shaped by default; built over a ``github.com`` :class:`Forge` it answers the GitHub paths of the same
verbs (the repository collection is the backend's, so one handler table serves both).

The recorder in ``_forge_fake.py`` replays canned answers, so it cannot show that running a tick twice
leaves ONE issue. This one holds the state, and it answers exactly as gitea does in the detail that
caused the 2026-10-12 flood: every plain issue carries ``"pull_request": null``.
"""

from __future__ import annotations

import base64
import urllib.parse
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

from dev_lab.dev.forge import Forge
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgework import GITEA_ACTIONS_LOGIN, Client
from dev_lab.dev.netverb import Attempt, Diagnosis, Report

API = '/api/v1/repos/o/r'
FORGE = Forge('forge.example.org', 'o', 'r')
NOW_HTTP = 'Mon, 12 Oct 2026 12:00:00 GMT'


class StateForge(Client):
    """A :class:`Client` whose every call is answered from in-memory issues; *fail_lists* refuses listings."""

    def __init__(self, forge: Forge = FORGE) -> None:
        super().__init__(forge, 'T', sleep=lambda _s: None)
        self.issues_by_number: dict[int, dict[str, Any]] = {}
        self.pulls: dict[int, dict[str, Any]] = {}
        self.statuses: dict[str, list[dict[str, Any]]] = {}
        #: Every merge the forge was asked for, as sent: ``(number, body)``.
        self.merges: list[tuple[int, dict[str, Any]]] = []
        self.comments: dict[int, list[dict[str, Any]]] = {}
        #: The repository's Actions runs, as Gitea's ``GET .../actions/runs`` lists them.
        self.runs: list[dict[str, Any]] = []
        #: The repository's default branch, as ``GET /repos/{o}/{r}`` names it.
        self.default_branch = 'main'
        self.fail_lists = False
        self.deny_delete = False
        #: Every branch the forge was asked to delete by ref (GitHub's ``DELETE .../git/refs/heads/<b>``).
        self.deleted_refs: list[str] = []
        self.private: bool | None = True  # the repository's visibility, as the forge's `private` flag answers it
        self.login = 'a'  # who the token authenticates as: every comment it writes is authored by it
        #: ``{login: repository permission}`` as the forge records it; an absent login reads ``read``.
        self.permissions: dict[str, str] = {}
        self._next_comment = 1000
        #: The forge's clock, the ``Date`` of every answer; an issue written is updated at it.
        self.now_http = NOW_HTTP
        #: Every call as ``METHOD path?query``, in order: what a test counts requests by.
        self.asked: list[str] = []
        #: ``pyproject.toml`` at every ref (default: it adopts the Actions review), ``pyproject_at`` overriding one ref.
        self.pyproject = '[tool.dev_lab.ci."review.yml"]\n'
        self.pyproject_at: dict[str, str | None] = {}  # ``None``: the file is absent at that ref

    def add_run(
        self, head: str, *, repo: str = 'o/r', event: str = 'pull_request_target',
        path: str = 'review.yml@refs/pull/1/head', conclusion: str = 'success',
    ) -> tuple[int, str]:  # fmt: skip
        """An Actions run of *repo* at *head*: its id (``GITHUB_RUN_ID``) and its web URL, as Gitea answers them.

        By default the base's review run (``pull_request_target``, ``review.yml@<ref>``) concluded ``success``;
        ``conclusion=''`` is a run still in progress.
        """
        run_id = 7000 + len(self.runs)
        url = f'https://{self.forge.host}/{repo}/actions/runs/{len(self.runs) + 1}'
        self.runs.append(
            {'id': run_id, 'head_sha': head, 'html_url': url, 'event': event, 'path': path, 'conclusion': conclusion}
        )
        return run_id, url

    def _runs(self, query: dict[str, str]) -> dict[str, Any]:
        mine = [r for r in self.runs if f'/{self.forge.owner}/{self.forge.repo}/' in r['html_url']]
        listed = [r for r in mine if r['head_sha'] == query.get('head_sha', r['head_sha'])][::-1]  # newest first
        return {'workflow_runs': listed, 'total_count': len(listed)}

    def _contents(self, ref: str) -> dict[str, Any]:
        text = self.pyproject_at.get(ref, self.pyproject)
        if text is None:
            missing = Attempt(1, 404, 'not found', Diagnosis.UNCLASSIFIED)
            raise ForgeCallFailed(Report(('GET', 'contents'), (missing,), 1))
        return {'content': base64.b64encode(text.encode()).decode()}

    def _number(self) -> int:
        """Issues and pulls share one number space, as on both forges."""
        return max([*self.issues_by_number, *self.pulls], default=0) + 1

    def add_pull(self, head: str, base: str, *, title: str = 't', body: str = '', sha: str = '') -> int:
        number = self._number()
        self.pulls[number] = {
            'number': number,
            'title': title,
            'state': 'open',
            'merged': False,
            'body': body,
            'html_url': f'https://{self.forge.host}/o/r/pulls/{number}',
            'user': {'login': 'a'},
            'head': {'ref': head, 'sha': sha},
            'base': {'ref': base},
        }
        self.comments[number] = []
        return number

    def add_issue(self, title: str, body: str = '', *, state: str = 'open', **extra: object) -> int:
        number = self._number()
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
            'updated_at': self._updated(),
        } | extra
        self.comments[number] = []
        return number

    def _updated(self) -> str:
        return parsedate_to_datetime(self.now_http).astimezone(UTC).isoformat()

    def titled(self, title: str, state: str = 'open') -> list[int]:
        return [n for n, i in self.issues_by_number.items() if i['title'] == title and i['state'] == state]

    @staticmethod
    def _page(items: list[dict[str, Any]], query: dict[str, str]) -> list[dict[str, Any]]:
        size = int(query.get('limit', '30'))
        page = int(query.get('page', '1'))
        return items[(page - 1) * size : page * size]

    def _shape(self, route: str) -> tuple[str, str]:
        """The route's kind and the key in it (a number or a sha; ``''`` when none)."""
        api = self.repo
        fixed = {
            f'{self.backend.api_root}/user': 'user',
            api: 'repo',
            f'{api}/issues': 'issues',
            f'{api}/pulls': 'pulls',
            f'{api}/actions/runs': 'runs',
        }
        if route in fixed:
            return fixed[route], ''
        for prefix, kind in (
            (f'{api}/actions/runs/', 'run'),
            (f'{api}/contents/', 'contents'),
            (f'{api}/statuses/', 'statuses'),
            (f'{api}/git/refs/heads/', 'ref'),
            (f'{api}/collaborators/', 'permission'),  # the key is ``<quoted login>/permission``
        ):
            if route.startswith(prefix):
                return kind, route.removeprefix(prefix)
        if route.startswith(f'{api}/commits/') and route.endswith('/statuses'):  # GitHub's list, with creators
            return 'statuses', route.removeprefix(f'{api}/commits/').removesuffix('/statuses')
        if route.startswith(f'{api}/pulls/'):
            number, _, tail = route.removeprefix(f'{api}/pulls/').partition('/')
            return ('merge' if tail == 'merge' else 'pull'), number
        head, _, tail = route.removeprefix(f'{api}/issues/').partition('/')
        if head == 'comments':
            return 'comment', tail
        return ('comments' if tail == 'comments' else 'issue'), head

    def _listed(self, query: dict[str, str]) -> list[dict[str, Any]]:
        if self.fail_lists:
            failed = Attempt(1, 502, 'bad gateway', Diagnosis.UNCLASSIFIED)
            raise ForgeCallFailed(Report(('GET', 'issues'), (failed,), 1))
        state = query.get('state', 'open')
        since = datetime.fromisoformat(query['since']) if 'since' in query else None
        newest = sorted(self.issues_by_number.items(), reverse=True)
        listed = [
            i | {'comments': len(self.comments[n])}
            for n, i in newest
            if state in ('all', i['state']) and (since is None or datetime.fromisoformat(i['updated_at']) >= since)
        ]
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

    def _pulls_listed(self, query: dict[str, str]) -> list[dict[str, Any]]:
        state = query.get('state', 'open')
        return self._page([p for _, p in sorted(self.pulls.items()) if state in ('all', p['state'])], query)

    def _create_pull(self, body: dict[str, Any]) -> dict[str, Any]:
        number = self.add_pull(body['head'], body['base'], title=body['title'], body=body['body'])
        return self.pulls[number]

    def _edit_pull(self, number: int, body: dict[str, Any]) -> dict[str, Any]:
        self.pulls[number] |= body
        return self.pulls[number]

    def _merge(self, number: int, body: dict[str, Any]) -> None:
        self.merges.append((number, body))
        self.pulls[number] |= {'state': 'closed', 'merged': True}

    def _merge_github(self, number: int, body: dict[str, Any]) -> dict[str, Any]:
        """GitHub refuses a merge pinned to a sha that is no longer the PR head (409)."""
        if body.get('sha') != self.pulls[number]['head']['sha']:
            moved = Attempt(
                1, 409, 'Head branch was modified. Review and try the merge again.', Diagnosis.FORGE_REFUSED
            )
            raise ForgeCallFailed(Report(('PUT', 'merge'), (moved,), 1))
        self._merge(number, body)
        return {'merged': True}

    def _post_status(self, sha: str, body: dict[str, Any]) -> dict[str, Any]:
        """Gitea keeps every post, answering the state as ``status``; ids ascend across the forge."""
        self._next_comment += 1
        # Gitea records a job token's status as its Actions ghost (user -2) and answers ``"creator": null``, while
        # the same token's comments name its Actions user (D11, measured 2026-11-01).
        creator = None if self.login == GITEA_ACTIONS_LOGIN else {'login': self.login}
        made = {'id': self._next_comment, 'status': body['state'], 'creator': creator} | body
        self.statuses.setdefault(sha, []).append(made)
        return made

    def _permission(self, key: str) -> str:
        return self.permissions.get(urllib.parse.unquote(key.removesuffix('/permission')), 'read')

    def _delete_comment(self, comment_id: int) -> None:
        for listed in self.comments.values():
            listed[:] = [c for c in listed if c['id'] != comment_id]

    def _delete(self, number: int) -> None:
        if self.deny_delete:  # gitea answers a non-admin token 403
            refused = Attempt(1, 403, 'token does not have at least one of required scope(s)', Diagnosis.FORGE_REFUSED)
            raise ForgeCallFailed(Report(('DELETE', 'issue'), (refused,), 1))
        del self.issues_by_number[number]

    def _edit_issue(self, number: int, body: dict[str, Any]) -> dict[str, Any]:
        self.issues_by_number[number] |= body | {'updated_at': self._updated()}
        return self.issues_by_number[number]

    def call(self, method: str, path: str, body: object = None, durable: object = None) -> object:
        """Answer from the in-memory state, as gitea would; a create needs no read-back here."""
        del durable
        self.answered = self.now_http
        self.asked.append(f'{method} {path}')
        route, _, raw_query = path.partition('?')
        query = dict(urllib.parse.parse_qsl(raw_query))
        sent: dict[str, Any] = body if isinstance(body, dict) else {}
        kind, key = self._shape(route)
        number = int(key) if key.isdigit() else 0
        opened = sum(i['state'] == 'open' for i in self.issues_by_number.values())
        handlers = {
            ('GET', 'user'): lambda: {'login': self.login},
            ('GET', 'permission'): lambda: {'permission': self._permission(key)},
            ('GET', 'runs'): lambda: self._runs(query),
            ('GET', 'contents'): lambda: self._contents(query['ref']),
            ('GET', 'run'): lambda: next(r for r in self.runs if r['id'] == number),
            ('GET', 'repo'): lambda: {
                'open_issues_count': opened,
                'open_pr_counter': 0,
                'has_pull_requests': True,
                'private': self.private,
                'default_branch': self.default_branch,
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
            ('GET', 'pulls'): lambda: self._pulls_listed(query),
            ('POST', 'pulls'): lambda: self._create_pull(sent),
            ('GET', 'pull'): lambda: self.pulls[number],
            ('PATCH', 'pull'): lambda: self._edit_pull(number, sent),
            ('POST', 'merge'): lambda: self._merge(number, sent),
            ('PUT', 'merge'): lambda: self._merge_github(number, sent),
            ('DELETE', 'ref'): lambda: self.deleted_refs.append(key),
            ('GET', 'statuses'): lambda: self.statuses.get(key, []),
            ('POST', 'statuses'): lambda: self._post_status(key, sent),
        }
        return handlers[method, kind]()
