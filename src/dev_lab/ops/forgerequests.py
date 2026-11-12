"""The consented requests of ``ops forge``: each one's consent action and the digest its credential must name.

A credential consents to exactly one request: its ``subject`` is the request's digest (:meth:`AccountRequest.subject`,
:meth:`TokenRequest.subject`, :meth:`RevokeRequest.subject`, :meth:`TokenBatch.subject`). An account request is
READ from ``[ops.forge.accounts]`` (:func:`declared_request`), never typed, so the declaration is its one source.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from dev_lab.ops.giteaadmin import ROLE_GRANTS, ForgeRefused

if TYPE_CHECKING:
    from dev_lab.ops.giteaadmin import Forge

__all__ = [
    'ACCOUNT_ACTION',
    'BATCH_ACTION',
    'BATCH_CAP',
    'MINT_ACTION',
    'REVOKE_ACTION',
    'AccountRequest',
    'BatchItem',
    'RevokeRequest',
    'TokenBatch',
    'TokenRequest',
    'declared_request',
    'digest',
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


def digest(action: str, fields: Mapping[str, str]) -> str:
    """The SHA-256 a credential of *action* names as its subject: the action, then each field, sorted."""
    text = '\n'.join([action, *(f'{key}={value}' for key, value in sorted(fields.items()))])
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class AccountRequest:
    """``account ensure --login L``: L's declared role and repositories."""

    login: str
    role: str
    repos: tuple[str, ...]

    def subject(self) -> str:
        """The digest an ``ops.forge.account`` credential's subject must equal: login, role and repositories."""
        fields = {'login': self.login, 'role': self.role, 'repos': ','.join(sorted(set(self.repos)))}
        return digest(ACCOUNT_ACTION, fields)


def declared_request(role: Forge, login: str) -> AccountRequest:
    """*login*'s :class:`AccountRequest` as ``[ops.forge.accounts]`` declares it.

    Raises:
        ForgeRefused: *login* is not declared, or its role or repositories are malformed.

    """
    row = role.accounts.get(login)
    if row is None:
        msg = f'{login} is not declared in [ops.forge.accounts]; declared: {sorted(role.accounts)}'
        raise ForgeRefused(msg)
    kind, repos = row.get('role'), tuple(sorted(set(row.get('repos', ()))))
    if kind not in ROLE_GRANTS or not repos:
        msg = f'[ops.forge.accounts] {login} needs role one of {sorted(ROLE_GRANTS)} and at least one repo'
        raise ForgeRefused(msg)
    return AccountRequest(login, str(kind), repos)


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
        return digest(MINT_ACTION, fields)


@dataclass(frozen=True)
class RevokeRequest:
    """``token revoke --login L --name N``."""

    login: str
    name: str

    def subject(self) -> str:
        """The digest an ``ops.forge.revoke`` credential's subject must equal."""
        return digest(REVOKE_ACTION, {'login': self.login, 'name': self.name})


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
        return digest(BATCH_ACTION, {'login': self.login, 'items': listed})
