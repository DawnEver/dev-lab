"""The Gitea admin a forge host runs: its declared accounts role, the CLI as the Gitea user, and the local API.

Split out of :mod:`dev_lab.ops.forgeaccounts` (2026-11-10, MODULE-SIZE-ALARM): that module decides WHICH account
or token a consented request makes; this one is HOW a host's Gitea is asked -- the CLI where it can, the local API
with a short-lived admin token where it cannot.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, Final

from lab_commons import launch

__all__ = ['READ', 'Forge', 'ForgeRefused', 'GiteaCli', 'Http', 'Runner', 'local_api', 'run_argv']

#: The permission a reader is granted, and the only one ``account ensure`` grants.
READ: Final = 'read'
#: Runs one argv; its exit code and output.
type Runner = Callable[[list[str]], tuple[int, str]]
#: One local API call ``(method, path, token, sudo, body) -> (status, json)``.
type Http = Callable[[str, str, str, str, Mapping[str, Any] | None], tuple[int, Any]]


@dataclass(frozen=True)
class Forge:
    """The forge's machine accounts, made only through ``forge account|token`` (:mod:`dev_lab.ops.forgeaccounts`).

    ``api`` is the local Gitea's base URL; ``admin`` the Gitea admin whose SHORT-LIVED token (minted by the CLI per
    use, deleted after it) grants a repository collaborator, which the Gitea CLI cannot. ``binary``, ``config`` and
    ``user`` run the Gitea CLI as the Gitea user. ``read_only`` names the logins that may hold ``read:*`` scopes only;
    ``email_domain`` the address a made account gets; ``log`` the audit (who, what -- never a token).
    """

    api: str
    admin: str
    binary: str = 'gitea'
    config: str = '/etc/gitea/app.ini'
    user: str = 'gitea'
    read_only: tuple[str, ...] = ()
    email_domain: str = 'noreply.invalid'
    log: str = '/var/log/dev-lab-ops/forge.jsonl'


class ForgeRefused(ValueError):
    """The request is refused; nothing was changed (or, mid-way, the audit says what was)."""


class GiteaCli:
    """:class:`GiteaAdmin` on a host: the Gitea CLI as the Gitea user, and the local API for what it cannot do.

    The API calls carry an admin token the CLI mints for :attr:`Forge.admin` on first need (``write:repository``,
    ``write:user``, ``write:admin``) and :meth:`close` deletes; it never leaves this process. A token list or delete
    of another login is asked as that login (the ``Sudo`` header).
    """

    def __init__(self, role: Forge, *, run: Runner, http: Http) -> None:
        """Bind *role*'s CLI and API to *run* and *http*."""
        self.role, self.run, self.http = role, run, http
        self._admin: tuple[str, str] | None = None  # (name, token)

    def _cli(self, *argv: str) -> str:
        role = self.role
        code, said = self.run(['runuser', '-u', role.user, '--', role.binary, '--config', role.config, *argv])
        if code != 0:
            msg = f'gitea {" ".join(argv[:3])} failed (exit {code})'  # its output may carry a secret: never repeated
            raise ForgeRefused(msg)
        return said

    def _api(self, method: str, path: str, *, sudo: str = '', body: Mapping[str, Any] | None = None) -> tuple[int, Any]:
        if self._admin is None:
            name = f'dev-lab-ops-{uuid.uuid4().hex[:12]}'
            self._admin = (name, self.generate_token(self.role.admin, name, 'write:repository,write:user,write:admin'))
        return self.http(method, f'{self.role.api.rstrip("/")}/api/v1{path}', self._admin[1], sudo, body)

    def close(self) -> None:
        """Delete the admin token this use minted, if any."""
        if self._admin is not None:
            name, _token = self._admin
            self._api('DELETE', f'/users/{self.role.admin}/tokens/{name}')
            self._admin = None

    def user_exists(self, login: str) -> bool:
        """Whether *login* is a Gitea user (``admin user list``'s second column)."""
        rows = self._cli('admin', 'user', 'list').splitlines()[1:]
        return any(len(cells) > 1 and cells[1] == login for cells in (row.split() for row in rows))

    def create_user(self, login: str, email: str) -> None:
        """A restricted user with a random password nobody holds."""
        self._cli('admin', 'user', 'create', '--username', login, '--email', email, '--random-password',
                  '--must-change-password=false', '--restricted')  # fmt: skip

    def permission(self, repo: str, login: str) -> str | None:
        """*login*'s permission on *repo* (``none`` when it holds none)."""
        status, found = self._api('GET', f'/repos/{repo}/collaborators/{login}/permission')
        if status == HTTPStatus.NOT_FOUND:
            msg = f'no repository {repo} (or no login {login})'
            raise ForgeRefused(msg)
        return str(found.get('permission', 'none')) if isinstance(found, dict) else None

    def grant_read(self, repo: str, login: str) -> None:
        """Make *login* a Read collaborator of *repo*."""
        status, _ = self._api('PUT', f'/repos/{repo}/collaborators/{login}', body={'permission': READ})
        if status not in {HTTPStatus.OK, HTTPStatus.NO_CONTENT}:
            msg = f'granting {login} read on {repo} failed (HTTP {status})'
            raise ForgeRefused(msg)

    def token_names(self, login: str) -> set[str]:
        """The names of *login*'s tokens."""
        status, found = self._api('GET', f'/users/{login}/tokens', sudo=login)
        if status != HTTPStatus.OK or not isinstance(found, list):
            msg = f'reading {login} token names failed (HTTP {status})'
            raise ForgeRefused(msg)
        return {str(row.get('name')) for row in found}

    def delete_token(self, login: str, name: str) -> None:
        """Delete *login*'s token *name*."""
        status, _ = self._api('DELETE', f'/users/{login}/tokens/{name}', sudo=login)
        if status not in {HTTPStatus.OK, HTTPStatus.NO_CONTENT}:
            msg = f'deleting {login} token {name} failed (HTTP {status})'
            raise ForgeRefused(msg)

    def generate_token(self, login: str, name: str, scopes: str) -> str:
        """A new token of *login* named *name* with *scopes* (the CLI's ``--raw``: the bare token)."""
        return self._cli('admin', 'user', 'generate-access-token', '--username', login, '--token-name', name,
                         '--scopes', scopes, '--raw').strip()  # fmt: skip


def run_argv(argv: list[str]) -> tuple[int, str]:
    """One Gitea CLI argv through the launch door; its exit code and stdout."""
    done = launch.run(argv, capture_output=True, text=True, encoding='utf-8', check=False)
    return done.returncode, done.stdout


def local_api(method: str, url: str, token: str, sudo: str, body: Mapping[str, Any] | None) -> tuple[int, Any]:
    """One call to the host's own Gitea API (``[ops.forge] api``); its status and parsed body, ``None`` if none."""
    headers = {'Authorization': f'token {token}', 'Content-Type': 'application/json'} | ({'Sudo': sudo} if sudo else {})
    data = None if body is None else json.dumps(body).encode('utf-8')
    request = urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=30) as answer:  # noqa: S310
            status, raw = answer.status, answer.read()
    except urllib.error.HTTPError as refused:
        status, raw = refused.code, b''
    try:
        return status, json.loads(raw) if raw else None
    except ValueError:
        return status, None
