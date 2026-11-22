"""``hpcaccount credential <user@host> --login L --host-config F [--url U]`` < token; or ``--login L --drop-host H``.

PLACES ONE MINTED FORGE TOKEN ON A KEY-ONLY CLUSTER ACCOUNT (user ruling 2026-11-12: agents place tokens
themselves). The token is read from THIS process's stdin, never argv; everything printed names it only by a sha256
prefix. It reaches the account as the remote command's STDIN, through the grant's own key-only connection
(:func:`dev_lab.dev.hpcaccount.transport.grant_runner`: one shared connection per host, paced) -- the door every other
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
A NAMED READER HAS ITS OWN FILE (2026-11-22). A verification account holds its verdict-posting login and the config
source's reader (``[hpc.roles.<role>] config_reader``, :func:`named_login`) for one forge host. The reader's line is
placed in ``~/.git-credentials.reader`` (:data:`~dev_lab.dev.credstore.READER_STORE`), never in the shared store:
git moves a line it approves to the top of the store, so the reader's own pull made it answer the unnamed request
after every deploy (measured on two accounts), whatever order a placement wrote. A line the shared store still
holds for the reader is removed by the same placement, after the store's backup, and the door refuses when one
remains. ``--login L --drop-host H`` removes exactly L's line for H from both files, each after its backup.
After a placement, git's ``store`` helper is set when NO global helper is configured (one already set is kept):
a store line git never consults reads as anonymous (measured 2026-11-20 on three research accounts).

A NAMED LOGIN NEVER TAKES THE UNNAMED REQUEST (2026-11-22). A role declares no writer by name: the writer is
whoever answers the host's unnamed request, the one a serve posts with. Around a named placement that request is
asked before and after; an answer that changed (measured: the reader shadowed the writer, the reader's own
read-back passed, every tick was refused) exits 2 naming both logins, the store put back from the placement's
backup (:func:`~dev_lab.dev.credstore.restore_command`) when the placement wrote it.

READ BACK BEFORE IT SAYS SO (2026-11-20). After the rewrite the forge's ``auth role`` runs again through git's own
helper (no staged file) -- for a named login, a fill naming it through the reader file's get-only helper
(:func:`~dev_lab.dev.credstore.named_fill_command`) must return the token -- only when
the STORED line answers as ``--login`` does the door print ``verified: ...`` and
exit 0; anything else (a failover node whose write landed nowhere) exits 2 naming what answered. ``--from-output
<name>`` reads the token from the consent output ``outputs/<name>`` (:func:`dev_lab.dev.planrunsteps.stdout_path`)
instead of stdin and deletes that file ONLY after a verified placement -- a caller never removes a token by hand.

DECLARED ONLY: the account must hold a ``[[hpc.grant]]`` and the login must be declared -- a role's ``reader``
(:mod:`~dev_lab.dev.hpcaccount.division`) or an ``[ops.forge.accounts]`` login; when the account's role names a
reader, the login must be that reader. Anything else is refused before any connection.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

from lab_commons.hpc.cluster import Runner
from lab_commons.hpc.grants import Grant
from lab_commons.log import emit

from dev_lab.dev.credstore import (
    READER_STORE,
    STORE,
    CredentialRefused,
    DeclaredForge,
    digest,
    drop_held_command,
    held_command,
    named_fill_command,
    place_verified,
    read_forge,
    restore_command,
    rewrite_command,
    stamp_now,
    valid_host,
)
from dev_lab.dev.hpcaccount.division import Division, division_of, reached_machine
from dev_lab.dev.hpcaccount.fleet import declared_target, in_checkout
from dev_lab.dev.hpcaccount.transport import grant_runner
from dev_lab.dev.planrunsteps import stdout_path

__all__ = [
    'declared_logins',
    'drop_host',
    'main',
    'named_login',
    'place_credential',
    'unreachable',
]

#: Sets git's ``store`` helper on the account only when NO helper is configured; one already set is kept.
_STORE_HELPER = (
    '[ -n "$(git config --global --get-all credential.helper)" ] || git config --global credential.helper store'
)


#: The role keys naming a forge login an account of that role may hold.
_READERS: Final = ('reader', 'config_reader')


def declared_logins(division: Division, forge: DeclaredForge) -> frozenset[str]:
    """Every declared forge login: each role's ``reader`` and ``config_reader``, and each of *forge*'s accounts."""
    readers = {str(table[key]) for table in division.roles.values() for key in _READERS if table.get(key)}
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
    table = division.roles.get(division.role_of(user), {})
    reader, config_reader = str(table.get('reader', '')), str(table.get('config_reader', ''))
    if reader and login not in {reader, config_reader}:
        also = f' (config source: {config_reader!r})' if config_reader else ''
        return f"{user}'s role {division.role_of(user)!r} reads as {reader!r}{also}, not {login!r}"
    return ''


def named_login(division: Division, user: str, login: str) -> bool:
    """Whether *user* reaches *login* only through a url naming it.

    That is its role's ``config_reader`` when it is not the login an unnamed request is for (the role's
    ``reader``; on a writer account, the writer).
    """
    return login == division.named_reader(user) != ''


def unreachable(account: str, grants: Sequence[Grant]) -> str:
    """Why *account* cannot be reached right now (a dead hold, a refused second factor); ``''`` when it can.

    Asked BEFORE the token is read: measured 2026-11-20, a placement over a dead hold printed nothing, exited 0, and
    the caller deleted a token that never arrived.
    """
    grant = next((g for g in grants if g.user == account.partition('@')[0]), None)
    if grant is None:
        return ''  # the placement refuses it by name, before any connection
    try:
        grant_runner(grant, first=account)('true', None)
    except (RuntimeError, OSError) as failed:
        return f'{account} is not reachable: {failed}'
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
    connect: Callable[[Grant], Runner] | None = None,
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
    shell = connect(grant) if connect else grant_runner(grant, first=account)
    try:
        target = declared_target(grant, shell, as_deployed=True)
        if isinstance(target, str):
            say(f'credential: {target}')
            return 2
        role = in_checkout(target, ['-m', 'dev_lab.dev.forge', 'auth', 'role', '--url', repo])
        named = named_login(division, user, login)
        before = _unnamed(shell, role) if named else ''  # who a serve posts as, before this line exists
        stamp = stamp or stamp_now()
        refusal, backup = place_verified(
            shell, login=login, token=token, repo=repo, role=role, stamp=stamp, named=named
        )
    except (RuntimeError, OSError, ValueError) as failed:
        say(f'credential: refused -- {user}: {failed}')
        return 2
    if refusal:
        say(f'credential: refused -- {refusal}')
        return 2
    shell(_STORE_HELPER, None)  # a store line git never consults reads as anonymous (measured 2026-11-20)
    asked = _Asked(user, login, repo, role)
    if why := _stored_refusal(shell, asked, token if named else '') or (
        _shadow_refusal(shell, asked, before, stamp, backup) if named else ''
    ):
        say(f'credential: {why}')
        return 2
    held = f'~/{READER_STORE}' if named else 'the stored line'
    say(f'verified: {user}: {held} answers {repo} as {login}; placed {digest(token)} (0600) {backup}')
    return 0


@dataclass(frozen=True)
class _Asked:
    """One placement's read-back: the account *user*, the placed *login*, the *repo* and its ``auth role`` line."""

    user: str
    login: str
    repo: str
    role: str


