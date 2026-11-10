"""``forge account ensure`` / ``forge token mint``: the forge's machine accounts, made only through this door.

After the lockdown no agent holds root or a Gitea admin token (user rulings 2026-11-09). A machine account -- a
read-only reader for every server that pulls code, later others -- and each of its per-host tokens are made here,
run by the ``ops`` account through its fixed sudo line, each use authorised by a SINGLE-USE consent credential the
user granted with their code (:data:`ACCOUNT_ACTION`, :data:`MINT_ACTION`), whose ``subject`` is the request's
digest (:meth:`AccountRequest.subject`, :meth:`TokenRequest.subject`): it consents to exactly that request.

``account ensure`` makes the login if absent -- restricted, random password, no password change -- and grants
EXACTLY Read on each named repository, reporting a different permission as drift and setting it to Read.
``token mint`` prints the token ONCE to stdout for the caller to place; it is never logged. ``token mint-batch``
mints a closed, ordered batch of one login's tokens (at most :data:`BATCH_CAP`) under ONE :data:`BATCH_ACTION`
credential whose subject is the whole batch's digest (:meth:`TokenBatch.subject`); each item is validated as a single
mint is, all of them before the consent is spent, and each token is printed as one JSON line ``{"name", "token"}``.
A login declared read-only (``[ops.forge] read_only``) is refused any scope that is not ``read:*``; an existing token
name is refused unless ``--rotate``, which deletes the old token first. Every use is audited -- who, what --
never a token. ``token revoke`` deletes one named token of one login under ONE :data:`REVOKE_ACTION` credential
whose subject is the login and name's digest (:meth:`RevokeRequest.subject`); a name the login does not hold is
reported already absent, so a revoke can be re-run.

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
    'BATCH_ACTION',
    'BATCH_CAP',
    'MINT_ACTION',
    'REVOKE_ACTION',
    'AccountRequest',
    'BatchItem',
    'ForgeRefused',
    'GiteaAdmin',
    'GiteaCli',
    'Redeem',
    'RevokeRequest',
    'TokenBatch',
    'TokenRequest',
    'add_parser',
    'ensure',
    'mint',
    'mint_batch',
    'revoke',
    'run_verb',
    'token_line',
]

#: The consent action of one ``account ensure`` (:mod:`dev_lab.ops.consent.actions`).
ACCOUNT_ACTION: Final = 'ops.forge.account'
#: The consent action of one ``token mint``.
MINT_ACTION: Final = 'ops.forge.token'
#: The consent action of one ``token mint-batch``: one login's closed, ordered batch of tokens.
BATCH_ACTION: Final = 'ops.forge.tokens'
#: The consent action of one ``token revoke``: one named token of one login, deleted.
REVOKE_ACTION: Final = 'ops.forge.revoke'
#: The most tokens one batch consent may mint.
BATCH_CAP: Final = 16
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


@dataclass(frozen=True)
class RevokeRequest:
    """``token revoke --login L --name N``."""

    login: str
    name: str

    def subject(self) -> str:
        """The digest an ``ops.forge.revoke`` credential's subject must equal."""
        return _digest(REVOKE_ACTION, {'login': self.login, 'name': self.name})


@dataclass(frozen=True)
class BatchItem:
    """One token of a :class:`TokenBatch`: ``--item NAME:SCOPE``, rotated when ``--rotate NAME``."""

    name: str
    scope: str
    rotate: bool


@dataclass(frozen=True)
class TokenBatch:
    """``token mint-batch --login L --item NAME:SCOPE ... [--rotate NAME]``: ordered, closed, one login."""

    login: str
    items: tuple[BatchItem, ...]

    def subject(self) -> str:
        """The digest an ``ops.forge.tokens`` credential's subject must equal: the login and every item, in order."""
        listed = json.dumps([[item.name, item.scope, int(item.rotate)] for item in self.items], separators=(',', ':'))
        return _digest(BATCH_ACTION, {'login': self.login, 'items': listed})


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
    scopes = _scopes(role, request.login, request.name, request.scope)
    _consented(redeem, credential, request.subject(), MINT_ACTION)
    _login_exists(gitea, request.login)
    if request.name in gitea.token_names(request.login):
        _rotatable(request.login, request.name, rotate=request.rotate)
        gitea.delete_token(request.login, request.name)
    token = gitea.generate_token(request.login, request.name, ','.join(scopes))
    _audit(role, by, {'action': MINT_ACTION, 'login': request.login, 'name': request.name,
                      'scope': ','.join(scopes), 'rotated': request.rotate})  # fmt: skip
    return token


