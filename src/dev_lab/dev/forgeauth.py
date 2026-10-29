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

ONE COMMAND MOVES EVERY FORGE CREDENTIAL TO A NEW BOX::

    python -m dev_lab.dev.forge auth export |
        ssh <box> "cd <checkout> && <venv python> -m dev_lab.dev.forge auth login --from-file -"

``auth export`` writes a KEY FILE to stdout -- one line ``<username>@<host> <token>`` per credential git
holds for each forge host the family uses (:func:`family_hosts`: every remote of every checkout beside
this one, plus ``github.com``), ``#`` comments and blank lines ignored. It refuses a terminal stdout, so a
token is never painted on a screen; stderr carries counts, names and sha256 prefixes only. ``auth login
--from-file <path|->`` reads the file WHOLE: every line parsed, every token verified, and only then is any
stored, each under its file username. A GCM OAuth access token (username ``OAUTH_USER``) travels too but
expires; that host re-authenticates through GCM on its first push.

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
import hashlib
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final, NamedTuple, TextIO

import lab_commons.launch as _door
from lab_commons.credentials import _GIT, _GIT_TIMEOUT_S
from lab_commons.log import emit

from dev_lab.dev._forgebackends import GITHUB_HOST
from dev_lab.dev.forge import (
    Forge,
    NoCredential,
    Transport,
    UnreadableRemote,
    credential_for,
    forge_from_remote,
    forge_of_url,
    https_transport,
    store_credential,
)
from dev_lab.dev.forgework import Client, ForgeCallFailed, stored_client
from dev_lab.dev.venvpath import running_interpreter
from dev_lab.dev.worktreeplace import family_root

__all__ = [
    'TICK_SCOPES',
    'KeyLine',
    'family_hosts',
    'format_key_file',
    'login',
    'main',
    'parse_key_file',
    'status',
    'tick_refusal',
]

#: The exit status for a usage error, as argparse uses it.
_USAGE = 2

#: A key file line's fields: ``<username>@<host>`` and the token.
_KEY_FIELDS: Final = 2
# A host the token is SENT to: a DNS name, an IPv4 or a bracketed IPv6, with an optional numeric port -- never a path,
# query, fragment or userinfo, which would turn a key file into a forwarder of the token to any URL.
_LABEL: Final = r'[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?'
_HOST: Final = re.compile(rf'(?:{_LABEL}(?:\.{_LABEL})*|\[[0-9A-Fa-f:.]+\])(?::[0-9]{{1,5}})?')

#: The token scopes a tick needs, as the forge's token page names them.
TICK_SCOPES: Final = 'repository (read and write), issue (read and write), user (read)'


class KeyLine(NamedTuple):
    """One credential of a key file: ``<username>@<host> <token>``."""

    host: str
    username: str
    token: str


def format_key_file(keys: Sequence[KeyLine]) -> str:
    """The key file :func:`parse_key_file` reads back: one ``<username>@<host> <token>`` line per key."""
    head = '# forge credentials: python -m dev_lab.dev.forge auth login --from-file <this file|->\n'
    return head + ''.join(f'{k.username}@{k.host} {k.token}\n' for k in keys)


def parse_key_file(text: str) -> tuple[KeyLine, ...]:
    """Every key of *text*; a malformed or repeated line refuses the WHOLE file, naming its number only.

    Raises:
        ValueError: a line is not ``<username>@<host> <token>``, its host is not a bare name with an optional
            port, or it names one username of a host twice.

    """
    keys: dict[tuple[str, str], KeyLine] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        fields = line.split()
        username, at, host = fields[0].rpartition('@')
        if len(fields) != _KEY_FIELDS or not (at and username and host):
            msg = f'key file line {number}: expected `<username>@<host> <token>`'
            raise ValueError(msg)
        if not _HOST.fullmatch(host):
            msg = f'key file line {number}: host is not a bare name with an optional port'
            raise ValueError(msg)
        if (host, username) in keys:
            msg = f'key file line {number}: {username}@{host} named twice'
            raise ValueError(msg)
        keys[host, username] = KeyLine(host, username, fields[1])
    return tuple(keys.values())


