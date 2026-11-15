"""ONE minted forge token placed in a git credential STORE, verified before it replaces: the shared core.

Two doors place a token: :mod:`dev_lab.dev.hpcaccount.credential` on a key-only cluster account (a remote shell)
and :mod:`dev_lab.dev.devhost` ``credential`` on THIS development machine (a local POSIX shell). Both hand
:func:`place_verified` a shell that runs one command line with an optional stdin; everything else is here, once.

The token is never on an argv and never printed: it arrives as a shell's stdin, read by ``read`` and written by
``printf`` (builtins). The line is staged alone in ``~/.git-credentials.new-<ts>`` (umask 077); the forge's own
``auth role``, run with git's credential helper pointed at ONLY that file, must answer as the login. Then the store
is rewritten (:func:`rewrite_command`): a backup ``~/.git-credentials.bak-<ts>`` (0600) first, every other line kept,
the forge's line replaced, mode 0600, atomic ``mv``. A refusal deletes the staged file and leaves the store untouched.

THE FORGE IS THE HOST CONFIG'S (:func:`read_forge`): its sites and accounts come from the forge host's reviewed
config, never a copy; a url on another host is refused before anything is staged.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from urllib.parse import quote, urlsplit

from dev_lab.ops.config import load as load_host_config

__all__ = [
    'STORE',
    'CredentialRefused',
    'DeclaredForge',
    'Shell',
    'digest',
    'discard_command',
    'place_verified',
    'read_forge',
    'rewrite_command',
    'stage_command',
    'stamp_now',
    'valid_host',
    'verify_prefix',
]

#: Runs one shell command line with an optional stdin; returns its stdout, raises on failure.
Shell = Callable[[str, str | None], str]

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


def valid_host(host: str) -> bool:
    """*host* is a bare forge host name (no scheme, user, path or shell metacharacter)."""
    return _HOST.fullmatch(host) is not None


def _checked(host: str, stamp: str) -> None:
    if not valid_host(host):
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


def verify_prefix(host: str, stamp: str) -> str:
    """The exports that make git's credential helper read ONLY the staged file for *host*.

    An empty helper resets a list; both the generic list and *host*'s URL-scoped one (which git prefers, and which
    ``rewrite_command``'s global config holds) are reset, then pointed at the staged file. ``$HOME`` stays literal: the
    helper's own shell expands it, so a native git under MSYS bash gets a path it can open (not an MSYS ``/c/...``).
    """
    _checked(host, stamp)
    staged = f'\'store --file="$HOME/{STORE}.new-{stamp}"\''
    scoped = f'credential.https://{host}.helper'
    return (
        'export GIT_CONFIG_COUNT=4 GIT_CONFIG_KEY_0=credential.helper GIT_CONFIG_VALUE_0= '
        f'GIT_CONFIG_KEY_1=credential.helper GIT_CONFIG_VALUE_1={staged} '
        f'GIT_CONFIG_KEY_2={scoped} GIT_CONFIG_VALUE_2= '
        f'GIT_CONFIG_KEY_3={scoped} GIT_CONFIG_VALUE_3={staged} && '
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


def place_verified(shell: Shell, *, login: str, token: str, repo: str, role: str, stamp: str = '') -> tuple[str, str]:
    """Stage *token* as *login* for *repo*'s host, verify with the *role* command, then replace.

    Returns ``(refusal, '')`` when the forge answered as anyone but *login* (the store untouched), else
    ``('', backup line)``.
    """
    stamp, host = stamp or stamp_now(), urlsplit(repo).hostname or ''
    shell(stage_command(stamp), f'https://{quote(login, safe="")}:{quote(token, safe="")}@{host}\n')
    try:
        answered = str(json.loads(shell(verify_prefix(host, stamp) + role, None)).get('login') or '')
    except (RuntimeError, OSError, ValueError) as failed:
        answered = f'an error ({failed})'
    if answered != login:
        shell(discard_command(stamp), None)
        return f'the forge answers {repo} as {answered or "anonymous"}, not {login}; ~/{STORE} untouched', ''
    return '', shell(rewrite_command(host, stamp, staged=True), None).strip()
