"""Issue and pull-request collaboration on the forge, with NO dependency on ``gh`` or ``tea``.

WHY HERE AND NOT A BINARY. An agent that files an issue or opens a PR needs the same handful of verbs
on every box, and a host CLI is one more thing installed, authenticated and version-skewed per
machine -- differently for each forge. The REST shapes are small and stable, so the verbs live in the
leaf every repo already installs: ``issue list|view|create|comment|close`` and ``pr create|view``,
nothing more.

TWO BACKENDS, ONE RESULT. :func:`backend_for` reads the host already derived from ``origin`` by
:func:`lab_commons.dev.forge.forge_from_remote`: ``github.com`` is GitHub, every other host is the
Gitea-shaped forge that module already speaks. Results are normalized into :class:`Issue`,
:class:`Comment` and :class:`PullRequest`, so a caller never branches on which forge answered.

THE CREDENTIAL ROUTE IS THE ONE :mod:`lab_commons.dev.forge` ALREADY USES -- ``git credential fill``
for the host -- preceded by the forge's conventional environment variable (``GITEA_TOKEN``;
``GH_TOKEN`` then ``GITHUB_TOKEN``). Nothing is written to disk and the token never reaches output.

RETRY, THEN REPORT, IN NETVERB'S VOCABULARY. Every call is bounded by
:data:`~lab_commons.dev.netverb.DEFAULT_ATTEMPTS` and its outcome is a
:class:`~lab_commons.dev.netverb.Report`, so an HTTP failure reads exactly like a failed ``git
push``. An ANSWERED 4xx is a refusal and is never repeated (a 401, 408 or 429 stays retryable, as the
table says); a 5xx or a dropped connection is retried. A create whose response was lost may still
have landed, so before a create is RETRIED the newest objects are read back and the token's own
identical one from the last few minutes is returned instead (:mod:`lab_commons.dev._forge_landed`);
when that read itself fails the create is reported rather than sent blind a second time.

PROVENANCE IS A GENERIC ENVIRONMENT CONTRACT. When ``HARNESS_MACHINE`` and ``HARNESS_AGENT`` are both
set, every created issue body, PR body and comment opens with ``[<machine> · <agent> · <branch>]``
(the branch omitted on a detached HEAD). Absent either, nothing is added: a human writes unmarked.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from lab_commons.dev._forge_landed import LOOKBACK, find_landed, since
from lab_commons.dev.forge import _GIT, _GIT_TIMEOUT_S, Forge, Transport, forge_from_remote, https_transport, token_for
from lab_commons.dev.netverb import DEFAULT_ATTEMPTS, DEFAULT_BACKOFF_S, Attempt, Diagnosis, Report, classify
from lab_commons.log import emit

__all__ = [
    'CREDENTIAL_SOURCE',
    'GITEA',
    'GITHUB',
    'Backend',
    'Client',
    'Comment',
    'ForgeCallFailed',
    'Issue',
    'PullRequest',
    'backend_for',
    'client_for',
    'main',
    'provenance',
    'token_route',
    'token_source',
]

#: The one host that is GitHub. Every other host is treated as the Gitea-shaped forge.
GITHUB_HOST: Final = 'github.com'

#: Statuses below this are answers; at or above it the call failed.
_HTTP_ERROR_FLOOR: Final = 400

#: The 5xx floor: a server error, which a later attempt may clear.
_HTTP_SERVER_FLOOR: Final = 500

#: 4xx statuses that are NOT a refusal of the request itself: timeout and rate limit clear by waiting.
_HTTP_RETRYABLE_4XX: Final = frozenset({408, 429})

#: A create's read-back before a retry -- its own landed object, or ``None`` -- or no read-back at all.
_Found = Callable[[], Any] | None

#: The separator in the provenance line, spelled once.
_DOT: Final = ' · '


class ForgeCallFailed(OSError):
    """A forge call that did not succeed within the bound; :attr:`report` is netverb's report of it."""

    def __init__(self, report: Report) -> None:
        """Carry the report; the message is its derived remedy."""
        super().__init__(report.remedy)
        self.report = report


