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
credential -- is :mod:`dev_lab.dev.forgefailure`. A 401/403 is MEASURED before it is named: the same credential
is asked ``GET /user`` (:meth:`Client._diagnosis`).
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
from typing import Any, Final

import lab_commons.launch as _door

from dev_lab.dev import forge as _forge
from dev_lab.dev._forge_journal import (
    LOOKBACK,
    Durable,
    Journal,
    Probe,
    Write,
    journal_for,
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
    _GIT,
    _GIT_TIMEOUT_S,
    Forge,
    Transport,
    forge_from_remote,
    forge_of_url,
    forge_transport,
)
from dev_lab.dev.forgefailure import HTTP_ERROR_FLOOR, UNAUTHENTICATED, ForgeCallFailed, diagnose
from dev_lab.dev.netverb import DEFAULT_ATTEMPTS, DEFAULT_BACKOFF_S, Attempt, Diagnosis, Report

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
    'provenance',
    'pull_of',
    'stored_client',
]

#: What GitHub answers a workflow job token asking `/user`: only this answer, from GitHub, names the Actions bot.
_INTEGRATION: Final = 'Resource not accessible by integration'

#: The separator in the provenance line, spelled once.
_DOT: Final = ' · '


def provenance(cwd: Path, env: Mapping[str, str]) -> str | None:
    """``[<machine> · <agent> · <branch>]`` when both HARNESS vars are set, else ``None``."""
    machine, agent = env.get('HARNESS_MACHINE', ''), env.get('HARNESS_AGENT', '')
    if not machine or not agent:
        return None
    done = _door.run(
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
    #: Given the refused ``(username, token)``, the credential git's store hands out AFTER refreshing it
    #: (:func:`dev_lab.dev.forgecred.refresh_credential`); :func:`stored_client` sets it. Asked once per client.
    refresh: Callable[[str, str], tuple[str, str]] | None = None
    #: Where this repository's read caches live (:func:`dev_lab.dev.forgepulls.issues`); :func:`client_for`
    #: sets it -- ``None`` reads everything afresh.
    cache_dir: Path | None = None
    #: Whether :attr:`refresh` was spent, and whether it left the store empty.
    _refreshed: bool = dataclasses.field(default=False, init=False, repr=False)
    _gone: bool = dataclasses.field(default=False, init=False, repr=False)
    _kept: bool = dataclasses.field(default=False, init=False, repr=False)

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
            sent = {'Authorization': auth, 'Content-Type': content_type, 'User-Agent': _forge.user_agent(self.forge)}
            sent |= dict(backend.headers)
            conn.request(method, path, body=data, headers=sent)
            response = conn.getresponse()
            self.answered = response.getheader('Date') or self.answered
            return response.status, response.read()
        finally:
            conn.close()

    def _diagnosis(self, status: int, text: str, path: str) -> Diagnosis:
        """:func:`~dev_lab.dev.forgefailure.diagnose`, but a 401/403 is MEASURED against ``GET /user`` first.

        Refused only when ``GET /user`` refuses the credential too.

        The incident (2026-10-18): one 401 was read as "permanent, re-store the credential" while ``git
        credential fill`` held a credential that authenticated minutes later. A check that cannot be made
        (dropped, 5xx) is not evidence against the credential, so the attempt stays transient.
        """
        if status not in _forge.AUTH_REFUSED:
            return diagnose(status, text)
        user = f'{self.backend.api_root}/user'
        if path != user:
            try:
                status, _ = self._once('GET', user, None, 'application/json', None)
            except OSError:
                return Diagnosis.TRANSIENT
        if status not in _forge.AUTH_REFUSED:
            return Diagnosis.TRANSIENT
        return Diagnosis.TRANSIENT if status == UNAUTHENTICATED and self._refresh() else Diagnosis.FORGE_REFUSED

    def _refresh(self) -> bool:
        """Refresh the refused credential once, as git does after a 401; whether a DIFFERENT one came back.

        An expired OAuth access token is the usual 401 (``docs-src/dev/forge.md#credentials``); the refreshed
        one is sent on the retry. A store left empty is recorded, so the failure names the one re-login case.
        """
        if self.refresh is None or self._refreshed:
            return False
        self._refreshed = True
        try:
            username, token = self.refresh(self.username, self.token)
        except _forge.NoCredential:
            self._gone = True
            return False
        if token == self.token:
            self._kept = self.username != _forge.REFRESHABLE_USER
            return False
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

        Not retried and not JSON: the caller verifies what it got (:mod:`dev_lab.dev.artefacts` checks sha256).
        """
        parts = urllib.parse.urlsplit(url)
        path = parts.path + (f'?{parts.query}' if parts.query else '')
        status, payload = self._once('GET', path, None, 'application/octet-stream', parts.netloc or None)
        if not 0 < status < HTTP_ERROR_FLOOR:
            text = payload.decode(errors='replace')[:300]
            raise ForgeCallFailed(
                Report(('GET', path), (Attempt(1, status or 1, text, self._diagnosis(status, text, path)),), 1)
            )
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
            if 0 < status < HTTP_ERROR_FLOOR:
                return json.loads(payload) if payload else None
            text = payload.decode(errors='replace')[:300]
            made.append(Attempt(index, status or 1, text, self._diagnosis(status, text, write.path)))
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
        report = Report((write.method, write.path), tuple(made), DEFAULT_ATTEMPTS)
        raise ForgeCallFailed(report, credential_gone=self._gone, credential_kept=self._kept)

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
) -> Client:
    """The client for *root*'s *remote* (or another repository's *url*), its token and provenance stamp.

    A *token* given is the job token a workflow handed over by file (the review door, :mod:`reviewgitauth`).
    """
    forge = forge_of_url(url) if url else forge_from_remote(root, remote=remote)
    stamp = provenance(root, os.environ if env is None else env)
    built = stored_client(
        forge, cwd=root, env=env, transport=transport, stamp=stamp, journal=journal_for(root), token=token
    )
    built.cache_dir = outbox_dir(root)
    return built


def stored_client(
    forge: Forge,
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    transport: Transport = forge_transport,
    stamp: str | None = None,
    journal: Journal | None = None,
    token: str = '',
) -> Client:
    """A client presenting the credential git's store holds for *forge*, refreshed as git does on a 401.

    Inside a workflow job on the forge's own Actions the job token is the credential, never refreshed: the
    *token* given, else the job's env (:func:`actions_token`).

    Raises:
        NoCredential: the store holds no credential for the host.

    """
    if job := token or actions_token(forge, os.environ if env is None else env):
        return Client(
            forge, job, transport=transport, username=backend_for(forge).actions_login, stamp=stamp, journal=journal
        )
    username, secret = _forge.credential_for(forge.host, cwd=cwd, env=env)

    def refresh(refused_user: str, refused: str) -> tuple[str, str]:
        return _forge.refresh_credential(forge.host, (refused_user, refused), cwd=cwd, env=env)

    return Client(forge, secret, transport=transport, username=username, stamp=stamp, journal=journal, refresh=refresh)
