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

``auth role --url <repo url>`` prints, as one JSON object, who the stored credential is on that repository and
whether it may write there (``{"login", "push", "admin"}``; an empty login when git holds none, so git pulls
anonymously). The hpcaccount deploy reads it to refuse a research account pulling with a writer (user ruling
2026-11-09).

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
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final, NamedTuple, TextIO

import lab_commons.launch as _door
from lab_commons.credentials import _GIT, _GIT_TIMEOUT_S
from lab_commons.log import emit

from dev_lab.dev import forgeverdict
from dev_lab.dev._forgebackends import GITHUB_HOST
from dev_lab.dev.forge import (
    AUTH_REFUSED,
    Forge,
    NoCredential,
    Transport,
    UnreadableRemote,
    credential_for,
    forge_from_remote,
    forge_of_url,
    forge_transport,
    store_credential,
)
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgekeyfile import KeyLine, format_key_file, parse_key_file
from dev_lab.dev.forgework import Client, stored_client
from dev_lab.dev.netverb import Diagnosis
from dev_lab.dev.venvpath import running_interpreter
from dev_lab.dev.worktreeplace import family_root

__all__ = [
    'TICK_SCOPES',
    'UNREACHABLE',
    'UNREACHABLE_EXIT',
    'RepoRole',
    'family_hosts',
    'login',
    'main',
    'repo_role',
    'status',
    'tick_refusal',
]

#: The exit status for a usage error, as argparse uses it.
_USAGE = 2

#: The token scopes a tick needs, as the forge's token page names them.
TICK_SCOPES: Final = 'repository (read and write), issue (read and write), user (read)'


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
    forge: Forge, token: str, *, cwd: Path, env: Mapping[str, str] | None = None, transport: Transport = forge_transport
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
    forge: Forge, *, cwd: Path, env: Mapping[str, str] | None = None, transport: Transport = forge_transport
) -> str:
    """The login the stored token authenticates as.

    Raises:
        NoCredential: git holds no credential for the host.
        ForgeCallFailed: a token was found and the forge did not accept it.

    """
    return stored_client(forge, cwd=cwd, env=env, transport=transport).whoami()


class RepoRole(NamedTuple):
    """Who the stored credential is on one repository and whether it may write there."""

    login: str
    push: bool
    admin: bool


def repo_role(
    forge: Forge, *, cwd: Path, env: Mapping[str, str] | None = None, transport: Transport = forge_transport
) -> RepoRole:
    """*forge*'s repository as the stored credential sees it; an empty login when git holds none.

    Raises:
        ForgeCallFailed: the forge refused the credential or the repository read.

    """
    try:
        client = stored_client(forge, cwd=cwd, env=env, transport=transport)
    except NoCredential:
        return RepoRole('', push=False, admin=False)
    permissions = client.call('GET', client.repo).get('permissions') or {}
    return RepoRole(client.whoami(), push=bool(permissions.get('push')), admin=bool(permissions.get('admin')))


#: The exit of ``auth check|status`` when the forge could not be asked: no answer, a 5xx, an unmeasured 401/403.
#: EX_TEMPFAIL, so a caller tells it from a refusal (exit 1) by the code, never by reading the message.
UNREACHABLE_EXIT: Final = 75

#: The lead of the message ``auth check|status`` give with :data:`UNREACHABLE_EXIT`.
UNREACHABLE: Final = 'the forge did not answer -- NOT a token fault, do not re-store it; re-run the same command'


def tick_refusal(
    forge: Forge, *, cwd: Path, env: Mapping[str, str] | None = None, transport: Transport = forge_transport
) -> str:
    """What the forge API refuses the stored credential that a tick needs on *forge*'s repo; ``''`` when nothing.

    Only an ANSWERED refusal is named: a credential refusal measured against ``GET /user`` or a final refusal of
    the call (:class:`~dev_lab.dev.forgefailure.ForgeCallFailed`). Anything else -- no answer, a 5xx, a 401/403
    the measurement did not confirm -- is no verdict on the token, and is raised after the bounded retries.

    Raises:
        ForgeCallFailed: the forge could not be asked; retrying the same command is the remedy.

    """
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
    """Whether *call* answered; ``False`` only for an answered refusal, a transient is re-raised."""
    try:
        call()
    except ForgeCallFailed as failed:
        if _refusal(failed):
            return False
        raise
    return True


