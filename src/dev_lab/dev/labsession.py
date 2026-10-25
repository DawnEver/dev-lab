"""ONE-SESSION-ONE-PR's identity: the launcher's ``LAB_SESSION``, stamped as a ``Lab-Session`` trailer at commit-msg.

The id is ISSUED BY THE LAUNCHER, once per session and vendor-neutral (cc-config's ``ccc``/``ccds``/``codc``
launchers, ``scripts/shared/machine.mjs``), and inherited by every child process -- a subagent, a fabric
takeover, a codex run. The agent never writes it: this hook stamps it from the environment, replacing any
trailer already in the message. A commit WITHOUT the id -- a human's, or an agent's on a path no launcher
started (the VS Code extension, the codex desktop app, ``codc`` attached to a shared app-server) -- is NEVER
refused (user ruling 2026-10-21): it carries no trailer and ONE-SESSION-ONE-PR does not judge it. Only a
session that has an id is judged. ``Claude-Session:`` is plain prose; nothing reads it.

A commit the FORGE makes (a relock, a machine merge) is the forge's, never a session's: it runs git under
:func:`machine_env`, so it carries no session even on a host started from inside one.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.forge import _GIT, _GIT_TIMEOUT_S, UnreadableRemote, forge_from_remote

__all__ = ['ENV', 'FORGE_NAME', 'TRAILER', 'forge_email', 'machine_env', 'main', 'sessions', 'stamp']

#: The environment variable the launcher issues the session id in.
ENV: Final = 'LAB_SESSION'
#: The commit trailer this hook writes.
TRAILER: Final = 'Lab-Session'
#: The author and committer name of every commit the forge makes.
FORGE_NAME: Final = 'Forge'

_ID: Final = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$')


def forge_email(root: Path | None) -> str:
    """``forge@<host of root's origin>``: the forge signs its own commits; ``forge@invalid`` when none is readable."""
    try:
        host = forge_from_remote(root).host if root is not None else ''
    except UnreadableRemote:
        host = ''
    return f'forge@{host.partition(":")[0] or "invalid"}'


def machine_env(root: Path | None = None, *, env: Mapping[str, str] | None = None) -> dict[str, str]:
    """*env* (default: this process's) as the FORGE: no session, and the forge's identity, never the account's.

    The ONE source of a forge-made commit's author and committer (user ruling 2026-10-25): on an HPC login
    node git would otherwise sign with the account's passwd GECOS name. The machine and account stay
    visible as data in the ``Forge-Host`` trailer (``<cluster>/<account>``), never as the author.
    """
    out = {key: value for key, value in (os.environ if env is None else env).items() if key != ENV}
    email = forge_email(root)
    for role in ('AUTHOR', 'COMMITTER'):
        out[f'GIT_{role}_NAME'], out[f'GIT_{role}_EMAIL'] = FORGE_NAME, email
    return out


def sessions(root: Path, base: str, head: str) -> frozenset[str]:
    """Every ``Lab-Session`` the commits in ``base..head`` carry; empty when git cannot read the range."""
    done = _door.run(
        [_GIT, '-C', str(root), 'log', f'--format=%(trailers:key={TRAILER},valueonly)', f'{base}..{head}'],
        capture_output=True, text=True, encoding='utf-8', timeout=_GIT_TIMEOUT_S, check=False,
    )  # fmt: skip
    return frozenset(done.stdout.split()) if done.returncode == 0 else frozenset()


def stamp(message_file: str, session: str) -> None:
    """Append ``Lab-Session: <session>`` to *message_file*, replacing a trailer already there."""
    _door.run(
        [_GIT, 'interpret-trailers', '--in-place', '--if-exists', 'replace', '--trailer', f'{TRAILER}: {session}',
         message_file],
        check=True, timeout=_GIT_TIMEOUT_S,
    )  # fmt: skip


def main(argv: Sequence[str] | None = None, *, env: Mapping[str, str] | None = None) -> int:
    """The commit-msg hook: stamp the launcher's session; a commit without one passes unstamped."""
    args = list(sys.argv[1:] if argv is None else argv)
    session = (os.environ if env is None else env).get(ENV, '')
    if not session:
        return 0
    if not _ID.match(session):
        emit(f'[lab-session] REFUSED -- {ENV}={session!r} is not a session id (8-128 of [A-Za-z0-9._-]).', err=True)
        return 1
    try:
        stamp(args[-1], session)
    except (IndexError, OSError, subprocess.SubprocessError) as failed:
        emit(f'[lab-session] REFUSED -- the session could not be stamped: {failed}', err=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