def _stored_refusal(shell: Runner, asked: _Asked, named_token: str) -> str:
    """Why the STORED line does not answer as the placed login; ``''`` when it does.

    With *named_token* (a login reached only by a url naming it) the read is a fill naming it from the reader file,
    which must return that token (the forge's ``auth role`` asks for the host alone) -- and the shared store must
    hold no line for it: one left there is moved first by the reader's next pull.
    """
    host = urlsplit(asked.repo).hostname or ''
    try:
        if named_token and shell(held_command(host, asked.login), None).strip():
            stored = f'{asked.login} from ~/{STORE}, where a named reader must hold no line,'
        elif named_token:
            stored = asked.login if shell(named_fill_command(host, asked.login), None).strip() == named_token else ''
            stored = stored or 'another token'
        else:
            stored = _unnamed(shell, asked.role)
    except (RuntimeError, OSError, ValueError) as failed:
        stored = f'an error ({failed})'
    if stored == asked.login:
        return ''
    said = stored or 'anonymous'
    return f'not verified -- {asked.user}: the stored line answers {asked.repo} as {said}, not {asked.login}'


def _shadow_refusal(shell: Runner, asked: _Asked, before: str, stamp: str, backup: str) -> str:
    """Why a NAMED placement is undone: the host's unnamed request no longer answers as *before*; ``''`` when it does.

    *before* is who answered it ahead of the placement -- the writer a serve posts as (a role names none). ``''``
    (nothing stored) or the placed login itself shadowed nobody. A changed answer restores the store from the
    placement's backup when the placement wrote it (it removed a line the store held for the reader), so the
    refusal leaves the store as it was found.
    """
    if before in {'', asked.login}:
        return ''
    try:
        after = _unnamed(shell, asked.role)
    except (RuntimeError, OSError, ValueError) as failed:
        after = f'an error ({failed})'
    if after == before:
        return ''
    try:
        if f'/{STORE}.bak-{stamp}' in backup:
            shell(restore_command(stamp), None)
        undone = f'~/{STORE} is as it was before this placement ({backup})'
    except (RuntimeError, OSError) as failed:
        undone = f'~/{STORE} NOT restored ({failed}): remove the line with --login {asked.login} --drop-host <host>'
    return (
        f'refused -- {asked.user}: an unnamed request for {asked.repo} answered as {before} before {asked.login} '
        f'was placed and as {after or "anonymous"} after it, so a serve would post as the wrong login; {undone}'
    )


