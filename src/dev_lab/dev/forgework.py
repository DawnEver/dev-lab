"""Issue and pull-request collaboration on the forge, with NO dependency on ``gh`` or ``tea``.

WHY HERE AND NOT A BINARY. An agent that files an issue or opens a PR needs the same handful of verbs
on every box, and a host CLI is one more thing installed, authenticated and version-skewed per
machine -- differently for each forge. The REST shapes are small and stable, so the verbs live in the
leaf every repo already installs: ``issue list|view|create|comment|close`` and ``pr create|view``,
nothing more.

TWO BACKENDS, ONE RESULT. :func:`backend_for` reads the host already derived from ``origin`` by
:func:`dev_lab.dev.forge.forge_from_remote`: ``github.com`` is GitHub, every other host is the
Gitea-shaped forge that module already speaks. Results are normalized into :class:`Issue`,
:class:`Comment` and :class:`PullRequest`, so a caller never branches on which forge answered.

THE CREDENTIAL ROUTE IS THE ONE :mod:`dev_lab.dev.forge` ALREADY USES, AND ONLY IT -- ``git
credential fill`` for the host (user ruling 2026-10-09: the person's own credential, never a global
token variable a process tree inherits). Nothing is written to disk and the token never reaches output.

RETRY, THEN REPORT, IN NETVERB'S VOCABULARY: how an answer reads -- success, transient, a refusal, a refused
credential, a rate limit -- and the one retry loop are :mod:`dev_lab.dev.forgefailure`. A 401/403 that is no rate
limit is MEASURED before it is named: the same credential is asked ``GET /user`` (:meth:`Client._diagnosis`).
A create whose response was lost may still have landed, so before a create is RETRIED the newest
objects are read back and the token's own identical one created since the attempt began is returned
instead (:class:`~dev_lab.dev._forge_journal.Probe`); when that read itself fails the create is
reported rather than sent blind a second time.

PROVENANCE IS A GENERIC ENVIRONMENT CONTRACT. When ``HARNESS_MACHINE`` and ``HARNESS_AGENT`` are both
set, every created issue body, PR body and comment opens with ``[<machine> · <agent> · <branch>]``
(the branch omitted on a detached HEAD). Absent either, nothing is added: a human writes unmarked.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import time
import urllib.parse
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, cast

from dev_lab.dev import forge as _forge
from dev_lab.dev._forge_journal import (
    LOOKBACK,
    Durable,
    Journal,
    Probe,
    Write,
    journal_at,
    outbox_dir,
    since,
    write_key,
)
from dev_lab.dev._forge_records import Comment, Issue, PullRequest, _issue, comment_of, draft_title, is_pull, pull_of
from dev_lab.dev._forgebackends import (
    ACTIONS_BOT,
    GITEA,
    GITEA_ACTIONS_LOGIN,
    GITHUB,
    GITHUB_HOST,
    Backend,
    actions_token,
    backend_for,
)
from dev_lab.dev.forge import (
    Forge,
    Transport,
    forge_from_remote,
    forge_of_url,
    forge_transport,
)
from dev_lab.dev.forgecred import CredentialRefresh
from dev_lab.dev.forgefailure import (
    HTTP_ERROR_FLOOR,
    RATE_HEADERS,
    UNAUTHENTICATED,
    Answer,
    ForgeCallFailed,
    diagnose,
    rate_limited,
    retried,
)
from dev_lab.dev.forgememo import ReadMemo
from dev_lab.dev.forgestamp import provenance
from dev_lab.dev.netverb import Attempt, Diagnosis, Report

__all__ = [
    'ACTIONS_BOT',
    'GITEA',
    'GITEA_ACTIONS_LOGIN',
    'GITHUB',
    'GITHUB_HOST',
    'Backend',
    'Client',
    'Comment',
    'Issue',
    'PullRequest',
    'backend_for',
    'client_for',
    'comment_of',
    'is_pull',
    'pull_of',
    'stored_client',
]

#: What GitHub answers a workflow job token asking `/user`: only this answer, from GitHub, names the Actions bot.
_INTEGRATION: Final = 'Resource not accessible by integration'

#: How many redirects a download follows: GitHub's artifact zip answers one, to a signed storage URL.
_REDIRECTS: Final = 3
_OCTETS: Final = 'application/octet-stream'


@dataclass
class Client:
    """The seven verbs against one repository. *stamp* is the provenance line, or ``None``."""

    forge: Forge
    token: str
    transport: Transport = forge_transport
    username: str = ''
    stamp: str | None = None
    sleep: Callable[[float], None] = time.sleep
    timeout: float = 30.0
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    #: The raw ``Date`` header of the forge's latest answer: its clock (:func:`dev_lab.dev.forgeclaim.forge_now`).
    answered: str = ''
    #: The outbox journal each write is recorded in before it is attempted (:mod:`dev_lab.dev._forge_journal`);
    #: :func:`client_for` always sets it -- ``None`` only where a test drives the bare door.
    journal: Journal | None = None
    #: Given the refused ``(username, token)``, the typed provider refresh/preservation outcome
    #: (:func:`dev_lab.dev.forgecred.refresh_credential`); :func:`stored_client` sets it. Asked once per client.
    refresh: Callable[[str, str], CredentialRefresh] | None = None
    #: Where this repository's read caches live (:func:`dev_lab.dev.forgepulls.issues`); :func:`client_for`
    #: sets it -- ``None`` reads everything afresh.
    cache_dir: Path | None = None
    #: The pass memo answering repeated GETs (:class:`~dev_lab.dev.forgememo.ReadMemo`); ``None`` reads afresh.
    memo: ReadMemo | None = None
    #: Whether :attr:`refresh` was spent, and whether the original credential was retained.
    _refreshed: bool = dataclasses.field(default=False, init=False, repr=False)
    _kept: bool = dataclasses.field(default=False, init=False, repr=False)
    #: The ``Location`` of the latest answer, ``''`` when it named none: where a redirect points.
    _location: str = dataclasses.field(default='', init=False, repr=False)

    @property
    def backend(self) -> Backend:
        """The backend this repository's host selects."""
        return backend_for(self.forge)

    def _once(
        self, method: str, path: str, data: bytes | None, content_type: str, host: str | None, *,
        accept: str = '', authed: bool = True,
    ) -> Answer:  # fmt: skip
        backend = self.backend
        auth = _forge.authorization(self.username, self.token, backend.auth_scheme)
        conn = self.transport(host or backend.host(self.forge), self.timeout)
        try:
            # authed: no credential follows a redirect; no token: an anonymous read of a public repo
            sent = {'Authorization': auth} if authed and self.token else {}
            sent |= {'Content-Type': content_type, 'User-Agent': _forge.user_agent(self.forge)} | dict(backend.headers)
            sent |= {'Accept': accept} if accept else {}
            conn.request(method, path, body=data, headers=sent)
            response = conn.getresponse()
            self.answered = response.getheader('Date') or self.answered
            self._location = response.getheader('Location') or ''
            said = {name: value for name in RATE_HEADERS if (value := response.getheader(name))}
            return Answer(response.status, response.read(), said)
        finally:
            conn.close()

    def _diagnosis(self, answer: Answer, text: str, path: str) -> Diagnosis:
        """:func:`~dev_lab.dev.forgefailure.diagnose`, but a 401/403 that is no rate limit is MEASURED first.

        Refused only when ``GET /user`` refuses the credential too. A rate limit is never measured: ``GET /user``
        is rate limited as well, and its 403 would name the credential (2026-11-05).

        The incident (2026-10-18): one 401 was read as "permanent, re-store the credential" while ``git
        credential fill`` held a credential that authenticated minutes later. A check that cannot be made
        (dropped, 5xx) is not evidence against the credential, so the attempt stays transient.
        """
        status = answer.status
        if status not in _forge.AUTH_REFUSED or rate_limited(status, text, answer.headers):
            return diagnose(status, text, answer.headers)
        user = f'{self.backend.api_root}/user'
        if path != user:
            try:
                status = self._once('GET', user, None, 'application/json', None).status
            except OSError:
                return Diagnosis.TRANSIENT
        if status not in _forge.AUTH_REFUSED:
            return Diagnosis.TRANSIENT
        return Diagnosis.TRANSIENT if status == UNAUTHENTICATED and self._refresh() else Diagnosis.FORGE_REFUSED

    def _refresh(self) -> bool:
        """Ask one verified provider refresh; unknown stores retain their credential, never erase it."""
        if self.refresh is None or self._refreshed:
            return False
        self._refreshed = True
        outcome = self.refresh(self.username, self.token)
        self._kept = outcome.state == 'kept'
        if self._kept:
            return False
        username, token = outcome.credential
        self.username, self.token = username, token
        return True

    @property
    def repo(self) -> str:
        """The repository's API collection path, which every verb's path starts with."""
        return self.backend.repo_path(self.forge)

    def call(
        self, method: str, path: str, body: Mapping[str, Any] | None = None, durable: Durable | None = None
    ) -> Any:  # noqa: ANN401 -- JSON
        """One REST call, journaled when it writes, retried then reported: the door every verb uses.

        *durable* says how a write is keyed, read back and replayed (:class:`~dev_lab.dev._forge_journal.Durable`).
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

        The caller verifies what it got (:mod:`dev_lab.dev.artefacts` checks sha256). A redirect (GitHub's artifact
        zip answers one, to a signed storage URL) is followed WITHOUT the credential, at most :data:`_REDIRECTS`
        times: the signed URL is its own authority, and the token never leaves the forge's API.
        """
        authed = True
        for _ in range(_REDIRECTS + 1):
            parts = urllib.parse.urlsplit(url)
            path = parts.path + (f'?{parts.query}' if parts.query else '')
            payload = self._raw('GET', path, host=parts.netloc or None, authed=authed)
            if not self._location:
                return payload
            url, authed = urllib.parse.urljoin(url, self._location), False
        refused = Attempt(1, HTTP_ERROR_FLOOR, f'more than {_REDIRECTS} redirects', Diagnosis.FORGE_REFUSED)
        raise ForgeCallFailed(Report(('GET', url), (refused,), 1))

    def pull_diff(self, number: int) -> str:
        """The forge's OWN unified diff of pull request *number* -- what a review bundle is checked against.

        Where and how it is asked for is the backend's (:attr:`~dev_lab.dev._forgebackends.Backend.diff_at`).
        """
        suffix, accept = self.backend.diff_at
        return self._raw('GET', f'{self.repo}/pulls/{number}{suffix}', accept=accept).decode('utf-8', 'replace')

    def _raw(self, method: str, path: str, *, host: str | None = None, accept: str = '', authed: bool = True) -> bytes:
        """One read's raw answer, not JSON, retried as every call is; a refusal raises :class:`ForgeCallFailed`."""
        answer = retried(
            (method, path),
            lambda: self._once(method, path, None, _OCTETS, host, accept=accept, authed=authed),
            diagnosis=lambda failed, text: self._diagnosis(failed, text, path),
            sleep=self.sleep,
            failed=lambda report: ForgeCallFailed(report, credential_kept=self._kept),
        )
        return cast('Answer', answer).payload  # no *landed*: only an Answer comes back

    def _request(
        self, method: str, path: str, data: bytes | None, content_type: str, durable: Durable | None, *, host: str = ''
    ) -> Any:  # noqa: ANN401 -- JSON
        """A write (never a read) is journaled BEFORE it is attempted and acknowledged once the forge answered."""
        intent = durable or Durable()
        key = intent.key or write_key(method, host, path, data or b'')
        write = Write(key, method, path, content_type, data or b'', host, intent.probe, time.time(), intent.until)
        if self.memo is not None and method == 'GET':
            return self.memo.read((host, path), lambda: self._attempts(write, data))
        if self.memo is not None:
            self.memo.clear()
        if method == 'GET' or self.journal is None:
            return self._attempts(write, data)
        write = self.journal.record(write)
        answer = self._attempts(write, data)  # a failure stays journaled
        self.journal.ack(key)
        return answer

    def _attempts(self, write: Write, data: bytes | None) -> Any:  # noqa: ANN401 -- JSON
        """*data* sent as *write* through :func:`~dev_lab.dev.forgefailure.retried`, a create's probe its *landed*."""
        got = retried(
            (write.method, write.path),
            lambda: self._once(write.method, write.path, data, write.content_type, write.host or None),
            diagnosis=lambda failed, text: self._diagnosis(failed, text, write.path),
            sleep=self.sleep,
            landed=None if write.probe is None else lambda: self.landed(write),
            failed=lambda report: ForgeCallFailed(report, credential_kept=self._kept),
        )
        if not isinstance(got, Answer):
            return got
        return json.loads(got.payload) if got.payload else None

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

    def can_write(self, login: str) -> bool:
        """Whether the forge records *login* with write permission on this repository (refused or unknown: no).

        ``GET .../collaborators/{login}/permission`` on both forges; the writing permissions are the backend's.
        """
        path = f'{self.repo}/collaborators/{urllib.parse.quote(login, safe="")}/permission'
        try:
            answer = self.call('GET', path)
        except ForgeCallFailed:
            return False
        return isinstance(answer, dict) and answer.get('permission') in self.backend.writer_permissions

    def whoami(self) -> str:
        """The login the token authenticates as -- ``GET /api/v1/user`` on Gitea, ``GET /user`` on GitHub.

        ALWAYS ASKED OF THE FORGE (D11): a GitHub workflow job token is refused ``/user`` as an integration, and
        only that answer FROM GITHUB makes it :data:`ACTIONS_BOT` -- never the username this process was built with.
        """
        try:
            return self.call('GET', f'{self.backend.api_root}/user')['login']
        except ForgeCallFailed as refused:
            said = refused.report.attempts[-1].output if refused.report.attempts else ''
            if self.backend is GITHUB and _INTEGRATION in said:
                return ACTIONS_BOT
            raise

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

    def pr_create(self, title: str, body: str, *, head: str, base: str, draft: bool) -> PullRequest:
        """A new pull request from *head* into *base*; a *draft* in the forge's own way (:mod:`dev_lab.dev.forgedraft`).

        GitHub takes ``draft: true``; Gitea has no draft field, and reads its ``WIP:`` title prefix as one.
        """
        if draft and self.backend is not GITHUB:
            title = draft_title(title)
        payload: dict[str, Any] = {'title': title, 'body': self._stamped(body), 'head': head, 'base': base}
        if draft and self.backend is GITHUB:
            payload['draft'] = True
        probe = Probe(self._recent('pulls'), {'title': title, 'body': payload['body']})
        return pull_of(self.call('POST', f'{self.repo}/pulls', payload, Durable(probe=probe)))

    def pr_view(self, number: int) -> PullRequest:
        """One pull request."""
        return pull_of(self.call('GET', f'{self.repo}/pulls/{number}'))