@dataclass(frozen=True)
class Backend:
    """What differs between forges: where the API lives, how it authenticates, how it lists issues."""

    name: str
    api_root: str
    auth_scheme: str
    list_query: str
    token_vars: tuple[str, ...]
    fixed_host: str | None = None
    headers: tuple[tuple[str, str], ...] = ()
    page_param: str = 'limit'

    def host(self, forge: Forge) -> str:
        """The API host: GitHub's is fixed, a Gitea forge serves its API on its own host."""
        return self.fixed_host or forge.host

    def repo_path(self, forge: Forge) -> str:
        """The repository's API collection."""
        return f'{self.api_root}/repos/{forge.owner}/{forge.repo}'


GITEA: Final = Backend(
    name='gitea',
    api_root='/api/v1',
    auth_scheme='token',
    list_query='state={state}&type=issues&limit={limit}',
    token_vars=('GITEA_TOKEN',),
)

GITHUB: Final = Backend(
    name='github',
    api_root='',
    auth_scheme='Bearer',
    list_query='state={state}&per_page={limit}',
    token_vars=('GH_TOKEN', 'GITHUB_TOKEN'),
    fixed_host='api.github.com',
    page_param='per_page',
    headers=(
        ('Accept', 'application/vnd.github+json'),
        ('X-GitHub-Api-Version', '2022-11-28'),
        ('User-Agent', 'lab-commons-forgework'),
    ),
)


def backend_for(forge: Forge) -> Backend:
    """GitHub for ``github.com``, the Gitea-shaped forge for every other host."""
    return GITHUB if forge.host.lower() == GITHUB_HOST else GITEA


#: How :func:`token_source` names the fallback, so ``auth status`` can say where a token came from.
CREDENTIAL_SOURCE: Final = 'git credential'


def token_source(forge: Forge, *, cwd: Path, env: Mapping[str, str] | None = None) -> tuple[str, str]:
    """``(where, token)``: the backend's environment variable when set, else the git transport's credential.

    The credential is sent as a TOKEN header whichever helper stored it, so it must be a personal
    access token -- which is what ``python -m lab_commons.dev.forge auth login`` stores.
    """
    source = os.environ if env is None else env
    for name in backend_for(forge).token_vars:
        if source.get(name):
            return name, source[name]
    return CREDENTIAL_SOURCE, token_for(forge.host, cwd=cwd, env=env)


def token_route(forge: Forge, *, cwd: Path, env: Mapping[str, str] | None = None) -> str:
    """The token :func:`token_source` finds, without its provenance."""
    return token_source(forge, cwd=cwd, env=env)[1]


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


def _issue(raw: Mapping[str, Any]) -> Issue:
    return Issue(
        raw['number'], raw['title'], raw['state'], raw.get('body') or '', raw['html_url'], raw['user']['login']
    )


def _pull(raw: Mapping[str, Any]) -> PullRequest:
    issue = _issue(raw)
    return PullRequest(*dataclasses.astuple(issue), raw['head']['ref'], raw['base']['ref'])


def _comment(raw: Mapping[str, Any]) -> Comment:
    return Comment(raw['id'], raw.get('body') or '', raw['html_url'])


def provenance(cwd: Path, env: Mapping[str, str]) -> str | None:
    """``[<machine> · <agent> · <branch>]`` when both HARNESS vars are set, else ``None``."""
    machine, agent = env.get('HARNESS_MACHINE', ''), env.get('HARNESS_AGENT', '')
    if not machine or not agent:
        return None
    done = subprocess.run(
        [_GIT, 'symbolic-ref', '--short', '-q', 'HEAD'],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=_GIT_TIMEOUT_S,
        check=False,
    )
    branch = done.stdout.strip() if done.returncode == 0 else ''
    return '[' + _DOT.join(part for part in (machine, agent, branch) if part) + ']'


def _diagnose(status: int, text: str) -> Diagnosis:
    """Read through netverb's table first; an answered 4xx it does not know is a refusal, never a transient."""
    found = classify(f'error: {status} {text}')
    answered = _HTTP_ERROR_FLOOR <= status < _HTTP_SERVER_FLOOR and status not in _HTTP_RETRYABLE_4XX
    return Diagnosis.FORGE_REFUSED if found is Diagnosis.UNCLASSIFIED and answered else found