def revoke(
    role: Forge, gitea: GiteaAdmin, request: RevokeRequest, *, redeem: Redeem, credential: Mapping[str, Any], by: str
) -> str:
    """Delete *request*'s token if the login holds it; what it did. Audited (login, name), never a token.

    Raises:
        ForgeRefused: the login is absent, or the credential does not consent to exactly this request.

    """
    _consented(redeem, credential, request.subject(), REVOKE_ACTION)
    _login_exists(gitea, request.login)
    held = request.name in gitea.token_names(request.login)
    if held:
        gitea.delete_token(request.login, request.name)
    _audit(role, by, {'action': REVOKE_ACTION, 'login': request.login, 'name': request.name, 'revoked': held})
    return (f'revoked {request.login} token {request.name}' if held
            else f'{request.login} token {request.name} already absent')  # fmt: skip


def _scopes(role: Forge, login: str, name: str, scope: str) -> list[str]:
    scopes = [one.strip() for one in scope.split(',') if one.strip()]
    if not scopes:
        msg = f'token {name} needs a scope'
        raise ForgeRefused(msg)
    if login in role.read_only and (wide := [s for s in scopes if not s.startswith('read:')]):
        msg = f'{login} is declared read-only ([ops.forge] read_only): refused scopes {wide}'
        raise ForgeRefused(msg)
    return scopes


def _login_exists(gitea: GiteaAdmin, login: str) -> None:
    if not gitea.user_exists(login):
        msg = f'no login {login}: make it with `forge account ensure` first'
        raise ForgeRefused(msg)


def _rotatable(login: str, name: str, *, rotate: bool) -> None:
    if not rotate:
        msg = f'{login} already holds a token named {name}; --rotate deletes it and mints anew'
        raise ForgeRefused(msg)


def _checked(role: Forge, batch: TokenBatch) -> list[list[str]]:
    """Each item's scopes, once the batch's shape and every item pass as a single mint would."""
    if not batch.items:
        msg = 'token mint-batch needs at least one --item'
        raise ForgeRefused(msg)
    if len(batch.items) > BATCH_CAP:
        msg = f'token mint-batch mints at most {BATCH_CAP} tokens per consent; asked {len(batch.items)}'
        raise ForgeRefused(msg)
    names = [item.name for item in batch.items]
    if twice := sorted({name for name in names if names.count(name) > 1}):
        msg = f'token mint-batch names {twice} twice'
        raise ForgeRefused(msg)
    return [_scopes(role, batch.login, item.name, item.scope) for item in batch.items]


def mint_batch(
    role: Forge,
    gitea: GiteaAdmin,
    batch: TokenBatch,
    *,
    redeem: Redeem,
    credential: Mapping[str, Any],
    by: str,
    place: Callable[[str, str], None],
) -> None:
    """Mint every item of *batch* in order, handing each token to *place* as it is minted; audited without them.

    Every item is validated (scope, read-only, a name held without ``rotate``) before anything is minted, the
    credential redeemed ONCE for the whole batch. A failure mid-way is audited and raised naming what minted and what
    did not; the tokens already minted were placed, so none is silently lost.

    Raises:
        ForgeRefused: the batch is empty, above :data:`BATCH_CAP`, names a token twice, an item is refused as a single
            mint would be, the credential does not consent to exactly this batch, or a mint failed mid-way.

    """
    scopes = _checked(role, batch)
    _consented(redeem, credential, batch.subject(), BATCH_ACTION)
    _login_exists(gitea, batch.login)
    held = gitea.token_names(batch.login)
    for item in batch.items:
        if item.name in held:
            _rotatable(batch.login, item.name, rotate=item.rotate)
    names = [item.name for item in batch.items]
    minted: list[str] = []
    for item, scope in zip(batch.items, scopes, strict=True):
        try:
            if item.name in held:
                gitea.delete_token(batch.login, item.name)
            token = gitea.generate_token(batch.login, item.name, ','.join(scope))
        except ForgeRefused as failed:
            rest = names[len(minted) :]
            _audit(role, by, {'action': BATCH_ACTION, 'login': batch.login, 'failed': item.name, 'minted': minted,
                              'not_minted': rest})  # fmt: skip
            msg = f'{failed}; minted {minted}; not minted {rest}'
            raise ForgeRefused(msg) from failed
        place(item.name, token)
        minted.append(item.name)
        _audit(role, by, {'action': BATCH_ACTION, 'login': batch.login, 'name': item.name,
                          'scope': ','.join(scope), 'rotated': item.name in held})  # fmt: skip