def client_for(
    root: Path,
    *,
    env: Mapping[str, str] | None = None,
    transport: Transport = forge_transport,
    remote: str = 'origin',
    url: str = '',
    token: str = '',
    outbox: Path | None = None,
) -> Client:
    """The client for *root*'s *remote* (or another repository's *url*), its token and provenance stamp.

    A *token* given is the job token a workflow handed over by file (the review door, :mod:`reviewgitauth`).
    Its journal and caches live in *outbox*: given by a role that holds no checkout (the judge's declared state),
    else *root*'s main checkout's (:func:`~dev_lab.dev._forge_journal.outbox_dir`).
    """
    forge = forge_of_url(url) if url else forge_from_remote(root, remote=remote)
    stamp = provenance(root, os.environ if env is None else env)
    built = stored_client(forge, cwd=root, env=env, transport=transport, stamp=stamp, token=token)
    built.cache_dir = outbox_dir(root) if outbox is None else outbox
    built.journal = journal_at(built.cache_dir)
    return built


def stored_client(
    forge: Forge,
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    transport: Transport = forge_transport,
    stamp: str | None = None,
    token: str = '',
) -> Client:
    """A client presenting the credential git's store holds for *forge*, refreshed as git does on a 401.

    Inside a workflow job on the forge's own Actions the job token is the credential, never refreshed: the
    *token* given, else the job's env (:func:`actions_token`).

    Raises:
        NoCredential: the store holds no credential for the host.

    """
    if job := token or actions_token(forge, os.environ if env is None else env):
        return Client(forge, job, transport=transport, username=backend_for(forge).actions_login, stamp=stamp)
    username, secret = _forge.credential_for(forge.host, cwd=cwd, env=env)

    def refresh(refused_user: str, refused: str) -> CredentialRefresh:
        return _forge.refresh_credential(forge.host, (refused_user, refused), cwd=cwd, env=env)

    return Client(forge, secret, transport=transport, username=username, stamp=stamp, refresh=refresh)
