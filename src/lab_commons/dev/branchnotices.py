"""FORGE NOTICES WHERE A SESSION ACTS ON ITS PR: the open notices of a ``pr/*`` branch's PR, for this session.

User ruling 2026-10-21. A notice matters at the moments a session ACTS on its PR, and those moments are git and
forge verbs every agent vendor shares, so this one reader serves each of them:

* ``post-commit`` (``pr-notices`` row, the current branch) -- an agent commits often, even long before it pushes;
* ``pre-push`` (``pr-notices`` row, the pushed ``pr/*`` refs);
* ``forge pr create`` (:mod:`lab_commons.dev.forgecli`, the head branch);
* a session's start, by the vendor's own launcher or hook (``forge notices --session``).

It reads the notices :mod:`lab_commons.dev.forgenotice` keeps in the PR's integration comment, keeps those
addressed to the session (``LAB_SESSION``, :mod:`lab_commons.dev.labsession`) and not acked, and prints them.
There is no per-turn poll anywhere: a session gone idle is the integrator's (``forgenotice.escalated``).

READ-ONLY AND NEVER IN THE VERB'S WAY. The answer is cached on disk for :data:`CACHE` per (session, repo, branch),
so a run of commits costs one forge read; a miss is bounded by :data:`DEADLINE_S` wall-clock. No session, no PR,
a forge failure or the deadline all read as silence, and :func:`main` exits 0 whatever it found.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.dev.branchset_push import pushed_refs
from lab_commons.dev.forge import _GIT, _GIT_TIMEOUT_S
from lab_commons.dev.forgenotice import integration_comment, read
from lab_commons.dev.labsession import ENV
from lab_commons.log import emit

if TYPE_CHECKING:
    from lab_commons.dev.forgework import Client

__all__ = ['CACHE_S', 'DEADLINE_S', 'PREFIX', 'lines_for', 'main', 'pushed', 'report']

#: The wall-clock bound on one forge read; past it the verb goes on in silence.
DEADLINE_S: Final = 8.0
#: How long one forge answer serves a (session, repo, branch).
CACHE_S: Final = 60.0
#: The branches whose PR carries notices.
PREFIX: Final = 'pr/'
_HEADER: Final = '[pr-notices] the forge has open notices for this PR:'


def _cache_dir() -> Path:
    return Path(tempfile.gettempdir()) / 'lab-commons-notices'


def _from_forge(client: Client, branch: str, session: str) -> list[str]:
    from lab_commons.dev.forgepulls import pr_list  # noqa: PLC0415 (a network leaf, read only on a cache miss)

    out: list[str] = []
    for pull in pr_list(client):
        if pull.head == branch and (comment := integration_comment(client, pull.number)) is not None:
            out += [n.line() for n in read(comment.body).notices if session in n.sessions and not n.acked]
    return out


def lines_for(
    root: Path,
    branch: str,
    session: str,
    *,
    client: Client | None = None,
    deadline: float = DEADLINE_S,
    clock: Callable[[], float] = time.time,
    cache_dir: Path | None = None,
) -> list[str]:
    """The open notices of *branch*'s PR addressed to *session*; ``[]`` when none, unknown or unreadable."""
    if not session or not branch.startswith(PREFIX):
        return []
    key = hashlib.sha256(f'{session}\0{root.resolve()}\0{branch}'.encode()).hexdigest()[:16]
    file = (cache_dir or _cache_dir()) / f'{key}.json'
    try:
        cached = json.loads(file.read_text(encoding='utf-8'))
        if clock() - float(cached['at']) < CACHE_S:
            return list(cached['lines'])
    except (OSError, ValueError, KeyError, TypeError):
        pass  # no cache yet, or an unreadable one: ask the forge
    found: list[list[str]] = []

    def read_forge() -> None:
        try:
            from lab_commons.dev.forgework import client_for  # noqa: PLC0415

            found.append(_from_forge(client if client is not None else client_for(root), branch, session))
        except Exception:  # noqa: BLE001, S110 -- a notice must never fail a git verb
            pass

    worker = threading.Thread(target=read_forge, daemon=True)
    worker.start()
    worker.join(deadline)
    if worker.is_alive() or not found:
        return []  # unreadable: not cached, so the next verb asks again
    try:
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps({'at': clock(), 'lines': found[0]}), encoding='utf-8')
    except OSError:
        pass  # the cache is optional
    return found[0]


def pushed(lines: Iterable[str]) -> list[str]:
    """The ``pr/*`` branches a push updates (git's pre-push refspec lines); a deletion has no PR to act on."""
    return [r.branch for r in pushed_refs(lines) if not r.deleted and r.branch and r.branch.startswith(PREFIX)]


def report(
    root: Path,
    branches: Sequence[str],
    session: str,
    *,
    client: Client | None = None,
    deadline: float = DEADLINE_S,
    clock: Callable[[], float] = time.time,
    cache_dir: Path | None = None,
) -> str:
    """What the verb prints for *branches*: their open notices for *session*; ``''`` when there are none."""
    found = [
        line
        for branch in branches
        for line in lines_for(root, branch, session, client=client, deadline=deadline, clock=clock, cache_dir=cache_dir)
    ]
    return '\n'.join([_HEADER, *(f'  {line}' for line in found)]) if found else ''


def _current(root: Path) -> str:
    done = _door.run(
        [_GIT, 'symbolic-ref', '--quiet', '--short', 'HEAD'],
        cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=_GIT_TIMEOUT_S, check=False,
    )  # fmt: skip
    return done.stdout.strip() if done.returncode == 0 else ''


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m lab_commons.dev.branchnotices [--push] [ROOT]``: print, never fail -- always exits 0.

    ``--push`` reads git's pre-push refspec lines on stdin; without it, the current branch (post-commit).
    """
    try:
        parser = argparse.ArgumentParser(prog='lab_commons.dev.branchnotices', description=__doc__.splitlines()[0])
        parser.add_argument('--push', action='store_true', help="the pushed pr/* refs, git's pre-push stdin")
        parser.add_argument('root', nargs='?', default='')
        args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
        root = Path(args.root) if args.root else Path.cwd()
        if args.push:
            stdin = '' if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read()
            branches = pushed(stdin.splitlines())
        else:
            branches = [_current(root)]
        if text := report(root, branches, os.environ.get(ENV, '')):
            emit(text, err=True)
    except (Exception, SystemExit):  # noqa: BLE001, S110 -- a notice must never fail a git verb
        pass
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
