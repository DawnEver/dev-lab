"""``hpcaccount credential <user@host> --login L --host-config F [--url U]`` < token; or ``--drop-host H``.

PLACES ONE MINTED FORGE TOKEN ON A KEY-ONLY CLUSTER ACCOUNT (user ruling 2026-11-12: agents place tokens
themselves). The token is read from THIS process's stdin, never argv; everything printed names it only by a sha256
prefix. It reaches the account as the remote command's STDIN, through the grant's own key-only connection
(:func:`lab_commons.hpc.cluster.runner_for`: one shared connection per host, paced) -- the door every other
``hpcaccount`` verb uses; no new kind of connection.

THE FORGE IS THE HOST CONFIG'S. The forge accounts have ONE source: the forge host's reviewed config
(``--host-config``, a checkout of its config source), read by the loader ``config apply`` validates it with
(:func:`dev_lab.ops.config.load`, structure only) -- never a copy in this machine's file. Its public host is the site
it serves (``[ops.caddy] sites``). ``--url`` must be a repository on that host; without it, the first of the login's
``[ops.forge.accounts.<login>] repos`` there. A url on any other host (the account's own GitHub origin, say) is
refused before any connection: placing a forge token under another host's line destroyed that line once
(2026-11-12). A host config that cannot be read, or declares no accounts or site, is refused naming it.

VERIFIED BEFORE IT REPLACES. The line is staged alone in ``~/.git-credentials.new-<ts>`` (umask 077) and the forge's
own ``auth role`` (:func:`dev_lab.dev.hpcaccount.account.role_of`'s verb), run in the account's declared checkout
with git's credential helper pointed at ONLY that file, must answer as ``--login``. Only then is the store rewritten
(:func:`rewrite_command`): a backup ``~/.git-credentials.bak-<ts>`` (0600) first, then every other line kept, the
forge's line replaced, mode 0600, atomic ``mv``. A refusal deletes the staged file and leaves the store untouched.
``--drop-host H`` removes exactly H's line through the same rewrite and backup -- the repair for a damaged line.

DECLARED ONLY: the account must hold a ``[[hpc.grant]]`` and the login must be declared -- a role's ``reader``
(:mod:`~dev_lab.dev.hpcaccount.division`) or an ``[ops.forge.accounts]`` login; when the account's role names a
reader, the login must be that reader. Anything else is refused before any connection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import sys
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from urllib.parse import quote, urlsplit

from lab_commons.config import section
from lab_commons.hpc.cluster import Runner, runner_for
from lab_commons.hpc.grants import Grant, load_grants
from lab_commons.log import emit

from dev_lab.dev.hpcaccount.division import Division, split_hpc
from dev_lab.dev.hpcaccount.fleet import declared_target, in_checkout
from dev_lab.ops.config import load as load_host_config

__all__ = [
    'CredentialRefused',
    'DeclaredForge',
    'declared_logins',
    'digest',
    'discard_command',
    'drop_host',
    'main',
    'place_credential',
    'read_forge',
    'rewrite_command',
    'stage_command',
    'stamp_now',
    'verify_prefix',
]

#: The store git's ``credential.helper store`` reads, under ``$HOME``.
STORE: Final = '.git-credentials'
_HOST: Final = re.compile(r'[A-Za-z0-9.-]+')
_STAMP: Final = re.compile(r'[0-9]{8}T[0-9]{6}Z')


def digest(token: str) -> str:
    """The only form of a token any output carries: ``sha256:<12 hex>``."""
    return f'sha256:{hashlib.sha256(token.encode()).hexdigest()[:12]}'


def stamp_now() -> str:
    """The UTC timestamp a staged file and a backup are named by."""
    return datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')


def _checked(host: str, stamp: str) -> None:
    if not _HOST.fullmatch(host):
        msg = f'not a forge host name: {host!r}'
        raise ValueError(msg)
    if not _STAMP.fullmatch(stamp):
        msg = f'not a timestamp: {stamp!r}'
        raise ValueError(msg)


def _staged(stamp: str) -> str:
    _checked('x', stamp)
    return f'"$HOME/{STORE}.new-{stamp}"'


def stage_command(stamp: str) -> str:
    """The shell line that writes the one line on its stdin, alone, to ``~/.git-credentials.new-<stamp>`` (0600).

    The line is read by the shell's ``read`` and written by its ``printf`` builtin, so it is in no process's argv.
    """
    return f'umask 077 && IFS= read -r line && printf \'%s\\n\' "$line" > {_staged(stamp)}'


def verify_prefix(stamp: str) -> str:
    """The exports that make git's credential helper read ONLY the staged file (an empty helper resets the list)."""
    _checked('x', stamp)
    return (
        'export GIT_CONFIG_COUNT=2 GIT_CONFIG_KEY_0=credential.helper GIT_CONFIG_VALUE_0= '
        f'GIT_CONFIG_KEY_1=credential.helper GIT_CONFIG_VALUE_1="store --file=$HOME/{STORE}.new-{stamp}" && '
    )