@dataclass
class Client:
    """The seven verbs against one repository. *stamp* is the provenance line, or ``None``."""

    forge: Forge
    token: str
    transport: Transport = https_transport
    stamp: str | None = None
    sleep: Callable[[float], None] = time.sleep
    timeout: float = 30.0
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    @property
    def backend(self) -> Backend:
        """The backend this repository's host selects."""
        return backend_for(self.forge)

    def _once(self, method: str, path: str, data: bytes | None) -> tuple[int, bytes]:
        backend = self.backend
        headers = {'Authorization': f'{backend.auth_scheme} {self.token}', 'Content-Type': 'application/json'}
        conn = self.transport(backend.host(self.forge), self.timeout)
        try:
            conn.request(method, path, body=data, headers=headers | dict(backend.headers))
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    @property
    def repo(self) -> str:
        """The repository's API collection path, which every verb's path starts with."""
        return self.backend.repo_path(self.forge)

    def call(self, method: str, path: str, body: Mapping[str, Any] | None = None, landed: _Found = None) -> Any:  # noqa: ANN401 -- JSON
        """One REST call, retried then reported: the door every verb -- here and in the sibling modules -- uses.

        *landed* is a create's read-back, run before each retry (see :mod:`lab_commons.dev._forge_landed`).
        """
        data = json.dumps(dict(body)).encode() if body is not None else None
        made: list[Attempt] = []
        for index in range(1, DEFAULT_ATTEMPTS + 1):
            try:
                status, payload = self._once(method, path, data)
            except OSError as exc:
                status, payload = 0, str(exc).encode()
            if 0 < status < _HTTP_ERROR_FLOOR:
                return json.loads(payload) if payload else None
            text = payload.decode(errors='replace')[:300]
            made.append(Attempt(index, status or 1, text, _diagnose(status, text)))
            if not made[-1].retryable:
                break
            if index < DEFAULT_ATTEMPTS:
                self.sleep(DEFAULT_BACKOFF_S)
                if landed is not None:
                    try:
                        found = landed()
                    except ForgeCallFailed:
                        break  # whether it landed is unknowable, and a blind retry may duplicate it
                    if found is not None:
                        return found
        raise ForgeCallFailed(Report((method, path), tuple(made), DEFAULT_ATTEMPTS))

    def _landed(self, path: str, **fields: str) -> Callable[[], Any]:
        """The read a create runs before each retry: its own object, if the lost attempt landed."""
        return lambda: find_landed(self.call('GET', path), login=self.whoami(), fields=fields, now=self.clock())

    def _recent(self, collection: str) -> str:
        return f'{self.repo}/{collection}?state=all&{self.backend.page_param}={LOOKBACK}'

    def _stamped(self, text: str) -> str:
        return text if self.stamp is None else f'{self.stamp}\n\n{text}'

    def whoami(self) -> str:
        """The login the token authenticates as -- ``GET /api/v1/user`` on Gitea, ``GET /user`` on GitHub."""
        return self.call('GET', f'{self.backend.api_root}/user')['login']

    def issue_list(self, *, state: str = 'open', limit: int = 30) -> tuple[Issue, ...]:
        """Issues in *state*, pull requests excluded (GitHub lists both under ``issues``)."""
        query = self.backend.list_query.format(state=state, limit=limit)
        listed = self.call('GET', f'{self.repo}/issues?{query}')
        return tuple(_issue(raw) for raw in listed if 'pull_request' not in raw)

    def issue_view(self, number: int) -> Issue:
        """One issue."""
        return _issue(self.call('GET', f'{self.repo}/issues/{number}'))

    def issue_create(self, title: str, body: str) -> Issue:
        """A new issue; the body carries the provenance line."""
        payload = {'title': title, 'body': self._stamped(body)}
        recent = self._landed(self._recent('issues'), **payload)
        return _issue(self.call('POST', f'{self.repo}/issues', payload, recent))

    def issue_comment(self, number: int, body: str) -> Comment:
        """A comment on an issue (or a PR, which both forges number as an issue)."""
        path, payload = f'{self.repo}/issues/{number}/comments', {'body': self._stamped(body)}
        recent = self._landed(f'{path}?since={since(self.clock())}', **payload)
        return _comment(self.call('POST', path, payload, recent))

    def issue_close(self, number: int) -> Issue:
        """Close an issue; nothing is written but the state."""
        return _issue(self.call('PATCH', f'{self.repo}/issues/{number}', {'state': 'closed'}))

    def pr_create(self, title: str, body: str, *, head: str, base: str) -> PullRequest:
        """A new pull request from *head* into *base*."""
        payload = {'title': title, 'body': self._stamped(body), 'head': head, 'base': base}
        recent = self._landed(self._recent('pulls'), title=title, body=payload['body'])
        return _pull(self.call('POST', f'{self.repo}/pulls', payload, recent))

    def pr_view(self, number: int) -> PullRequest:
        """One pull request."""
        return _pull(self.call('GET', f'{self.repo}/pulls/{number}'))


