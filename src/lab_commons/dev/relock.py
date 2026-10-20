"""A RELOCK ARRIVES AS A PULL REQUEST: the DECISION half -- which consumers are stale, and on which branch.

W4 of the PR-only plan. When an upstream family repo's ``integrate/main`` moves, a consumer's ``uv.lock``
stops being the newest resolution and the ``lock`` pre-push row refuses every push from that checkout. Today
the steward relocks by hand, which is the same two commands every time and is exactly what a step should do:

* :func:`decision` reads one consumer's staleness through :func:`lab_commons.dev.lockcheck.stale` -- the SAME
  reading the pre-push row makes, never a copy -- and answers ``None`` when the lock is newest, else the
  branch to push and the pull request to open (or to update, when one is already open for that dist).
* The branch is ``pr/relock-<dist>-<newest short sha>``: one open relock PR per (consumer, dist), and a moving
  upstream moves the branch rather than adding a second PR.

WHAT THIS MODULE DOES NOT DO, on purpose: it resolves nothing and pushes nothing. ``uv lock --upgrade`` is the
dependency door's (:mod:`lab_commons.dev.dep`), and a push is the author's; a decision that ran them would be
a second writer of the same fact.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from lab_commons.dev.lockcheck import stale
from lab_commons.log import emit

__all__ = ['Relock', 'branch_for', 'decision', 'dist_of', 'main']

#: The prefix every relock branch carries: a declared ephemeral namespace in every consumer.
PREFIX: Final = 'pr/relock'

#: How much of a sha names a branch -- enough to be unique on one host, short enough to read.
SHORT: Final = 12

#: The verbs a resolution's change line opens with, and where the distribution sits after one.
_VERBS: Final = frozenset({'Update', 'Add', 'Remove'})
_NAME_INDEX: Final = 2


@dataclass(frozen=True)
class Relock:
    """One consumer's relock: the dist that moved, the branch to push, and what the PR says."""

    dist: str
    branch: str
    title: str
    body: str


def dist_of(change: str) -> str:
    """The distribution a :func:`~lab_commons.dev.lockcheck.stale` sentence names.

    The sentence is ``uv.lock is not the newest resolution: Update pint v0.26.1 -> v0.26.2``; the word after
    the verb is the distribution, and a sentence of another shape answers ``'lock'`` rather than guessing.
    """
    _, _, rest = change.partition('resolution: ')
    words = rest.split()
    name = words[1] if len(words) >= _NAME_INDEX and words[0] in _VERBS else ''
    return name or 'lock'


def branch_for(dist: str, sha: str) -> str:
    """``pr/relock-<dist>-<short sha>``: one branch per (consumer, dist), moved rather than multiplied."""
    return f'{PREFIX}-{dist}-{sha[:SHORT]}'


def decision(root: Path, sha: str, *, resolve: Callable[..., object] | None = None) -> Relock | None:
    """The relock *root* needs for upstream *sha*, or ``None`` when its lock is already the newest.

    *resolve* is the resolution :func:`stale` reads; left out it dry-runs the door, exactly as the pre-push
    row does, so a decision can never disagree with the push that follows it.
    """
    found = stale(root) if resolve is None else stale(root, resolve=resolve)  # type: ignore[arg-type]
    if not found:
        return None
    dist = dist_of(found[0])
    changes = '\n'.join(f'- {line}' for line in found)
    branch = branch_for(dist, sha)
    title = f'build(deps): relock {dist} to the newest resolution'
    body = (
        f'{root.name} is behind the family on `{dist}`:\n\n{changes}\n\n'
        f'The lock resolves through the one door (`lab_commons.dev.dep --lock-upgrade`), and this branch is '
        f'`{branch}`: one open relock PR per (consumer, dist), moved when the upstream moves again.'
    )
    return Relock(dist, branch, title, body)


def main(
    argv: Sequence[str] | None = None, *, cwd: Path | None = None, resolve: Callable[..., object] | None = None
) -> int:
    """``relock <upstream sha>``: print the relock this checkout needs, or say it needs none."""
    parser = argparse.ArgumentParser(prog='python -m lab_commons.dev.relock', description=__doc__.splitlines()[0])
    parser.add_argument('sha', help='the upstream commit that moved (its short form names the branch)')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd() if cwd is None else cwd
    try:
        found = decision(root, args.sha, resolve=resolve)
    except OSError as why:
        emit(f'[relock] {why}', err=True)
        return 1
    if found is None:
        emit(f'[relock] {root.name}: the lock is the newest resolution for {args.sha[:SHORT]}')
        return 0
    emit(f'[relock] {root.name}: {found.dist} -> {found.branch}')
    emit(f'[relock]   {found.title}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