def discard_command(stamp: str) -> str:
    """The shell line that deletes the staged file; the store is untouched."""
    return f'rm -f {_staged(stamp)}'


def rewrite_command(host: str, stamp: str, *, staged: bool) -> str:
    """The shell line that backs up ``~/.git-credentials`` and removes *host*'s line -- replaced by the staged one.

    The backup ``~/.git-credentials.bak-<stamp>`` (0600) is taken when a store exists and its path echoed; every
    other line is kept; the new file is written under ``umask 077``, ``chmod 600`` and moved into place atomically.
    """
    _checked(host, stamp)
    own = r'^https?://[^@/]*@' + host.replace('.', r'\.') + r'(:[0-9]+)?/?$'
    add, done = (f' && cat {_staged(stamp)}', f' && rm -f {_staged(stamp)}') if staged else ('', '')
    return (
        f'umask 077 && f="$HOME/{STORE}" && b="$f.bak-{stamp}" && '
        '{ [ ! -e "$f" ] || { cp "$f" "$b" && chmod 600 "$b" && echo "backup $b"; }; } && t="$(mktemp "$f.XXXXXX")" '
        f'&& {{ {{ grep -v -E {shlex.quote(own)} "$f" 2>/dev/null || true; }}{add}; }} > "$t" '
        f'&& chmod 600 "$t" && mv -f "$t" "$f"{done}'
    )


class CredentialRefused(ValueError):
    """The declared forge could not be read, or a url is not on it: what was refused, never a token."""


@dataclass(frozen=True)
class DeclaredForge:
    """The forge a host config declares: the *sites* it serves and each login's repositories."""

    path: Path
    sites: tuple[str, ...]
    accounts: Mapping[str, tuple[str, ...]]

    def url_for(self, login: str, url: str) -> str:
        """*url* when it is on this forge, else (empty) the login's first declared repository here.

        Raises:
            CredentialRefused: *url* is on another host, or there is no declared repository to default to.

        """
        if url:
            if (urlsplit(url).hostname or '') not in self.sites:
                msg = f'{url} is not on the forge {list(self.sites)} the host config {self.path} declares'
                raise CredentialRefused(msg)
            return url
        repos = self.accounts.get(login, ())
        if not repos or len(self.sites) != 1:
            msg = f'{login} has no repository on one declared site {list(self.sites)} in {self.path}: give --url'
            raise CredentialRefused(msg)
        return f'https://{self.sites[0]}/{repos[0]}.git'


def read_forge(host_config: Path) -> DeclaredForge:
    """The forge *host_config* declares: ``[ops.caddy] sites`` and ``[ops.forge.accounts]``.

    Raises:
        CredentialRefused: *host_config* cannot be read, or declares no accounts or no site.

    """
    try:
        config = load_host_config(host_config, structure_only=True, alerts=False)
    except (OSError, ValueError, TypeError, tomllib.TOMLDecodeError) as failed:
        msg = f'the host config {host_config} could not be read: {failed}'
        raise CredentialRefused(msg) from failed
    forge, caddy = config.forge, config.caddy
    if forge is None or not forge.accounts or caddy is None or not caddy.sites:
        msg = f'the host config {host_config} declares no [ops.forge.accounts] and [ops.caddy] sites: not a forge'
        raise CredentialRefused(msg)
    accounts = {login: tuple(row.get('repos', ())) for login, row in forge.accounts.items()}
    return DeclaredForge(host_config, tuple(caddy.sites), accounts)


def declared_logins(division: Division, forge: DeclaredForge) -> frozenset[str]:
    """Every declared forge login: each role's ``reader`` and each of *forge*'s accounts."""
    readers = {str(table['reader']) for table in division.roles.values() if table.get('reader')}
    return frozenset(readers | set(forge.accounts))


def _grant_refusal(grant: Grant | None, account: str) -> str:
    user, _, host = account.partition('@')
    if grant is None:
        return f'{user} holds no [[hpc.grant]]'
    if host not in grant.hosts and host not in {h.split('.', 1)[0] for h in grant.hosts}:
        return f'{host} is not a login host of {user} {list(grant.hosts)}'
    return ''