def _verb(group: argparse._SubParsersAction, name: str) -> argparse.ArgumentParser:
    sub = group.add_parser(name)
    sub.add_argument('--json', action='store_true', help='print the normalized result as JSON')
    return sub


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='lab_commons.dev.forge',
        description='issue and PR verbs on the forge',
        epilog='also: issue claim|status N, status post|list SHA; token: auth login|status',
    )
    nouns = parser.add_subparsers(dest='noun', required=True)
    issue = nouns.add_parser('issue').add_subparsers(dest='verb', required=True)
    listing = _verb(issue, 'list')
    listing.add_argument('--state', choices=('open', 'closed', 'all'), default='open')
    listing.add_argument('--limit', type=int, default=30)
    for name in ('view', 'close'):
        _verb(issue, name).add_argument('number', type=int)
    create = _verb(issue, 'create')
    create.add_argument('--title', required=True)
    create.add_argument('--body', default='')
    comment = _verb(issue, 'comment')
    comment.add_argument('number', type=int)
    comment.add_argument('--body', required=True)
    pr = nouns.add_parser('pr').add_subparsers(dest='verb', required=True)
    _verb(pr, 'view').add_argument('number', type=int)
    opened = _verb(pr, 'create')
    opened.add_argument('--title', required=True)
    opened.add_argument('--body', default='')
    opened.add_argument('--head', required=True)
    opened.add_argument('--base', required=True)
    return parser


def _dispatch(client: Client, args: argparse.Namespace) -> Issue | PullRequest | Comment | tuple[Issue, ...]:
    verbs: dict[tuple[str, str], Callable[[], Issue | PullRequest | Comment | tuple[Issue, ...]]] = {
        ('issue', 'list'): lambda: client.issue_list(state=args.state, limit=args.limit),
        ('issue', 'view'): lambda: client.issue_view(args.number),
        ('issue', 'create'): lambda: client.issue_create(args.title, args.body),
        ('issue', 'comment'): lambda: client.issue_comment(args.number, args.body),
        ('issue', 'close'): lambda: client.issue_close(args.number),
        ('pr', 'create'): lambda: client.pr_create(args.title, args.body, head=args.head, base=args.base),
        ('pr', 'view'): lambda: client.pr_view(args.number),
    }
    return verbs[args.noun, args.verb]()


def _render(item: Issue | PullRequest | Comment) -> str:
    if isinstance(item, Comment):
        return item.url
    return f'#{item.number} [{item.state}] {item.title}  {item.url}'


def client_for(root: Path, *, env: Mapping[str, str] | None = None, transport: Transport = https_transport) -> Client:
    """The client for *root*'s ``origin``, its token and its provenance stamp -- what every CLI verb builds."""
    forge = forge_from_remote(root)
    stamp = provenance(root, os.environ if env is None else env)
    return Client(forge, token_route(forge, cwd=root, env=env), transport=transport, stamp=stamp)


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    transport: Transport = https_transport,
) -> int:
    """``python -m lab_commons.dev.forge <noun> <verb> ...``; exit 1 with netverb's remedy on failure."""
    args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    client = client_for(Path.cwd() if cwd is None else cwd, env=env, transport=transport)
    try:
        result = _dispatch(client, args)
    except ForgeCallFailed as failed:
        emit(f'[forge] {failed.report.remedy}', err=True)
        emit(failed.report.attempts[-1].output, err=True)
        return 1
    items = result if isinstance(result, tuple) else (result,)
    if args.json:
        data = [dataclasses.asdict(item) for item in items]
        emit(json.dumps(data if isinstance(result, tuple) else data[0], indent=2))
    else:
        for item in items:
            emit(_render(item))
    return 0
