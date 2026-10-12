"""The forge credential: what the git transport already holds for a host, read and stored through git.

Split out of :mod:`lab_commons.dev.forge` (2026-10-12) when naming WHY a credential is absent pushed
that module past the size band; :mod:`lab_commons.dev.forge` re-exports the public names.
"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

__all__ = [
    'AUTH_REFUSED',
    'AUTH_REMEDY',
    'NoCredential',
    'authorization',
    'credential_for',
    'store_credential',
    'token_for',
]

#: Resolved once: a bare name is a PATH lookup at every call site, and a PATH that answers differently
#: between a terminal and a detached launcher describes an environment nobody meant.
_GIT = shutil.which('git') or 'git'

#: Reading a remote URL touches no network; a git that has not answered in half a minute is hung.
_GIT_TIMEOUT_S = 30


class NoCredential(OSError):
    """The git transport holds no credential for this host, so there is nothing to authenticate with."""


#: HTTP statuses that refuse the presented credential: permanent, the remedy is a re-stored credential.
AUTH_REFUSED: Final = frozenset({401, 403})

#: The remedy an auth refusal names.
AUTH_REMEDY: Final = 'the forge refused the stored credential; re-store it: python -m lab_commons.dev.forge auth login'


def credential_for(host: str, *, cwd: Path, env: Mapping[str, str] | None = None) -> tuple[str, str]:
    """``(username, secret)`` the git transport already holds for *host*; never returned to a log.

    The username travels with the secret because git presents BOTH (HTTP Basic): a stored gitea
    PASSWORD authenticates only that way, and a token does too, so presenting them as git does is
    the one form every stored credential passes. An EMPTY password is refused rather than returned:
    a header would carry it, the forge would reject it, and a missing credential would be reported
    as a forge problem.
    """
    done = _credential('fill', {'host': host}, cwd=cwd, env=env)
    fields = dict(line.partition('=')[::2] for line in done.stdout.splitlines())
    if fields.get('password'):
        return fields.get('username', ''), fields['password']
    raise NoCredential(_why_no_credential(host, done))


#: What git prints when a configured helper could not be STARTED. Only git's own phrase: its prompt
#: fallback also says "No such file or directory", and that is an empty store, not a missing helper.
_HELPER_NOT_STARTED: Final = ('is not a git command',)


def _why_no_credential(host: str, done: subprocess.CompletedProcess[str]) -> str:
    """Which of three different failures left *host* without a credential -- each has its own repair.

    Measured 2026-10-12: a given env blanked ``PATH``, so git could not start ``git-credential-manager``
    and the store that HELD the credential was reported as empty. And on Ada a git that could not load
    its own libraries exited 127 under the same message. Neither is a missing credential.
    Reads git's stderr only; the secret travels on stdout and is never part of this text.
    """
    said = ' '.join(done.stderr.split())[:300]
    if done.returncode == _NOT_STARTED:
        return f'git itself could not start (exit {done.returncode}): {said}'
    if any(token in said.lower() for token in _HELPER_NOT_STARTED):
        return f'the credential helper for {host} could not be started (is it on PATH?): {said}'
    return f'no stored credential for {host}: the git transport must be able to authenticate first'


def authorization(username: str, secret: str, scheme: str) -> str:
    """HTTP Basic with the credential's username, exactly as git presents it; ``<scheme> <secret>`` only without one.

    A secret with no username is a bare token handed to ``auth login`` -- the one case Basic cannot carry.
    """
    if username:
        return 'Basic ' + base64.b64encode(f'{username}:{secret}'.encode()).decode()
    return f'{scheme} {secret}'


def token_for(host: str, *, cwd: Path, env: Mapping[str, str] | None = None) -> str:
    """The secret half of :func:`credential_for`."""
    return credential_for(host, cwd=cwd, env=env)[1]


def store_credential(host: str, username: str, secret: str, *, cwd: Path, env: Mapping[str, str] | None = None) -> None:
    """Hand *secret* to the configured git credential helper for ``https://<host>``; nothing touches disk here.

    The SAME store :func:`token_for` reads, so the forge verbs and ``git push`` over https use it alike.
    Where it is persisted is the helper's decision (Git Credential Manager, the OS keychain, ...).
    """
    done = _credential('approve', {'host': host, 'username': username, 'password': secret}, cwd=cwd, env=env)
    if done.returncode != 0:
        msg = f'git credential approve failed for {host} (exit {done.returncode}); is a credential.helper configured?'
        raise NoCredential(msg)


#: A shell's exit code for a command it could not execute.
_NOT_STARTED: Final = 127


def _credential(
    verb: str, fields: Mapping[str, str], *, cwd: Path, env: Mapping[str, str] | None
) -> subprocess.CompletedProcess[str]:
    """One ``git credential <verb>`` over https; the secret travels on stdin, never in argv."""
    payload = ''.join(f'{key}={value}\n' for key, value in {'protocol': 'https', **fields}.items())
    return subprocess.run(
        [_GIT, 'credential', verb],
        input=payload + '\n',
        cwd=cwd,
        env=None if env is None else {**os.environ, **dict(env)},
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=_GIT_TIMEOUT_S,
        check=False,
    )
