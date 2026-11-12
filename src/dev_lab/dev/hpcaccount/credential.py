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
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from urllib.parse import urlsplit

from lab_commons.config import section
from lab_commons.hpc.cluster import Runner, runner_for
from lab_commons.hpc.grants import Grant, load_grants
from lab_commons.log import emit

from dev_lab.dev.credstore import (
    STORE,
    CredentialRefused,
    DeclaredForge,
    digest,
    place_verified,
    read_forge,
    rewrite_command,
    stamp_now,
    valid_host,
)
from dev_lab.dev.hpcaccount.division import Division, split_hpc
from dev_lab.dev.hpcaccount.fleet import declared_target, in_checkout

__all__ = [
    'declared_logins',
    'drop_host',
    'main',
    'place_credential',
]


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
    shell = connect(grant)
    try:
        target = declared_target(grant, shell)
        if isinstance(target, str):
            say(f'credential: {target}')
            return 2
        role = in_checkout(target, ['-m', 'dev_lab.dev.forge', 'auth', 'role', '--url', repo])
        refusal, backup = place_verified(shell, login=login, token=token, repo=repo, role=role, stamp=stamp)
    except (RuntimeError, OSError, ValueError) as failed:
        say(f'credential: refused -- {user}: {failed}')
        return 2
    if refusal:
        say(f'credential: refused -- {refusal}')
        return 2
    host = urlsplit(repo).hostname or ''
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
    why = _grant_refusal(grant, account) or ('' if valid_host(host) else f'not a host name: {host!r}')
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


def parser() -> argparse.ArgumentParser:
    """The ``credential`` command line: the one source of its usage (:func:`usage`)."""
    made = argparse.ArgumentParser(prog='dev_lab.dev.hpcaccount credential', description=__doc__.splitlines()[0])
    made.add_argument('account', metavar='<user>@<login host>', help='a declared [[hpc.grant]] account')
    verb = made.add_mutually_exclusive_group(required=True)
    verb.add_argument('--login', metavar='<forge login>', help='the declared forge login the token on stdin belongs to')
    verb.add_argument('--drop-host', metavar='<host>', help="remove exactly this host's line (after a backup)")
    made.add_argument(
        '--host-config', type=Path, metavar='<host config>', help="the forge host's reviewed config (with --login)"
    )
    made.add_argument(
        '--url', default='', metavar='<repo url>', help="a repository url on the host config's forge (with --login)"
    )
    return made


def usage() -> str:
    """The command's shape as :func:`parser` renders it, ``hpcaccount credential ...``, the help flag left out."""
    said = ' '.join(parser().format_usage().split())
    return said.removeprefix('usage: dev_lab.dev.').replace(' [-h]', '')


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``credential``; place the token on stdin, or drop a host's line."""
    made = parser()
    args = made.parse_args(list(sys.argv[1:] if argv is None else argv))
    if args.drop_host:
        return drop_host(
            args.account, host=args.drop_host, grants=load_grants(split_hpc(section('hpc'))[0]).grants, say=emit
        )
    if args.host_config is None:
        made.error('--login needs --host-config')
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
