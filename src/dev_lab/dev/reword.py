"""``python -m dev_lab.dev.reword <sha> --message-file F``: a new message for an UNPUSHED commit of this lane.

PRIVATE-MARKERS refuses a push whose commit message names a private value, and GIT-COMMIT-AMEND refuses the amend
that would reword it. This is the door between them: the commits from *sha* to ``HEAD`` are re-committed with
``git commit-tree`` -- the same trees and authors, *sha*'s message replaced -- onto a FRESH branch
``<branch>-reworded``. Nothing is rewritten in place: the current branch and every other ref stay as they are, so
another agent's commit is never touched, and the fresh branch is what the session pushes (a new PR head).

Refused, by name: a *sha* any remote-tracking ref already holds (public; rewording it publishes nothing new), a
*sha* that is not an ancestor of ``HEAD``, a detached ``HEAD``, the declared integration or trunk branch, and a fresh
branch name that already exists.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from lab_commons.log import emit

__all__ = ['SUFFIX', 'Refused', 'reword']

#: Appended to the current branch's name for the fresh branch.
SUFFIX: Final = '-reworded'

#: Branches no session rewrites on (their commits arrive by merge).
_SHARED: Final = frozenset({'main', 'integrate/main'})


class Refused(ValueError):
    """The reword was refused; the message names why and what to do instead."""


def _git(root: Path, *argv: str, env: dict[str, str] | None = None, check: bool = True) -> str:
    done = _door.run(['git', *argv], cwd=root, capture_output=True, check=check, env=env)
    return done.stdout.decode('utf-8', errors='replace').strip()


def _ok(root: Path, *argv: str) -> bool:
    return _door.run(['git', *argv], cwd=root, capture_output=True, check=False).returncode == 0


def reword(root: Path, sha: str, message: str) -> tuple[str, str]:
    """``(fresh branch, its head)``: *sha*..HEAD re-committed with *sha*'s message replaced by *message*."""
    branch = _git(root, 'symbolic-ref', '--quiet', '--short', 'HEAD', check=False)
    if not branch:
        msg = 'HEAD is detached: reword works on a branch of this session'
        raise Refused(msg)
    if branch in _SHARED:
        msg = f'{branch} is shared (commits arrive by merge): reword only a lane of this session'
        raise Refused(msg)
    target = _git(root, 'rev-parse', '--verify', f'{sha}^{{commit}}')
    if not _ok(root, 'merge-base', '--is-ancestor', target, 'HEAD'):
        msg = f'{sha} is not an ancestor of {branch}'
        raise Refused(msg)
    if _git(root, 'branch', '--remotes', '--contains', target):
        msg = f'{sha} is already on a remote: rewording it publishes nothing new'
        raise Refused(msg)
    fresh = f'{branch}{SUFFIX}'
    if _ok(root, 'rev-parse', '--verify', '--quiet', f'refs/heads/{fresh}'):
        msg = f'{fresh} already exists: push or delete it first'
        raise Refused(msg)
    chain = [target, *_git(root, 'rev-list', '--reverse', '--topo-order', '--ancestry-path', f'{target}..HEAD').split()]
    made: dict[str, str] = {}
    for old in chain:
        parents = [made.get(p, p) for p in _git(root, 'rev-list', '--parents', '-n', '1', old).split()[1:]]
        text = message if old == target else _git(root, 'log', '-1', '--format=%B', old)
        made[old] = _commit(root, old, parents, text)
    head = made[_git(root, 'rev-parse', 'HEAD')]
    _git(root, 'branch', fresh, head)
    return fresh, head


def _commit(root: Path, old: str, parents: list[str], message: str) -> str:
    """A commit with *old*'s tree, author and dates, *parents* and *message*."""
    who = _git(root, 'log', '-1', '--format=%an%x00%ae%x00%aI%x00%cn%x00%ce%x00%cI', old).split('\0')
    env = os.environ | dict(
        zip(
            ('GIT_AUTHOR_NAME', 'GIT_AUTHOR_EMAIL', 'GIT_AUTHOR_DATE',
             'GIT_COMMITTER_NAME', 'GIT_COMMITTER_EMAIL', 'GIT_COMMITTER_DATE'),
            who, strict=True,
        )
    )  # fmt: skip
    argv = ['git', 'commit-tree', f'{old}^{{tree}}', *(arg for p in parents for arg in ('-p', p))]
    done = _door.run(argv, cwd=root, capture_output=True, check=True, env=env, input=message.encode('utf-8'))
    return done.stdout.decode('utf-8').strip()


def main(argv: list[str] | None = None) -> int:
    """The CLI: 0 with the fresh branch printed, 2 refused by name."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.reword', description=__doc__)
    parser.add_argument('sha')
    parser.add_argument('--message-file', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        fresh, head = reword(args.root, args.sha, args.message_file.read_text(encoding='utf-8'))
    except Refused as refused:
        emit(f'reword: refused: {refused}', err=True)
        return 2
    emit(f'reword: {fresh} at {head[:12]} -- push it (a new PR head) and close the old PR as superseded')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
