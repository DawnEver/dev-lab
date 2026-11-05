"""A GITHUB APP as a forge identity: the judge's, where the forge allows no second user (decision 2026-11-04).

GitHub names an App's writes by the App, and a branch ruleset can require a check run FROM ONE APP
(``required_status_checks`` with ``integration_id``): nobody else -- no user, no Actions job, no other App -- can post
it. So a GitHub judge is an App, and its verdict a check run (:mod:`dev_lab.dev.forgereview_bundle`).

The App authenticates in two steps, each asked of GitHub:

* a JWT (RS256 over the App's private key; ``iat`` 60 s in the past against clock drift, ``exp`` within GitHub's
  10 min ceiling) authenticates AS THE APP: ``GET /app`` names its slug, ``GET /repos/{o}/{r}/installation`` the
  installation on the repository;
* ``POST /app/installations/{id}/access_tokens`` exchanges it for an INSTALLATION TOKEN (one hour), the credential
  every verb then presents. It is cached per process and repository (:func:`installation`), so one run mints once.

Signing is ``cryptography``'s RSA (a base dependency): the JWT around it is three base64url segments, no RSA of
our own. The key file is read, never logged; the token never reaches output.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from dev_lab.dev.forge import forge_of_url, forge_transport
from dev_lab.dev.forgework import Client, client_for

if TYPE_CHECKING:
    from collections.abc import Callable

    from dev_lab.dev.forge import Forge, Transport

__all__ = ['App', 'AppClient', 'app_client', 'app_jwt', 'app_of', 'installation']

#: How far ``iat`` is set back against a clock running ahead of GitHub's.
_SKEW: Final = timedelta(seconds=60)
#: How long the JWT lives: under GitHub's 10-minute ceiling, counted from the set-back ``iat``.
_LIFE: Final = timedelta(minutes=9)
#: An installation token closer than this to its expiry is minted again.
_MARGIN: Final = timedelta(minutes=5)


@dataclass(frozen=True)
class App:
    """A GitHub App identity: its id (what a ruleset's ``integration_id`` names) and its slug, as GitHub answers."""

    app_id: int
    slug: str

    @property
    def login(self) -> str:
        """The login GitHub records for the App's comments and reviews: ``<slug>[bot]``."""
        return f'{self.slug}[bot]'


@dataclass(frozen=True)
class _Minted:
    app: App
    token: str
    expires: datetime


#: Per process: ``(host, app id, repository) -> the installation token minted for it``.
_MINTED: dict[tuple[str, int, str], _Minted] = {}


def _segment(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def app_jwt(app_id: int, key_pem: bytes, now: datetime) -> str:
    """The RS256 JWT authenticating as App *app_id* at *now*; refused when *key_pem* is no RSA private key."""
    key = serialization.load_pem_private_key(key_pem, password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        msg = f'the key of GitHub App {app_id} is not an RSA private key: GitHub signs RS256 only'
        raise TypeError(msg)
    issued = now - _SKEW
    head = _segment(json.dumps({'alg': 'RS256', 'typ': 'JWT'}, separators=(',', ':')).encode())
    claims = {'iat': int(issued.timestamp()), 'exp': int((issued + _LIFE).timestamp()), 'iss': str(app_id)}
    body = _segment(json.dumps(claims, separators=(',', ':')).encode())
    signed = f'{head}.{body}'
    signature = key.sign(signed.encode(), padding.PKCS1v15(), hashes.SHA256())
    return f'{signed}.{_segment(signature)}'


def installation(
    forge: Forge, app_id: int, key_file: Path, *, transport: Transport = forge_transport,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> tuple[App, str]:  # fmt: skip
    """App *app_id*'s identity and an installation token on *forge*'s repository, minted once per process.

    Raises:
        ForgeCallFailed: GitHub refused a step (no installation on the repository, a wrong key or id).
        OSError: the key file is unreadable.
        TypeError: the key is no RSA private key.
        ValueError: GitHub's answer lacks a field, or names another App.

    """
    now = clock()
    cached = _MINTED.get(key := (forge.host, app_id, forge.identity))
    if cached is not None and cached.expires - now > _MARGIN:
        return cached.app, cached.token
    signer = Client(forge, app_jwt(app_id, key_file.read_bytes(), now), transport=transport)
    try:
        named: Any = signer.call('GET', '/app')
        installed: Any = signer.call('GET', f'{signer.repo}/installation')
        minted: Any = signer.call('POST', f'/app/installations/{installed["id"]}/access_tokens', {})
        app = App(int(named['id']), str(named['slug']))
        expires = datetime.fromisoformat(str(minted['expires_at']))
        token = str(minted['token'])
    except (KeyError, TypeError) as short:
        msg = f'GitHub App {app_id}: an authentication answer lacks {short}'
        raise ValueError(msg) from short
    if app.app_id != app_id:
        msg = f'the key signed for GitHub App {app_id} but GitHub names App {app.app_id}'
        raise ValueError(msg)
    _MINTED[key] = _Minted(app, token, expires)
    return app, token


@dataclass
class AppClient(Client):
    """A :class:`~dev_lab.dev.forgework.Client` presenting App :attr:`app`'s installation token as ``Bearer``.

    GitHub refuses an installation ``/user`` as an integration -- the answer :meth:`Client.whoami` reads as the
    Actions bot. Here that integration is KNOWN: the App GitHub named at ``GET /app`` when the token was minted.
    """

    app: App = field(kw_only=True)

    def whoami(self) -> str:
        """The login GitHub records for this App's writes, ``<slug>[bot]``."""
        return self.app.login


def app_of(client: Client) -> App | None:
    """The App *client* authenticates as, or ``None`` for a user's or a job's token."""
    return client.app if isinstance(client, AppClient) else None


def app_client(
    root: Path, url: str, app_id: int, key_file: Path, *, transport: Transport = forge_transport,
    outbox: Path | None = None,
) -> Client:  # fmt: skip
    """The client for *url* as App *app_id*'s installation, journal, stamp and caches as :func:`client_for`."""
    app, token = installation(forge_of_url(url), app_id, key_file, transport=transport)
    built = client_for(root, url=url, token=token, transport=transport, outbox=outbox)
    return AppClient(
        built.forge, token, transport=transport, stamp=built.stamp, journal=built.journal, cache_dir=built.cache_dir,
        app=app,
    )  # fmt: skip