def token_line(name: str, token: str) -> str:
    """One placed token as one JSON line, for the caller to put each where it goes."""
    return json.dumps({'name': name, 'token': token})


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
    tokens = kinds.add_parser('token').add_subparsers(dest='action', required=True)
    minting = tokens.add_parser('mint')
    minting.add_argument('--login', required=True)
    minting.add_argument('--name', required=True)
    minting.add_argument('--scope', required=True, help='Gitea scopes, comma-separated (a read-only login: read:*)')
    minting.add_argument('--rotate', action='store_true', help='delete an existing token of this name first')
    batch = tokens.add_parser('mint-batch', help=f'one login, up to {BATCH_CAP} tokens, one consent')
    batch.add_argument('--login', required=True)
    batch.add_argument('--item', action='append', required=True, metavar='NAME:SCOPE', help='in order; scope as mint')
    batch.add_argument('--rotate', action='append', default=[], metavar='NAME', help='rotate this item if it exists')
    revoking = tokens.add_parser('revoke', help='delete one named token of one login, one consent')
    revoking.add_argument('--login', required=True)
    revoking.add_argument('--name', required=True)
    for one in (account, minting, batch, revoking):
        one.add_argument('--credential', default='', help='a single-use consent credential for exactly this request')
        one.add_argument('--subject', action='store_true', help="print the request's digest the consent must name")


type _Request = AccountRequest | TokenRequest | TokenBatch | RevokeRequest


def _parsed_request(args: argparse.Namespace) -> tuple[_Request, str]:
    """The parsed verb's request and its consent action.

    Raises:
        ForgeRefused: a ``mint-batch`` item is malformed.

    """
    if args.kind == 'account':
        return AccountRequest(args.login, tuple(args.read)), ACCOUNT_ACTION
    if args.action == 'revoke':
        return RevokeRequest(args.login, args.name), REVOKE_ACTION
    if args.action == 'mint':
        return TokenRequest(args.login, args.name, args.scope, rotate=args.rotate), MINT_ACTION
    return _batch_request(args), BATCH_ACTION


def run_verb(role: Forge, args: argparse.Namespace, redeem_for: Callable[[str], Redeem]) -> int:
    """Run the parsed verb; exit 0 done, 2 refused. A minted token goes to stdout ONCE, never to a log."""
    try:
        request, action = _parsed_request(args)
    except ForgeRefused as refused:
        emit(f'refused: {refused}', err=True)
        return 2
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
        elif isinstance(request, RevokeRequest):
            emit(f'[ops forge] {revoke(role, gitea, request, redeem=redeem_for(action), credential=granted, by=by)}')
        elif isinstance(request, TokenRequest):
            emit(mint(role, gitea, request, redeem=redeem_for(action), credential=granted, by=by))
        else:
            mint_batch(role, gitea, request, redeem=redeem_for(action), credential=granted, by=by,
                       place=lambda name, token: emit(token_line(name, token)))  # fmt: skip
    except (ForgeRefused, ConsentRefused) as refused:
        emit(f'refused: {refused}', err=True)
        return 2
    finally:
        gitea.close()
    return 0


def _batch_request(args: argparse.Namespace) -> TokenBatch:
    """``--item NAME:SCOPE ...`` and ``--rotate NAME ...`` as a :class:`TokenBatch`.

    Raises:
        ForgeRefused: an item is not ``NAME:SCOPE``, or a ``--rotate`` names no item.

    """
    items = []
    for item in args.item:
        name, colon, scope = item.partition(':')
        if not colon or not name:
            msg = f'--item {item!r} is not NAME:SCOPE'
            raise ForgeRefused(msg)
        items.append(BatchItem(name, scope, rotate=name in args.rotate))
    if stray := sorted(set(args.rotate) - {item.name for item in items}):
        msg = f'--rotate {stray} names no --item'
        raise ForgeRefused(msg)
    return TokenBatch(args.login, tuple(items))
