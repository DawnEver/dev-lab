"""ONE-SESSION-ONE-PR's identity: the launcher's ``LAB_SESSION``, stamped as a ``Lab-Session`` trailer at commit-msg.

The id is ISSUED BY THE LAUNCHER, once per session and vendor-neutral (cc-config's ``ccc``/``ccds``/``codc``
launchers, ``scripts/shared/machine.mjs``), and inherited by every child process -- a subagent, a fabric
takeover, a codex run. The agent never writes it: this hook stamps it from the environment, replacing any
trailer already in the message. An AGENT commit -- one of :data:`AGENT_MARKERS` is set, the env contract the
launchers and the provenance stamp (:func:`lab_commons.dev.forgework.provenance`) already share -- without the
id is REFUSED, because a PR whose commits carry no session cannot be judged against the session's other PR. A
human commit without it is untouched. ``Claude-Session:`` is plain prose; nothing reads it.

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
from lab_commons.dev.forge import _GIT, _GIT_TIMEOUT_S
from lab_commons.log import emit

__all__ = ['AGENT_MARKERS', 'ENV', 'TRAILER', 'machine_env', 'main', 'sessions', 'stamp']

#: The environment variable the launcher issues the session id in.
ENV: Final = 'LAB_SESSION'
#: The commit trailer this hook writes.
TRAILER: Final = 'Lab-Session'
#: Set in an agent's process tree: the launchers' provenance contract, and Claude Code's own marker for a
#: session no launcher started (the VS Code extension).
AGENT_MARKERS: Final = ('HARNESS_AGENT', 'CLAUDECODE')

_ID: Final = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$')


def machine_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """*env* (default: this process's) without the session and the agent markers: a forge commit is no session's."""
    dropped = {ENV, *AGENT_MARKERS}
    return {key: value for key, value in (os.environ if env is None else env).items() if key not in dropped}


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
    """The commit-msg hook: stamp the launcher's session; refuse an agent commit that has none."""
    args = list(sys.argv[1:] if argv is None else argv)
    env = os.environ if env is None else env
    session = env.get(ENV, '')
    agent = next((marker for marker in AGENT_MARKERS if env.get(marker)), '')
    if session and not _ID.match(session):
        emit(f'[lab-session] REFUSED -- {ENV}={session!r} is not a session id (8-128 of [A-Za-z0-9._-]).', err=True)
        return 1
    if not session:
        if not agent:
            return 0
        emit(
            f'[lab-session] REFUSED -- an agent commit ({agent} is set) without {ENV}: its PR cannot be judged '
            f'against its session.\n[lab-session]   REMEDY: start the session from a launcher that issues '
            f'{ENV} (ccc, ccds, codc -- cc-config scripts/shared/machine.mjs); never write the trailer by hand.',
            err=True,
        )
        return 1
    try:
        stamp(args[-1], session)
    except (IndexError, OSError, subprocess.SubprocessError) as failed:
        emit(f'[lab-session] REFUSED -- the session could not be stamped: {failed}', err=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