def _unnamed(shell: Runner, role: str) -> str:
    """The login the forge's ``auth role`` answers as through git's own helper: the host's UNNAMED request."""
    return str(json.loads(shell(role, None) or '{}').get('login') or '')


def drop_host(
    account: str,
    *,
    host: str,
    login: str,
    grants: Sequence[Grant],
    say: Callable[[str], None],
    connect: Callable[[Grant], Runner] = grant_runner,
    stamp: str = '',
) -> int:
    """Remove exactly *login*'s *host* line of *account*'s store and reader file, each after a backup; 2 on refusal."""
    user = account.partition('@')[0]
    grant = next((g for g in grants if g.user == user), None)
    why = _grant_refusal(grant, account) or ('' if valid_host(host) else f'not a host name: {host!r}')
    if why or grant is None:
        say(f'credential: refused -- {why}')
        return 2
    stamp = stamp or stamp_now()
    try:
        shell = connect(grant)
        backup = shell(rewrite_command(host, stamp, login=login, staged=False), None).strip()
        backup = f'{backup} {shell(drop_held_command(host, stamp, login=login, store=READER_STORE), None)}'.strip()
    except (RuntimeError, OSError, ValueError) as failed:
        say(f'credential: refused -- {user}: {failed}')
        return 2
    say(f'{user}: dropped the {login}@{host} line of ~/{STORE} and ~/{READER_STORE} {backup}'.strip())
    return 0


def parser() -> argparse.ArgumentParser:
    """The ``credential`` command line: the one source of its usage (:func:`usage`)."""
    made = argparse.ArgumentParser(prog='dev_lab.dev.hpcaccount credential', description=__doc__.splitlines()[0])
    made.add_argument('account', metavar='<user>@<login host>', help='a declared [[hpc.grant]] account')
    made.add_argument(
        '--login', required=True, metavar='<forge login>', help='the declared forge login the token on stdin belongs to'
    )
    made.add_argument(
        '--drop-host', metavar='<host>', help="instead: remove exactly --login's line for this host (after a backup)"
    )
    made.add_argument(
        '--host-config', type=Path, metavar='<host config>', help="the forge host's reviewed config (with --login)"
    )
    made.add_argument(
        '--from-output',
        default='',
        metavar='<name>',
        help='read the token from the consent output outputs/<name>, deleted only after a verified placement',
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
    if not args.drop_host and args.host_config is None:
        made.error('--login needs --host-config')
    try:
        forge = None if args.drop_host else read_forge(args.host_config)
        machine = reached_machine([args.account.split('@', 1)[0]])
    except (CredentialRefused, PermissionError, LookupError, ValueError) as refused:
        emit(f'credential: refused -- {refused}')
        return 2
    source = Path(args.from_output).name if args.from_output else ''
    if args.from_output and (source != args.from_output or source in {'', '.', '..'}):
        emit(f'credential: refused -- --from-output takes a bare output name, not {args.from_output!r}', err=True)
        return 2
    if forge is None:
        return drop_host(args.account, host=args.drop_host, login=args.login, grants=machine.grants, say=emit)
    if why := unreachable(args.account, machine.grants):
        emit(f'credential: refused -- {why}; nothing was read from stdin, so the token stays with you', err=True)
        return 2
    output = stdout_path(source) if source else None
    try:
        token = output.read_text(encoding='utf-8').strip() if output else sys.stdin.read().strip()
    except OSError as failed:
        emit(f'credential: refused -- {failed}', err=True)
        return 2
    code = place_credential(
        args.account, login=args.login, token=token, url=args.url, forge=forge, grants=machine.grants,
        division=division_of(machine),
        say=emit,
    )  # fmt: skip
    if output and code == 0:
        output.unlink()
        emit(f'credential: removed the placed consent output {source}')
    return code
