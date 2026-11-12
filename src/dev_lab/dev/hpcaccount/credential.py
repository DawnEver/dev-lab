"""``python -m dev_lab.dev.hpcaccount credential <user@host> --login <forge login> [--url <repo url>]`` < token.

PLACES ONE MINTED FORGE TOKEN ON A KEY-ONLY CLUSTER ACCOUNT (user ruling 2026-11-12: agents place tokens
themselves). The token is read from THIS process's stdin, never argv; everything printed names it only by a sha256
prefix. It reaches the account as the remote command's STDIN, through the grant's own key-only connection
(:func:`lab_commons.hpc.cluster.runner_for`: one shared connection per host, paced) -- the door every other
``hpcaccount`` verb uses; no new kind of connection.

On the account it replaces ONLY the line for that forge host in ``~/.git-credentials``, keeps every other line, and
writes the file under ``umask 077`` with mode 0600 by an atomic ``mv`` (:func:`place_command`). Then the forge's own
``auth role`` (:func:`dev_lab.dev.hpcaccount.account.role_of`'s verb), run in the account's declared checkout, must
answer as ``--login``; another login is refused naming it.

DECLARED ONLY: the account must hold a ``[[hpc.grant]]`` and the login must be declared -- a role's ``reader``
(:mod:`~dev_lab.dev.hpcaccount.division`) or an ``[ops.forge.accounts]`` login; when the account's role names a
reader, the login must be that reader. Anything else is refused before any connection.

``--url`` is a repository url on the forge (``auth role`` reads permissions on a repository); without it, the
account's own dev-lab checkout's ``origin``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import sys
import tomllib
from collections.abc import Callable, Collection, Sequence
from pathlib import PurePosixPath
from typing import Final
from urllib.parse import quote, urlsplit

from lab_commons.config import section
from lab_commons.hpc.cluster import Runner, runner_for
from lab_commons.hpc.grants import Grant, load_grants
from lab_commons.log import emit

from dev_lab.dev.hpcaccount.division import Division, split_hpc
from dev_lab.dev.hpcaccount.fleet import Target, declared_target, in_checkout
from dev_lab.dev.hpcaccount.spec import KIT

__all__ = ['declared_logins', 'digest', 'main', 'place_command', 'place_credential']

_HOST: Final = re.compile(r'[A-Za-z0-9.-]+')


def digest(token: str) -> str:
    """The only form of a token any output carries: ``sha256:<12 hex>``."""
    return f'sha256:{hashlib.sha256(token.encode()).hexdigest()[:12]}'


def place_command(forge_host: str) -> str:
    """The shell line that replaces *forge_host*'s line of ``~/.git-credentials`` with the one line on its stdin.

    Every other line is kept; the new file is written under ``umask 077``, ``chmod 600`` and moved into place
    atomically. The credential line is read by the shell's ``read`` and written by its ``printf`` builtin, so it
    is in no process's argv.
    """
    if not _HOST.fullmatch(forge_host):
        msg = f'not a forge host name: {forge_host!r}'
        raise ValueError(msg)
    own = r'^https?://[^@/]*@' + forge_host.replace('.', r'\.') + r'(:[0-9]+)?/?$'
    return (
        'umask 077 && IFS= read -r line && f="$HOME/.git-credentials" && t="$(mktemp "$f.XXXXXX")" && '
        f'{{ {{ grep -v -E {shlex.quote(own)} "$f" 2>/dev/null || true; }} && printf \'%s\\n\' "$line"; }} > "$t" '
        '&& chmod 600 "$t" && mv -f "$t" "$f"'
    )


def declared_logins(division: Division, ops: dict[str, object]) -> frozenset[str]:
    """Every forge login declared on this machine: each role's ``reader`` and each ``[ops.forge.accounts]`` key."""
    forge = ops.get('forge', {})
    accounts = forge.get('accounts', {}) if isinstance(forge, dict) else {}
    readers = {str(table['reader']) for table in division.roles.values() if table.get('reader')}
    return frozenset(readers | set(accounts))


def _refusal(grant: Grant | None, account: str, *, login: str, logins: Collection[str], division: Division) -> str:
    """Why *account* may not take *login*, decided before any connection; ``''`` when it may."""
    user, _, host = account.partition('@')
    if grant is None:
        return f'{user} holds no [[hpc.grant]]'
    if host not in grant.hosts and host not in {h.split('.', 1)[0] for h in grant.hosts}:
        return f'{host} is not a login host of {user} {list(grant.hosts)}'
    if login not in logins:
        return (
            f'the forge login {login!r} is not declared ([hpc.roles.*] reader, [ops.forge.accounts]): {sorted(logins)}'
        )
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
    grants: Sequence[Grant],
    division: Division,
    logins: Collection[str],
    say: Callable[[str], None],
    connect: Callable[[Grant], Runner] = runner_for,
) -> int:
    """Place *token* as *login* on *account* (``user@host``) and verify the forge answers as *login*; 2 on refusal."""
    user = account.partition('@')[0]
    grant = next((g for g in grants if g.user == user), None)
    why = 'no token on stdin' if not token else _refusal(grant, account, login=login, logins=logins, division=division)
    if why or grant is None:
        say(f'credential: refused -- {why}')
        return 2
    shell = connect(grant)
    try:
        target = declared_target(grant, shell)
        if isinstance(target, str):
            say(f'credential: {target}')
            return 2
        repo = url or _origin(shell, target)
        forge_host = urlsplit(repo).hostname or ''
        line = f'https://{quote(login, safe="")}:{quote(token, safe="")}@{forge_host}'
        shell(place_command(forge_host), line + '\n')
        say(f'{user}: placed {login} {digest(token)} for {forge_host} in ~/.git-credentials (0600)')
        seen = json.loads(shell(in_checkout(target, ['-m', 'dev_lab.dev.forge', 'auth', 'role', '--url', repo]), None))
    except (RuntimeError, OSError, ValueError, tomllib.TOMLDecodeError) as failed:
        say(f'credential: refused -- {user}: {failed}')
        return 2
    if (answered := str(seen.get('login') or '')) != login:
        say(f'credential: refused -- the forge answers {repo} as {answered or "anonymous"}, not {login}')
        return 2
    say(f'{user}: the forge answers as {login} on {repo}')
    return 0


def _origin(shell: Runner, target: Target) -> str:
    return shell(f'git -C {PurePosixPath("~", target.root, KIT)} remote get-url origin', None).strip()


def parser() -> argparse.ArgumentParser:
    """The ``credential`` command line: the one source of its usage (:func:`usage`)."""
    made = argparse.ArgumentParser(prog='dev_lab.dev.hpcaccount credential', description=__doc__.splitlines()[0])
    made.add_argument('account', metavar='<user>@<login host>', help='a declared [[hpc.grant]] account')
    made.add_argument(
        '--login', required=True, metavar='<forge login>', help='the declared forge login the token belongs to'
    )
    made.add_argument(
        '--url', default='', metavar='<repo url>', help="a repository url on the forge (default: the kit's origin)"
    )
    return made


def usage() -> str:
    """The command's shape as :func:`parser` renders it, ``hpcaccount credential ...``, the help flag left out."""
    said = ' '.join(parser().format_usage().split())
    return said.removeprefix('usage: dev_lab.dev.').replace(' [-h]', '')


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``credential``, read the token from stdin and place it."""
    args = parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    table, division = split_hpc(section('hpc'))
    return place_credential(
        args.account,
        login=args.login,
        token=sys.stdin.read().strip(),
        url=args.url,
        grants=load_grants(table).grants,
        division=division,
        logins=declared_logins(division, section('ops')),
        say=emit,
    )
