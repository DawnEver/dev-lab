"""``python -m dev_lab.dev.forge auth login|status`` -- one command to give a box a forge token.

WHERE THE TOKEN GOES. Every forge verb reads ``git credential fill`` for the host and nothing else
(:func:`dev_lab.dev.forge.token_for`). ``auth login`` writes to that store with ``git credential
approve`` (``protocol=https``, the host, ``username=`` the login the forge returned, ``password=`` the
token), so the forge verbs find it AND ``git push`` over https uses it -- one secret, kept wherever
the configured helper keeps secrets (Git Credential Manager, the OS keychain).
This module writes no file and never prints the token.

VERIFIED BEFORE STORED. The token is sent to ``GET /api/v1/user`` (Gitea) or ``GET /user`` (GitHub)
first; a rejected token is reported with the forge's answer and is NOT stored, so a typo cannot
displace a credential that worked.

``auth status`` names the login the stored token authenticates as -- never the secret.

``auth check --url <repo url>`` asks what a ``forge serve`` TICK needs of the stored token on that
repository (:func:`tick_refusal`), with reads only: who it is (``GET /user``), whether it may post
commit statuses (the repository's own ``permissions.push``, never a test post) and whether it may read
issues (the host card). Measured 2026-10-12: a token that read every repo over git was refused at
``GET /user`` by every tick, and ``git ls-remote`` could not have seen it.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final, TextIO

from lab_commons.log import emit

from dev_lab.dev.forge import (
    Forge,
    NoCredential,
    Transport,
    forge_from_remote,
    forge_of_url,
    https_transport,
    store_credential,
)
from dev_lab.dev.forgework import Client, ForgeCallFailed, stored_client

__all__ = ['TICK_SCOPES', 'login', 'main', 'status', 'tick_refusal']

#: The exit status for a usage error, as argparse uses it.
_USAGE = 2

#: The token scopes a tick needs, as the forge's token page names them.
TICK_SCOPES: Final = 'repository (read and write), issue (read and write), user (read)'


def login(
    forge: Forge, token: str, *, cwd: Path, env: Mapping[str, str] | None = None, transport: Transport = https_transport
) -> str:
    """Verify *token* against the forge, then store it for ``https://<host>``; return the login.

    Raises:
        ForgeCallFailed: the forge did not accept the token; nothing was stored.
        NoCredential: the token was accepted and git could not store it.

    """
    who = Client(forge, token, transport=transport).whoami()
    store_credential(forge.host, who, token, cwd=cwd, env=env)
    return who


def status(
    forge: Forge, *, cwd: Path, env: Mapping[str, str] | None = None, transport: Transport = https_transport
) -> str:
    """The login the stored token authenticates as.

    Raises:
        NoCredential: git holds no credential for the host.
        ForgeCallFailed: a token was found and the forge did not accept it.

    """
    return stored_client(forge, cwd=cwd, env=env, transport=transport).whoami()


def tick_refusal(
    forge: Forge, *, cwd: Path, env: Mapping[str, str] | None = None, transport: Transport = https_transport
) -> str:
    """What the forge API refuses the stored credential that a tick needs on *forge*'s repo; ``''`` when nothing."""
    try:
        client = stored_client(forge, cwd=cwd, env=env, transport=transport)
    except NoCredential as none:
        return str(none)
    refused = []
    if not _answers(client.whoami):
        refused.append('user (read): GET /user refused')
    permissions: dict[str, Any] = {}
    if not _answers(lambda: permissions.update(client.call('GET', client.repo).get('permissions') or {})):
        refused.append('repository (read): the repository read refused')
    elif not permissions.get('push'):
        refused.append('repository (write): no push permission, so commit statuses would be refused')
    query = client.backend.list_query.format(state='open', limit=1)
    if not _answers(lambda: client.call('GET', f'{client.repo}/issues?{query}')):
        refused.append('issue (read): the issues list refused')
    return '; '.join(refused)


def _answers(call: Callable[[], object]) -> bool:
    try:
        call()
    except ForgeCallFailed:
        return False
    return True


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge auth', description='set up or check the forge token')
    verbs = parser.add_subparsers(dest='verb', required=True)
    signin = verbs.add_parser('login', help='verify a personal access token and store it with git credential')
    signin.add_argument('--token-stdin', action='store_true', help='read the token from stdin instead of a prompt')
    check = verbs.add_parser('status', help='who the stored token authenticates as')
    for sub in (signin, check):
        sub.add_argument('--host', help="the forge host (default: the host of this checkout's origin)")
    tick = verbs.add_parser('check', help='whether the stored token can do what a forge serve tick does')
    tick.add_argument('--url', help="the repository's https url (default: this checkout's origin)")
    return parser


def _forge(root: Path, host: str | None) -> Forge:
    """The forge to authenticate against: *host* alone when given, else this checkout's origin."""
    return Forge(host, '', '') if host else forge_from_remote(root)


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    transport: Transport = https_transport,
    read_secret: Callable[[str], str] = getpass.getpass,
    stdin: TextIO | None = None,
) -> int:
    """``auth login [--host H] [--token-stdin]`` / ``auth status [--host H]``; nonzero when not authenticated."""
    args = _parser().parse_args(list(sys.argv[2:] if argv is None else argv))
    root = Path.cwd() if cwd is None else cwd
    if args.verb == 'check':
        return _check(forge_of_url(args.url) if args.url else forge_from_remote(root), root, env, transport)
    forge = _forge(root, args.host)
    if args.verb == 'status':
        return _status(forge, root, env, transport)
    if args.token_stdin:
        token = (sys.stdin if stdin is None else stdin).read().strip()
    else:
        token = read_secret(f'Personal access token for {forge.host} (input hidden): ').strip()
    if not token:
        emit('[forge] no token given; nothing was stored', err=True)
        return _USAGE
    try:
        who = login(forge, token, cwd=root, env=env, transport=transport)
    except ForgeCallFailed as failed:
        emit(f'[forge] {forge.host} did not accept the token; it was NOT stored. {failed}', err=True)
        emit(failed.report.attempts[-1].output, err=True)
        return 1
    except NoCredential as refused:
        emit(f'[forge] {refused}', err=True)
        return 1
    emit(f'[forge] {forge.host}: authenticated as {who}; stored with git credential for https://{forge.host}')
    return 0


def _check(forge: Forge, root: Path, env: Mapping[str, str] | None, transport: Transport) -> int:
    where = f'{forge.host}/{forge.owner}/{forge.repo}'
    if why := tick_refusal(forge, cwd=root, env=env, transport=transport):
        emit(f'[forge] {where}: {why}. A tick needs a token with the scopes {TICK_SCOPES}: '
             'python -m dev_lab.dev.forge auth login', err=True)  # fmt: skip
        return 1
    emit(f'[forge] {where}: the stored token can do everything a tick does')
    return 0


def _status(forge: Forge, root: Path, env: Mapping[str, str] | None, transport: Transport) -> int:
    try:
        who = status(forge, cwd=root, env=env, transport=transport)
    except NoCredential:
        emit(f'[forge] {forge.host}: no token. Run: python -m dev_lab.dev.forge auth login', err=True)
        return 1
    except ForgeCallFailed as failed:
        emit(f'[forge] {forge.host}: the token did not authenticate. {failed}', err=True)
        emit(failed.report.attempts[-1].output, err=True)
        return 1
    emit(f'[forge] {forge.host}: token from git credential; authenticated as {who}')
    return 0
