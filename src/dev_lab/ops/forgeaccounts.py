"""``forge account ensure`` / ``forge token mint``: the forge's machine accounts, made only through this door.

After the lockdown no agent holds root or a Gitea admin token (user rulings 2026-11-09). A machine account -- one
declared role, ``[ops.forge.accounts] <login> = {role, repos}`` with role ``read``, ``write`` or ``review`` -- and
each of its per-host tokens are made here, run by the ``ops`` account through its fixed sudo line, each use
authorised by a SINGLE-USE consent credential the user granted with their code, whose ``subject`` is the request's
digest (:mod:`dev_lab.ops.forgerequests`): it consents to exactly that request.

``account ensure --login L`` reads L's role and repositories from the declaration (one source), makes the login if
absent -- restricted, random password, no password change -- and grants EXACTLY its role's permission
(:data:`~dev_lab.ops.giteaadmin.ROLE_GRANTS`) on each, reporting a different permission as drift and setting it. An
undeclared login is refused before any consent is spent; the consent names (login, role, repos), so a role widened
after it was granted is refused.
``token mint`` prints the token ONCE to stdout for the caller to place; it is never logged. ``token mint-batch``
mints a closed, ordered batch of one login's tokens (at most :data:`BATCH_CAP`) under ONE :data:`BATCH_ACTION`
credential whose subject is the whole batch's digest (:meth:`TokenBatch.subject`); each item is validated as a single
mint is, all of them before the consent is spent, and each token is printed as one JSON line ``{"name", "token"}``.
A login whose declared role is ``read`` is refused any scope that is not ``read:*``; an existing token
name is refused unless ``--rotate``, which deletes the old token first. Every use is audited -- who, what --
never a token. ``token revoke`` deletes one named token of one login under ONE :data:`REVOKE_ACTION` credential
whose subject is the login and name's digest (:meth:`RevokeRequest.subject`); a name the login does not hold is
reported already absent, so a revoke can be re-run.

Gitea is reached as the Gitea user through its CLI (:class:`GiteaCli`) where the CLI can; a repository collaborator
and a token list/delete have no CLI, so those go to the local API with an admin token the CLI mints for this one
use and the door deletes after it.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from lab_commons.log import emit

from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.forgerequests import (
    ACCOUNT_ACTION,
    BATCH_ACTION,
    BATCH_CAP,
    MINT_ACTION,
    REVOKE_ACTION,
    AccountRequest,
    BatchItem,
    RevokeRequest,
    TokenBatch,
    TokenRequest,
    declared_request,
)
from dev_lab.ops.giteaadmin import ROLE_GRANTS, Forge, ForgeRefused, GiteaCli, local_api, run_argv

if TYPE_CHECKING:
    import argparse

__all__ = [
    'ForgeRefused',
    'GiteaAdmin',
    'Redeem',
    'add_parser',
    'ensure',
    'mint',
    'mint_batch',
    'revoke',
    'run_list',
    'run_verb',
    'token_line',
    'token_list',
]

#: Redeems a credential on one subject (:func:`dev_lab.ops.consent.client.redeem`); raises when it does not.
type Redeem = Callable[[Mapping[str, Any], str], object]


class GiteaAdmin(Protocol):
    """What the door needs of Gitea; :class:`GiteaCli` on a host, a fake in tests."""

    def user_exists(self, login: str) -> bool:
        """Whether *login* is a user."""

    def create_user(self, login: str, email: str) -> None:
        """Make *login*: restricted, a random password nobody holds."""

    def permission(self, repo: str, login: str) -> str | None:
        """*login*'s permission on *repo*; ``None`` or ``none`` when it holds none."""

    def grant(self, repo: str, login: str, permission: str) -> None:
        """Make *login* a collaborator of *repo* holding *permission*."""

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


def ensure(
    role: Forge, gitea: GiteaAdmin, request: AccountRequest, *, redeem: Redeem, credential: Mapping[str, Any], by: str
) -> tuple[str, ...]:
    """Make *request*'s login if absent and grant exactly its role's permission on each repository; what it did.

    Raises:
        ForgeRefused: the login is undeclared, the request is not what the declaration says (a widened role), or
            the credential does not consent to exactly this request.

    """
    declared = declared_request(role, request.login)
    if (declared.role, declared.repos) != (request.role, tuple(sorted(set(request.repos)))):
        msg = (f'[ops.forge.accounts] declares {request.login} {declared.role} on {sorted(declared.repos)}; '
               f'asked {request.role} on {sorted(request.repos)}')  # fmt: skip
        raise ForgeRefused(msg)
    redeem(credential, request.subject())
    grant = ROLE_GRANTS[request.role]
    said: list[str] = []
    if gitea.user_exists(request.login):
        said.append(f'{request.login} exists')
    else:
        gitea.create_user(request.login, f'{request.login}@{role.email_domain}')
        said.append(f'created {request.login}')
    for repo in sorted(set(request.repos)):
        held = gitea.permission(repo, request.login)
        if held == grant:
            said.append(f'{repo}: {grant}')
            continue
        gitea.grant(repo, request.login, grant)
        said.append(f'{repo}: granted {grant}' if held in {None, 'none'} else f'{repo}: drift {held} -> {grant}')
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
    redeem(credential, request.subject())
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
    redeem(credential, request.subject())
    _login_exists(gitea, request.login)
    held = request.name in gitea.token_names(request.login)
    if held:
        gitea.delete_token(request.login, request.name)
    _audit(role, by, {'action': REVOKE_ACTION, 'login': request.login, 'name': request.name, 'revoked': held})
    return (f'revoked {request.login} token {request.name}' if held
            else f'{request.login} token {request.name} already absent')  # fmt: skip


