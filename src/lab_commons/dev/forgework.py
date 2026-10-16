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

THE CREDENTIAL ROUTE IS THE ONE :mod:`lab_commons.dev.forge` ALREADY USES, AND ONLY IT -- ``git
credential fill`` for the host (user ruling 2026-10-09: the person's own credential, never a global
token variable a process tree inherits). Nothing is written to disk and the token never reaches output.

RETRY, THEN REPORT, IN NETVERB'S VOCABULARY. Every call is bounded by
:data:`~lab_commons.dev.netverb.DEFAULT_ATTEMPTS` and its outcome is a
:class:`~lab_commons.dev.netverb.Report`, so an HTTP failure reads exactly like a failed ``git
push``. An ANSWERED 4xx is a refusal and is never repeated (a 401, 408 or 429 stays retryable, as the
table says); a 5xx or a dropped connection is retried. A create whose response was lost may still
have landed, so before a create is RETRIED the newest objects are read back and the token's own
identical one created since the attempt began is returned instead (:class:`~lab_commons.dev._forge_journal.Probe`);
when that read itself fails the create is reported rather than sent blind a second time.

PROVENANCE IS A GENERIC ENVIRONMENT CONTRACT. When ``HARNESS_MACHINE`` and ``HARNESS_AGENT`` are both
set, every created issue body, PR body and comment opens with ``[<machine> · <agent> · <branch>]``
(the branch omitted on a detached HEAD). Absent either, nothing is added: a human writes unmarked.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import subprocess
import time
import urllib.parse
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from lab_commons.dev import forge as _forge
from lab_commons.dev._forge_journal import LOOKBACK, Durable, Journal, Probe, Write, journal_for, since, write_key
from lab_commons.dev._forgebackends import GITEA, GITHUB, GITHUB_HOST, Backend, backend_for
from lab_commons.dev.forge import _GIT, _GIT_TIMEOUT_S, Forge, Transport, forge_from_remote, https_transport
from lab_commons.dev.netverb import DEFAULT_ATTEMPTS, DEFAULT_BACKOFF_S, Attempt, Diagnosis, Report, classify

__all__ = [
    'GITEA',
    'GITHUB',
    'GITHUB_HOST',
    'Backend',
    'Client',
    'Comment',
    'ForgeCallFailed',
    'Issue',
    'PullRequest',
    'backend_for',
    'client_for',
    'comment_of',
    'is_pull',
    'provenance',
    'pull_of',
]

#: Statuses below this are answers; at or above it the call failed.
_HTTP_ERROR_FLOOR: Final = 400

#: The 5xx floor: a server error, which a later attempt may clear.
_HTTP_SERVER_FLOOR: Final = 500

#: 4xx statuses that are NOT a refusal of the request itself: timeout and rate limit clear by waiting.
_HTTP_RETRYABLE_4XX: Final = frozenset({408, 429})


def is_pull(raw: Mapping[str, Any]) -> bool:
    """Whether a listed issue is a pull request: its ``pull_request`` is not null -- even `{}` marks a pull.

    Gitea sends ``"pull_request": null`` on every plain issue, so testing the key's presence read
    every issue as a pull: ``issue list`` printed nothing and the hosts lookup found no issue and
    opened a new one every tick (128 ``forge hosts`` issues on three repos, 2026-10-12).
    """
    return raw.get('pull_request') is not None


#: The separator in the provenance line, spelled once.
_DOT: Final = ' · '


class ForgeCallFailed(OSError):
    """A forge call that did not succeed within the bound; :attr:`report` is netverb's report of it."""

    def __init__(self, report: Report) -> None:
        """Carry the report; the message is its derived remedy, plus the auth remedy on a 401/403."""
        last = report.attempts[-1].returncode if report.attempts else 0
        super().__init__(f'{report.remedy}. {_forge.AUTH_REMEDY}' if last in _forge.AUTH_REFUSED else report.remedy)
        self.report = report


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
    )


