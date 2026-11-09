"""``forge account ensure`` / ``forge token mint``: the forge's machine accounts, made only through this door.

After the lockdown no agent holds root or a Gitea admin token (user rulings 2026-11-09). A machine account -- a
read-only reader for every server that pulls code, later others -- and each of its per-host tokens are made here,
run by the ``ops`` account through its fixed sudo line, each use authorised by a SINGLE-USE consent credential the
user granted with their code (:data:`ACCOUNT_ACTION`, :data:`MINT_ACTION`), whose ``subject`` is the request's
digest (:meth:`AccountRequest.subject`, :meth:`TokenRequest.subject`): it consents to exactly that request.

``account ensure`` makes the login if absent -- restricted, random password, no password change -- and grants
EXACTLY Read on each named repository, reporting a different permission as drift and setting it to Read.
``token mint`` prints the token ONCE to stdout for the caller to place; it is never logged. A login declared
read-only (``[ops.forge] read_only``) is refused any scope that is not ``read:*``; an existing token name is
refused unless ``--rotate``, which deletes the old token first. Every use is audited -- who, what -- never a token.

Gitea is reached as the Gitea user through its CLI (:class:`GiteaCli`) where the CLI can; a repository collaborator
and a token list/delete have no CLI, so those go to the local API with an admin token the CLI mints for this one
use and the door deletes after it.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Protocol

from lab_commons import launch
from lab_commons.log import emit

from dev_lab.ops.consent.credential import ConsentRefused


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


if TYPE_CHECKING:
    import argparse

__all__ = [
    'ACCOUNT_ACTION',
    'MINT_ACTION',
    'AccountRequest',
    'ForgeRefused',
    'GiteaAdmin',
    'GiteaCli',
    'Redeem',
    'TokenRequest',
    'add_parser',
    'ensure',
    'mint',
    'run_verb',
]

#: The consent action of one ``account ensure`` (:mod:`dev_lab.ops.consent.actions`).
ACCOUNT_ACTION: Final = 'ops.forge.account'
#: The consent action of one ``token mint``.
MINT_ACTION: Final = 'ops.forge.token'
#: The permission a reader is granted, and the only one ``account ensure`` grants.
READ: Final = 'read'

#: Redeems a credential for one action, raising when it does not consent; returns the credential's subject.
type Redeem = Callable[[Mapping[str, Any]], str]
#: Runs one argv; its exit code and output.
type Runner = Callable[[list[str]], tuple[int, str]]
#: One local API call ``(method, path, token, sudo, body) -> (status, json)``.
type Http = Callable[[str, str, str, str, Mapping[str, Any] | None], tuple[int, Any]]


class ForgeRefused(ValueError):
    """The request is refused; nothing was changed (or, mid-way, the audit says what was)."""


def _digest(action: str, fields: Mapping[str, str]) -> str:
    text = '\n'.join([action, *(f'{key}={value}' for key, value in sorted(fields.items()))])
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class AccountRequest:
    """``account ensure --login L --read owner/repo ...``."""

    login: str
    read: tuple[str, ...]

    def subject(self) -> str:
        """The digest an ``ops.forge.account`` credential's subject must equal."""
        return _digest(ACCOUNT_ACTION, {'login': self.login, 'read': ','.join(sorted(set(self.read)))})


@dataclass(frozen=True)
class TokenRequest:
    """``token mint --login L --name N --scope S [--rotate]``."""

    login: str
    name: str
    scope: str
    rotate: bool

    def subject(self) -> str:
        """The digest an ``ops.forge.token`` credential's subject must equal."""
        fields = {'login': self.login, 'name': self.name, 'scope': self.scope, 'rotate': str(int(self.rotate))}
        return _digest(MINT_ACTION, fields)


class GiteaAdmin(Protocol):
    """What the door needs of Gitea; :class:`GiteaCli` on a host, a fake in tests."""

    def user_exists(self, login: str) -> bool:
        """Whether *login* is a user."""

    def create_user(self, login: str, email: str) -> None:
        """Make *login*: restricted, a random password nobody holds."""

    def permission(self, repo: str, login: str) -> str | None:
        """*login*'s permission on *repo*; ``None`` or ``none`` when it holds none."""

    def grant_read(self, repo: str, login: str) -> None:
        """Make *login* a Read collaborator of *repo*."""

    def token_names(self, login: str) -> set[str]:
        """The names of *login*'s tokens."""

    def delete_token(self, login: str, name: str) -> None:
        """Delete *login*'s token *name*."""

    def generate_token(self, login: str, name: str, scopes: str) -> str:
        """A new token of *login*."""


def _audit(role: Forge, by: str, line: Mapping[str, Any]) -> None:
    log = Path(role.log)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('a', encoding='utf-8') as out:
        out.write(json.dumps({'at': datetime.now(UTC).isoformat(timespec='seconds'), 'by': by, **line}) + '\n')


def _consented(redeem: Redeem, credential: Mapping[str, Any], subject: str, action: str) -> None:
    if redeem(credential) != subject:
        msg = f'the {action} credential consents to another request (its subject is not this request digest)'
        raise ForgeRefused(msg)