def family_hosts(root: Path) -> tuple[str, ...]:
    """Every forge host a remote of a family checkout (each sibling of *root*'s main checkout) lives on."""
    hosts: set[str] = set()
    for checkout in sorted(family_root(root).iterdir()):
        if not (checkout / '.git').exists():
            continue
        names = _door.run(
            [_GIT, 'remote'],
            cwd=checkout,
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
        for remote in names.stdout.split():
            try:
                hosts.add(forge_from_remote(checkout, remote=remote).host)
            except UnreadableRemote:
                continue
    return tuple(sorted(hosts))


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
    source = signin.add_mutually_exclusive_group()
    source.add_argument('--token-stdin', action='store_true', help='read the token from stdin instead of a prompt')
    source.add_argument('--from-file', metavar='PATH', help='import every key of an `auth export` file (- for stdin)')
    export = verbs.add_parser('export', help='write every stored forge credential as a key file to stdout')
    export.add_argument('--host', action='append', help='a host to export (repeatable; default: the family hosts)')
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
    stdout: TextIO | None = None,
) -> int:
    """``auth login|status|check|export`` (module docstring); nonzero when not authenticated."""
    args = _parser().parse_args(list(sys.argv[2:] if argv is None else argv))
    root = Path.cwd() if cwd is None else cwd
    stdin = sys.stdin if stdin is None else stdin
    if args.verb != 'login' or args.from_file:
        return _without_prompt(args, root, env, transport, stdin=stdin, stdout=stdout or sys.stdout)
    forge = _forge(root, args.host)
    if args.token_stdin:
        token = stdin.read().strip()
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


def _without_prompt(
    args: argparse.Namespace,
    root: Path,
    env: Mapping[str, str] | None,
    transport: Transport,
    *,
    stdin: TextIO,
    stdout: TextIO,
) -> int:
    """Every verb but an interactive ``login``: ``export``, ``login --from-file``, ``check``, ``status``."""
    if args.verb == 'export':
        return _export(args.host or [*family_hosts(root), GITHUB_HOST], root, env, stdout)
    if args.verb == 'login':
        text = stdin.read() if args.from_file == '-' else Path(args.from_file).read_text(encoding='utf-8')
        return _import(text, root, env, transport)
    if args.verb == 'check':
        return _check(forge_of_url(args.url) if args.url else forge_from_remote(root), root, env, transport)
    return _status(_forge(root, args.host), root, env, transport)


def _check(forge: Forge, root: Path, env: Mapping[str, str] | None, transport: Transport) -> int:
    where = f'{forge.host}/{forge.owner}/{forge.repo}'
    if why := tick_refusal(forge, cwd=root, env=env, transport=transport):
        emit(f'[forge] {where}: {why}. A tick needs a token with the scopes {TICK_SCOPES}: '
             f'{running_interpreter()} -m dev_lab.dev.forge auth login', err=True)  # fmt: skip
        return 1
    emit(f'[forge] {where}: the stored token can do everything a tick does')
    return 0


def _status(forge: Forge, root: Path, env: Mapping[str, str] | None, transport: Transport) -> int:
    try:
        who = status(forge, cwd=root, env=env, transport=transport)
    except NoCredential:
        emit(f'[forge] {forge.host}: no token. Run: {running_interpreter()} -m dev_lab.dev.forge auth login', err=True)
        return 1
    except ForgeCallFailed as failed:
        emit(f'[forge] {forge.host}: the token did not authenticate. {failed}', err=True)
        emit(failed.report.attempts[-1].output, err=True)
        return 1
    emit(f'[forge] {forge.host}: token from git credential; authenticated as {who}')
    return 0


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:8]


def _export(hosts: Sequence[str], root: Path, env: Mapping[str, str] | None, out: TextIO) -> int:
    if out.isatty():
        emit('[forge] auth export writes secrets: pipe or redirect it, never to a terminal', err=True)
        return _USAGE
    keys, missing = [], []
    for host in dict.fromkeys(hosts):
        try:
            username, token = credential_for(host, cwd=root, env=env)
        except NoCredential:
            missing.append(host)
            continue
        keys.append(KeyLine(host, username, token))
    out.write(format_key_file(keys))
    out.flush()
    named = ', '.join(f'{k.username}@{k.host} sha256:{_digest(k.token)}' for k in keys)
    emit(f'[forge] exported {len(keys)} credential(s): {named or "none"}', err=True)
    if missing:
        emit(f'[forge] no credential stored for: {", ".join(missing)}', err=True)
    return 0 if keys else 1


def _import(text: str, root: Path, env: Mapping[str, str] | None, transport: Transport) -> int:
    try:
        keys = parse_key_file(text)
    except ValueError as malformed:
        emit(f'[forge] {malformed}; nothing was stored', err=True)
        return _USAGE
    if not keys:
        emit('[forge] the key file holds no credential; nothing was stored', err=True)
        return _USAGE
    for key in keys:
        try:
            Client(Forge(key.host, '', ''), key.token, transport=transport).whoami()
        except ForgeCallFailed as failed:
            emit(
                f'[forge] {key.host} refused the token of {key.username}: NOT stored, nor any other. {failed}', err=True
            )
            return 1
    try:
        for key in keys:
            store_credential(key.host, key.username, key.token, cwd=root, env=env)
    except NoCredential as refused:
        emit(f'[forge] {refused}', err=True)
        return 1
    emit(f'[forge] stored {len(keys)} credential(s): {", ".join(f"{k.username}@{k.host}" for k in keys)}')
    return 0
