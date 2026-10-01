"""``python -m lab_commons.dev.forge auth login|status`` -- one command to give a box a forge token.

WHERE THE TOKEN GOES. :func:`lab_commons.dev.forgework.token_source` reads the forge's environment
variable first and falls back to ``git credential fill`` for the host. ``auth login`` writes to that
fallback with ``git credential approve`` (``protocol=https``, the host, ``username=`` the login the
forge returned, ``password=`` the token), so the forge verbs find it AND ``git push`` over https uses
it -- one secret, kept wherever the configured helper keeps secrets (Git Credential Manager, the OS
keychain). This module writes no file and never prints the token.

VERIFIED BEFORE STORED. The token is sent to ``GET /api/v1/user`` (Gitea) or ``GET /user`` (GitHub)
first; a rejected token is reported with the forge's answer and is NOT stored, so a typo cannot
displace a credential that worked.

``auth status`` names WHERE the token came from (the variable, or ``git credential``) and the login it
authenticates as -- never the secret.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TextIO

from lab_commons.dev.forge import (
    Forge,
    NoCredential,
    Transport,
    forge_from_remote,
    https_transport,
    store_credential,
)
from lab_commons.dev.forgework import Client, ForgeCallFailed, backend_for, token_source
from lab_commons.log import emit

__all__ = ['login', 'main', 'status']

#: The exit status for a usage error, as argparse uses it.
_USAGE = 2


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
) -> tuple[str, str]:
    """``(where the token came from, the login it authenticates as)``.

    Raises:
        NoCredential: no environment variable is set and git holds no credential for the host.
        ForgeCallFailed: a token was found and the forge did not accept it.

    """
    where, token = token_source(forge, cwd=cwd, env=env)
    return where, Client(forge, token, transport=transport).whoami()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='lab_commons.dev.forge auth', description='set up or check the forge token')
    verbs = parser.add_subparsers(dest='verb', required=True)
    signin = verbs.add_parser('login', help='verify a personal access token and store it with git credential')
    signin.add_argument('--token-stdin', action='store_true', help='read the token from stdin instead of a prompt')
    check = verbs.add_parser('status', help='where the token comes from, and who it authenticates as')
    for sub in (signin, check):
        sub.add_argument('--host', help="the forge host (default: the host of this checkout's origin)")
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
        emit(f'[forge] {forge.host} did not accept the token; it was NOT stored. {failed.report.remedy}', err=True)
        emit(failed.report.attempts[-1].output, err=True)
        return 1
    except NoCredential as refused:
        emit(f'[forge] {refused}', err=True)
        return 1
    emit(f'[forge] {forge.host}: authenticated as {who}; stored with git credential for https://{forge.host}')
    _warn_if_shadowed(forge, env)
    return 0


def _status(forge: Forge, root: Path, env: Mapping[str, str] | None, transport: Transport) -> int:
    try:
        where, who = status(forge, cwd=root, env=env, transport=transport)
    except NoCredential:
        emit(f'[forge] {forge.host}: no token. Run: python -m lab_commons.dev.forge auth login', err=True)
        return 1
    except ForgeCallFailed as failed:
        emit(f'[forge] {forge.host}: the token did not authenticate. {failed.report.remedy}', err=True)
        emit(failed.report.attempts[-1].output, err=True)
        return 1
    emit(f'[forge] {forge.host}: token from {where}; authenticated as {who}')
    return 0


def _warn_if_shadowed(forge: Forge, env: Mapping[str, str] | None) -> None:
    """A set environment variable wins over the stored credential; say so rather than let it surprise."""
    source = os.environ if env is None else env
    shadowing = [name for name in backend_for(forge).token_vars if source.get(name)]
    if shadowing:
        emit(f'[forge] note: {shadowing[0]} is set in this environment and takes precedence over the stored token')