def token_list(gitea: GiteaAdmin, login: str) -> tuple[str, ...]:
    """The names of *login*'s tokens, sorted; read-only, so no consent. Never a value, hash or last-eight.

    Raises:
        ForgeRefused: the login is absent, or the forge did not answer the read.

    """
    _login_exists(gitea, login)
    return tuple(sorted(gitea.token_names(login)))


def run_list(gitea: GiteaAdmin, args: argparse.Namespace) -> int:
    """``forge token list --login L``: one name per line; exit 0, or 2 refused."""
    try:
        for name in token_list(gitea, args.login):
            emit(name)
    except ForgeRefused as refused:
        emit(f'refused: {refused}', err=True)
        return 2
    return 0


def _scopes(role: Forge, login: str, name: str, scope: str) -> list[str]:
    scopes = [one.strip() for one in scope.split(',') if one.strip()]
    if not scopes:
        msg = f'token {name} needs a scope'
        raise ForgeRefused(msg)
    reader = role.accounts.get(login, {}).get('role') == 'read'
    if reader and (wide := [s for s in scopes if not s.startswith('read:')]):
        msg = f'{login} is declared read-only ([ops.forge.accounts] role read): refused scopes {wide}'
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
    redeem(credential, batch.subject())
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


def add_parser(verbs: argparse._SubParsersAction) -> None:
    """``forge account ensure`` and ``forge token mint`` on the ops parser."""
    forged = verbs.add_parser('forge', help="the forge's machine accounts and their tokens, each use consented")
    kinds = forged.add_subparsers(dest='kind', required=True)
    account = kinds.add_parser('account')
    account.add_argument('action', choices=('ensure',))
    account.add_argument('--login', required=True)
    tokens = kinds.add_parser('token').add_subparsers(dest='action', required=True)
    minting = tokens.add_parser('mint')
    minting.add_argument('--login', required=True)
    minting.add_argument('--name', required=True)
    minting.add_argument('--scope', required=True, help='Gitea scopes, comma-separated (a read login: read:*)')
    minting.add_argument('--rotate', action='store_true', help='delete an existing token of this name first')
    batch = tokens.add_parser('mint-batch', help=f'one login, up to {BATCH_CAP} tokens, one consent')
    batch.add_argument('--login', required=True)
    batch.add_argument('--item', action='append', required=True, metavar='NAME:SCOPE', help='in order; scope as mint')
    batch.add_argument('--rotate', action='append', default=[], metavar='NAME', help='rotate this item if it exists')
    revoking = tokens.add_parser('revoke', help='delete one named token of one login, one consent')
    revoking.add_argument('--login', required=True)
    revoking.add_argument('--name', required=True)
    listing = tokens.add_parser('list', help="the names of one login's tokens; read-only, no consent")
    listing.add_argument('--login', required=True)
    for one in (account, minting, batch, revoking):
        one.add_argument('--credential', default='', help='a single-use consent credential for exactly this request')
        one.add_argument('--subject', action='store_true', help="print the request's digest the consent must name")


type _Request = AccountRequest | TokenRequest | TokenBatch | RevokeRequest


def _parsed_request(role: Forge, args: argparse.Namespace) -> tuple[_Request, str]:
    """The parsed verb's request and its consent action.

    Raises:
        ForgeRefused: a ``mint-batch`` item is malformed.

    """
    if args.kind == 'account':
        return declared_request(role, args.login), ACCOUNT_ACTION
    if args.action == 'revoke':
        return RevokeRequest(args.login, args.name), REVOKE_ACTION
    if args.action == 'mint':
        return TokenRequest(args.login, args.name, args.scope, rotate=args.rotate), MINT_ACTION
    return _batch_request(args), BATCH_ACTION


def run_verb(role: Forge, args: argparse.Namespace, redeem_for: Callable[[str], Redeem]) -> int:
    """Run the parsed verb; exit 0 done, 2 refused. A minted token goes to stdout ONCE, never to a log."""
    if args.kind == 'token' and args.action == 'list':
        reader = GiteaCli(role, run=run_argv, http=local_api)
        try:
            return run_list(reader, args)
        finally:
            reader.close()
    try:
        request, action = _parsed_request(role, args)
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