def _refusal(failed: ForgeCallFailed) -> bool:
    """An ANSWERED refusal: measured, final, or a 401/403 every attempt was answered with (a missing scope).

    Gitea's transient "Failed to authenticate user" clears on the next attempt, so a 401/403 that held on every
    one of the bounded attempts is the forge's answer; one that came with a dropped connection, a 5xx or a rate
    limit on any attempt is not.
    """
    if failed.credential_refused or failed.final is not None:
        return True
    attempts = failed.report.attempts
    held = all(a.returncode in AUTH_REFUSED and a.diagnosis is not Diagnosis.RATE_LIMITED for a in attempts)
    return bool(attempts) and len(attempts) == failed.report.allowed_attempts and held


def _unreachable(where: str, failed: ForgeCallFailed) -> int:
    attempts = len(failed.report.attempts)
    emit(f'[forge] {where}: {UNREACHABLE} ({attempts} attempts). {failed}', err=True)
    return UNREACHABLE_EXIT


def _settle(host: str, digest: str, why: str) -> None:
    """The feedback: remember a reported refusal, or settle one now that the host answered."""
    if why:
        forgeverdict.refused(host, digest, why)
    elif misread := forgeverdict.answered(host, digest):
        emit(f'[forge] {misread}', err=True)


def _digest_of(forge: Forge, root: Path, env: Mapping[str, str] | None) -> str:
    try:
        return _digest(credential_for(forge.host, cwd=root, env=env)[1])
    except NoCredential:
        return ''


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
    role = verbs.add_parser('role', help='who the stored token is on a repository and whether it may write (JSON)')
    role.add_argument('--url', help="the repository's https url (default: this checkout's origin)")
    return parser


def _forge(root: Path, host: str | None) -> Forge:
    """The forge to authenticate against: *host* alone when given, else this checkout's origin."""
    return Forge(host, '', '') if host else forge_from_remote(root)


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    transport: Transport = forge_transport,
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
    if args.verb == 'role':
        return _role(forge_of_url(args.url) if args.url else forge_from_remote(root), root, env, transport, stdout)
    if args.verb == 'check':
        return _check(forge_of_url(args.url) if args.url else forge_from_remote(root), root, env, transport)
    return _status(_forge(root, args.host), root, env, transport)


def _check(forge: Forge, root: Path, env: Mapping[str, str] | None, transport: Transport) -> int:
    where = f'{forge.host}/{forge.owner}/{forge.repo}'
    try:
        why = tick_refusal(forge, cwd=root, env=env, transport=transport)
    except ForgeCallFailed as failed:
        return _unreachable(where, failed)
    _settle(forge.host, _digest_of(forge, root, env), why)
    if why:
        emit(f'[forge] {where}: {why}. A tick needs a token with the scopes {TICK_SCOPES}: '
             f'{running_interpreter()} -m dev_lab.dev.forge auth login', err=True)  # fmt: skip
        return 1
    emit(f'[forge] {where}: the stored token can do everything a tick does')
    return 0


def _role(forge: Forge, root: Path, env: Mapping[str, str] | None, transport: Transport, out: TextIO) -> int:
    try:
        role = repo_role(forge, cwd=root, env=env, transport=transport)
    except ForgeCallFailed as failed:
        emit(f'[forge] {forge.host}/{forge.owner}/{forge.repo}: the forge refused the role read. {failed}', err=True)
        return 1
    out.write(json.dumps(role._asdict()) + '\n')
    return 0


def _status(forge: Forge, root: Path, env: Mapping[str, str] | None, transport: Transport) -> int:
    try:
        who = status(forge, cwd=root, env=env, transport=transport)
    except NoCredential:
        emit(f'[forge] {forge.host}: no token. Run: {running_interpreter()} -m dev_lab.dev.forge auth login', err=True)
        return 1
    except ForgeCallFailed as failed:
        if not _refusal(failed):
            return _unreachable(forge.host, failed)
        _settle(forge.host, _digest_of(forge, root, env), 'GET /user refused')
        emit(f'[forge] {forge.host}: the forge refused the token. {failed}', err=True)
        emit(failed.report.attempts[-1].output, err=True)
        return 1
    _settle(forge.host, _digest_of(forge, root, env), '')
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