def comment_of(raw: Mapping[str, Any]) -> Comment:
    """A forge's comment JSON as a :class:`Comment`."""
    return Comment(raw['id'], raw.get('body') or '', raw['html_url'], (raw.get('user') or {}).get('login', ''))


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
    """Read through netverb's table first; an answered 4xx it does not know is a refusal, never a transient.

    A 401/403 from the API is an ANSWER about the presented credential and is refused before the
    table is read: the table's 401-is-transient row was measured on ``git`` (a credential helper
    mid-flight), and an API call's header is fixed, so asking again cannot change the answer.
    """
    if status in _forge.AUTH_REFUSED:
        return Diagnosis.FORGE_REFUSED
    found = classify(f'error: {status} {text}')
    answered = _HTTP_ERROR_FLOOR <= status < _HTTP_SERVER_FLOOR and status not in _HTTP_RETRYABLE_4XX
    return Diagnosis.FORGE_REFUSED if found is Diagnosis.UNCLASSIFIED and answered else found


@dataclass
class Client:
    """The seven verbs against one repository. *stamp* is the provenance line, or ``None``."""

    forge: Forge
    token: str
    transport: Transport = https_transport
    username: str = ''
    stamp: str | None = None
    sleep: Callable[[float], None] = time.sleep
    timeout: float = 30.0
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    #: The raw ``Date`` header of the forge's latest answer: its clock (:func:`lab_commons.dev.forgeclaim.forge_now`).
    answered: str = ''
    #: The outbox journal each write is recorded in before it is attempted (:mod:`lab_commons.dev._forge_journal`);
    #: :func:`client_for` always sets it -- ``None`` only where a test drives the bare door.
    journal: Journal | None = None

    @property
    def backend(self) -> Backend:
        """The backend this repository's host selects."""
        return backend_for(self.forge)

    def _once(
        self, method: str, path: str, data: bytes | None, content_type: str, host: str | None
    ) -> tuple[int, bytes]:
        backend = self.backend
        auth = _forge.authorization(self.username, self.token, backend.auth_scheme)
        conn = self.transport(host or backend.host(self.forge), self.timeout)
        try:
            sent = {'Authorization': auth, 'Content-Type': content_type} | dict(backend.headers)
            conn.request(method, path, body=data, headers=sent)
            response = conn.getresponse()
            self.answered = response.getheader('Date') or self.answered
            return response.status, response.read()
        finally:
            conn.close()

    @property
    def repo(self) -> str:
        """The repository's API collection path, which every verb's path starts with."""
        return self.backend.repo_path(self.forge)

    def call(
        self, method: str, path: str, body: Mapping[str, Any] | None = None, durable: Durable | None = None
    ) -> Any:  # noqa: ANN401 -- JSON
        """One REST call, journaled when it writes, retried then reported: the door every verb uses.

        *durable* says how a write is keyed, read back and replayed (:class:`~lab_commons.dev._forge_journal.Durable`).
        """
        data = json.dumps(dict(body)).encode() if body is not None else None
        return self._request(method, path, data, 'application/json', durable)

    def upload(self, path: str, *, field: str, filename: str, content: bytes, durable: Durable | None = None) -> Any:  # noqa: ANN401 -- JSON
        """A ``multipart/form-data`` POST of one file under *field*; its boundary is its content's hash (one key)."""
        boundary = f'lab-commons-{hashlib.sha256(content).hexdigest()[:32]}'
        head = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
            'Content-Type: application/octet-stream\r\n\r\n'
        ).encode()
        data = head + content + f'\r\n--{boundary}--\r\n'.encode()
        return self._request('POST', path, data, f'multipart/form-data; boundary={boundary}', durable)

    def upload_raw(self, host: str, path: str, *, content: bytes, durable: Durable | None = None) -> Any:  # noqa: ANN401 -- JSON
        """A raw ``application/octet-stream`` POST to *host* -- GitHub's release-asset upload shape."""
        return self._request('POST', path, content, 'application/octet-stream', durable, host=host)

    def resend(self, write: Write) -> Any:  # noqa: ANN401 -- JSON
        """Send a journaled *write* again exactly as first sent, not journaling it twice (the outbox replay)."""
        return self._attempts(write, write.body)

    def download(self, url: str) -> bytes:
        """The raw bytes at an attachment's download *url*, fetched with this client's credential.

        Not retried and not JSON: the caller verifies what it got (:mod:`lab_commons.dev.artefacts` checks sha256).
        """
        parts = urllib.parse.urlsplit(url)
        path = parts.path + (f'?{parts.query}' if parts.query else '')
        status, payload = self._once('GET', path, None, 'application/octet-stream', parts.netloc or None)
        if not 0 < status < _HTTP_ERROR_FLOOR:
            text = payload.decode(errors='replace')[:300]
            raise ForgeCallFailed(Report(('GET', path), (Attempt(1, status or 1, text, _diagnose(status, text)),), 1))
        return payload

    def _request(
        self, method: str, path: str, data: bytes | None, content_type: str, durable: Durable | None, *, host: str = ''
    ) -> Any:  # noqa: ANN401 -- JSON
        """A write (never a read) is journaled BEFORE it is attempted and acknowledged once the forge answered."""
        intent = durable or Durable()
        key = intent.key or write_key(method, host, path, data or b'')
        write = Write(key, method, path, content_type, data or b'', host, intent.probe, time.time(), intent.until)
        if method == 'GET' or self.journal is None:
            return self._attempts(write, data)
        write = self.journal.record(write)
        answer = self._attempts(write, data)  # a failure stays journaled
        self.journal.ack(key)
        return answer

    def _attempts(self, write: Write, data: bytes | None) -> Any:  # noqa: ANN401 -- JSON
        """*data* sent as *write* until answered; before each retry a create's probe asks if the lost attempt landed."""
        made: list[Attempt] = []
        for index in range(1, DEFAULT_ATTEMPTS + 1):
            try:
                status, payload = self._once(write.method, write.path, data, write.content_type, write.host or None)
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
                if write.probe is not None:
                    try:
                        found = self.landed(write)
                    except ForgeCallFailed:
                        break  # whether it landed is unknowable, and a blind retry may duplicate it
                    if found is not None:
                        return found
        raise ForgeCallFailed(Report((write.method, write.path), tuple(made), DEFAULT_ATTEMPTS))

    def landed(self, write: Write) -> Any:  # noqa: ANN401 -- JSON
        """The object *write* made under this login, if it landed though its answer was lost; else ``None``."""
        if write.probe is None:
            return None
        listed = self.call('GET', write.probe.path)
        return write.probe.landed(listed, after=write.queued_at, login=self.whoami())

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
        return tuple(_issue(raw) for raw in listed if not is_pull(raw))

    def issue_view(self, number: int) -> Issue:
        """One issue."""
        return _issue(self.call('GET', f'{self.repo}/issues/{number}'))

    def issue_create(self, title: str, body: str) -> Issue:
        """A new issue; the body carries the provenance line."""
        payload = {'title': title, 'body': self._stamped(body)}
        probe = Probe(self._recent('issues'), payload)
        return _issue(self.call('POST', f'{self.repo}/issues', payload, Durable(probe=probe)))

    def issue_comment(self, number: int, body: str) -> Comment:
        """A comment on an issue (or a PR, which both forges number as an issue)."""
        path, payload = f'{self.repo}/issues/{number}/comments', {'body': self._stamped(body)}
        probe = Probe(f'{path}?since={since(self.clock())}', payload)
        return comment_of(self.call('POST', path, payload, Durable(probe=probe)))

    def issue_edit(self, number: int, body: str) -> Issue:
        """Replace an issue's body; the body is state, so no provenance line is added."""
        return _issue(self.call('PATCH', f'{self.repo}/issues/{number}', {'body': body}))

    def issue_close(self, number: int) -> Issue:
        """Close an issue; nothing is written but the state."""
        return _issue(self.call('PATCH', f'{self.repo}/issues/{number}', {'state': 'closed'}))

    def pr_create(self, title: str, body: str, *, head: str, base: str) -> PullRequest:
        """A new pull request from *head* into *base*."""
        payload = {'title': title, 'body': self._stamped(body), 'head': head, 'base': base}
        probe = Probe(self._recent('pulls'), {'title': title, 'body': payload['body']})
        return pull_of(self.call('POST', f'{self.repo}/pulls', payload, Durable(probe=probe)))

    def pr_view(self, number: int) -> PullRequest:
        """One pull request."""
        return pull_of(self.call('GET', f'{self.repo}/pulls/{number}'))


def client_for(
    root: Path, *, env: Mapping[str, str] | None = None, transport: Transport = https_transport, remote: str = 'origin'
) -> Client:
    """The client for *root*'s *remote*, its token and its provenance stamp -- what every CLI verb builds."""
    forge = forge_from_remote(root, remote=remote)
    stamp = provenance(root, os.environ if env is None else env)
    username, secret = _forge.credential_for(forge.host, cwd=root, env=env)
    return Client(forge, secret, transport=transport, username=username, stamp=stamp, journal=journal_for(root))