def _refusal(grant: Grant | None, account: str, *, login: str, forge: DeclaredForge, division: Division) -> str:
    """Why *account* may not take *login*, decided before any connection; ``''`` when it may."""
    if why := _grant_refusal(grant, account):
        return why
    user = account.partition('@')[0]
    if login not in (logins := declared_logins(division, forge)):
        declared = '[hpc.roles.*] reader, the host config [ops.forge.accounts]'
        return f'the forge login {login!r} is not declared ({declared}): {sorted(logins)}'
    reader = str(division.roles.get(division.role_of(user), {}).get('reader', ''))
    if reader and login != reader:
        return f"{user}'s role {division.role_of(user)!r} reads as {reader!r}, not {login!r}"
    return ''


def place_credential(
    account: str,
    *,
    login: str,
    token: str,
    url: str,
    forge: DeclaredForge,
    grants: Sequence[Grant],
    division: Division,
    say: Callable[[str], None],
    connect: Callable[[Grant], Runner] = runner_for,
    stamp: str = '',
) -> int:
    """Stage *token* as *login* on *account*, verify the forge answers as *login*, then replace; 2 on refusal."""
    user = account.partition('@')[0]
    grant = next((g for g in grants if g.user == user), None)
    try:
        why = (
            'no token on stdin' if not token else _refusal(grant, account, login=login, forge=forge, division=division)
        )
        repo = forge.url_for(login, url)
    except CredentialRefused as refused:
        why = str(refused)
    if why or grant is None:
        say(f'credential: refused -- {why}')
        return 2
    stamp, host = stamp or stamp_now(), urlsplit(repo).hostname or ''
    shell = connect(grant)
    try:
        target = declared_target(grant, shell)
        if isinstance(target, str):
            say(f'credential: {target}')
            return 2
        shell(stage_command(stamp), f'https://{quote(login, safe="")}:{quote(token, safe="")}@{host}\n')
        role = in_checkout(target, ['-m', 'dev_lab.dev.forge', 'auth', 'role', '--url', repo])
        try:
            answered = str(json.loads(shell(verify_prefix(stamp) + role, None)).get('login') or '')
        except (RuntimeError, OSError, ValueError) as failed:
            answered = f'an error ({failed})'
        if answered != login:
            shell(discard_command(stamp), None)
            say(
                f'credential: refused -- the forge answers {repo} as {answered or "anonymous"}, not {login}; '
                f'~/{STORE} untouched'
            )
            return 2
        backup = shell(rewrite_command(host, stamp, staged=True), None).strip()
    except (RuntimeError, OSError, ValueError) as failed:
        say(f'credential: refused -- {user}: {failed}')
        return 2
    say(f'{user}: the forge answers as {login} on {repo}; placed {digest(token)} for {host} (0600) {backup}'.strip())
    return 0


def drop_host(
    account: str,
    *,
    host: str,
    grants: Sequence[Grant],
    say: Callable[[str], None],
    connect: Callable[[Grant], Runner] = runner_for,
    stamp: str = '',
) -> int:
    """Remove exactly *host*'s line of *account*'s ``~/.git-credentials``, after a backup; 2 on refusal."""
    user = account.partition('@')[0]
    grant = next((g for g in grants if g.user == user), None)
    why = _grant_refusal(grant, account) or ('' if _HOST.fullmatch(host) else f'not a host name: {host!r}')
    if why or grant is None:
        say(f'credential: refused -- {why}')
        return 2
    try:
        backup = connect(grant)(rewrite_command(host, stamp or stamp_now(), staged=False), None).strip()
    except (RuntimeError, OSError) as failed:
        say(f'credential: refused -- {user}: {failed}')
        return 2
    say(f'{user}: dropped the {host} line of ~/{STORE} {backup}'.strip())
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``credential``; place the token on stdin, or drop a host's line."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.hpcaccount credential', description=__doc__.splitlines()[0])
    parser.add_argument('account', help='<user>@<login host> of a declared [[hpc.grant]]')
    verb = parser.add_mutually_exclusive_group(required=True)
    verb.add_argument('--login', help='the declared forge login the token on stdin belongs to')
    verb.add_argument('--drop-host', help="remove exactly this host's line (after a backup)")
    parser.add_argument('--host-config', type=Path, help="the forge host's reviewed config (with --login)")
    parser.add_argument('--url', default='', help="a repository url on the host config's forge (with --login)")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    if args.drop_host:
        return drop_host(
            args.account, host=args.drop_host, grants=load_grants(split_hpc(section('hpc'))[0]).grants, say=emit
        )
    if args.host_config is None:
        parser.error('--login needs --host-config')
    try:
        forge = read_forge(args.host_config)
    except CredentialRefused as refused:
        emit(f'credential: refused -- {refused}')
        return 2
    table, division = split_hpc(section('hpc'))
    grants = load_grants(table).grants
    token = sys.stdin.read().strip()
    return place_credential(
        args.account, login=args.login, token=token, url=args.url, forge=forge, grants=grants, division=division,
        say=emit,
    )  # fmt: skip