def ensure(
    role: Forge, gitea: GiteaAdmin, request: AccountRequest, *, redeem: Redeem, credential: Mapping[str, Any], by: str
) -> tuple[str, ...]:
    """Make *request*'s login if absent and grant it exactly Read on each repository; what it did, line by line.

    Raises:
        ForgeRefused: no repository was named, or the credential does not consent to exactly this request.

    """
    if not request.read:
        msg = 'account ensure grants Read on at least one --read owner/repo'
        raise ForgeRefused(msg)
    _consented(redeem, credential, request.subject(), ACCOUNT_ACTION)
    said: list[str] = []
    if gitea.user_exists(request.login):
        said.append(f'{request.login} exists')
    else:
        gitea.create_user(request.login, f'{request.login}@{role.email_domain}')
        said.append(f'created {request.login}')
    for repo in sorted(set(request.read)):
        held = gitea.permission(repo, request.login)
        if held == READ:
            said.append(f'{repo}: read')
            continue
        gitea.grant_read(repo, request.login)
        said.append(f'{repo}: granted read' if held in {None, 'none'} else f'{repo}: drift {held} -> read')
    _audit(role, by, {'action': ACCOUNT_ACTION, 'login': request.login, 'what': said})
    return tuple(said)


def mint(
    role: Forge, gitea: GiteaAdmin, request: TokenRequest, *, redeem: Redeem, credential: Mapping[str, Any], by: str
) -> str:
    """One token for *request*, to be printed once by the caller; audited without it.

    Raises:
        ForgeRefused: a read-only login asked a non-``read:*`` scope, the login is absent, the name exists without
            ``rotate``, or the credential does not consent to exactly this request.

    """
    scopes = [scope.strip() for scope in request.scope.split(',') if scope.strip()]
    if not scopes:
        msg = 'token mint needs --scope'
        raise ForgeRefused(msg)
    if request.login in role.read_only and (wide := [s for s in scopes if not s.startswith('read:')]):
        msg = f'{request.login} is declared read-only ([ops.forge] read_only): refused scopes {wide}'
        raise ForgeRefused(msg)
    _consented(redeem, credential, request.subject(), MINT_ACTION)
    if not gitea.user_exists(request.login):
        msg = f'no login {request.login}: make it with `forge account ensure` first'
        raise ForgeRefused(msg)
    if request.name in gitea.token_names(request.login):
        if not request.rotate:
            msg = f'{request.login} already holds a token named {request.name}; --rotate deletes it and mints anew'
            raise ForgeRefused(msg)
        gitea.delete_token(request.login, request.name)
    token = gitea.generate_token(request.login, request.name, ','.join(scopes))
    _audit(role, by, {'action': MINT_ACTION, 'login': request.login, 'name': request.name,
                      'scope': ','.join(scopes), 'rotated': request.rotate})  # fmt: skip
    return token


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
        _status, found = self._api('GET', f'/users/{login}/tokens', sudo=login)
        return {str(row.get('name')) for row in found} if isinstance(found, list) else set()

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


def add_parser(verbs: argparse._SubParsersAction) -> None:
    """``forge account ensure`` and ``forge token mint`` on the ops parser."""
    forged = verbs.add_parser('forge', help="the forge's machine accounts and their tokens, each use consented")
    kinds = forged.add_subparsers(dest='kind', required=True)
    account = kinds.add_parser('account')
    account.add_argument('action', choices=('ensure',))
    account.add_argument('--login', required=True)
    account.add_argument('--read', action='append', required=True, metavar='OWNER/REPO', help='grant exactly Read')
    minting = kinds.add_parser('token')
    minting.add_argument('action', choices=('mint',))
    minting.add_argument('--login', required=True)
    minting.add_argument('--name', required=True)
    minting.add_argument('--scope', required=True, help='Gitea scopes, comma-separated (a read-only login: read:*)')
    minting.add_argument('--rotate', action='store_true', help='delete an existing token of this name first')
    for one in (account, minting):
        one.add_argument('--credential', default='', help='a single-use consent credential for exactly this request')
        one.add_argument('--subject', action='store_true', help="print the request's digest the consent must name")


def run_verb(role: Forge, args: argparse.Namespace, redeem_for: Callable[[str], Redeem]) -> int:
    """Run the parsed verb; exit 0 done, 2 refused. A minted token goes to stdout ONCE, never to a log."""
    request: AccountRequest | TokenRequest
    if args.kind == 'account':
        request, action = AccountRequest(args.login, tuple(args.read)), ACCOUNT_ACTION
    else:
        request, action = TokenRequest(args.login, args.name, args.scope, rotate=args.rotate), MINT_ACTION
    if args.subject:
        emit(request.subject())
        return 0
    if not args.credential:
        emit(f'refused: {action} needs --credential (its subject: {request.subject()})', err=True)
        return 2
    granted = json.loads(Path(args.credential).read_text(encoding='utf-8'))
    gitea = GiteaCli(role, run=run_argv, http=local_api)
    by = os.environ.get('SUDO_USER', '') or 'root'
    try:
        if isinstance(request, AccountRequest):
            for line in ensure(role, gitea, request, redeem=redeem_for(action), credential=granted, by=by):
                emit(f'[ops forge] {line}')
        else:
            emit(mint(role, gitea, request, redeem=redeem_for(action), credential=granted, by=by))
    except (ForgeRefused, ConsentRefused) as refused:
        emit(f'refused: {refused}', err=True)
        return 2
    finally:
        gitea.close()
    return 0
