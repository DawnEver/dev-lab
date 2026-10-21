"""THE FORGE RELOCKS INTEGRATION: a stale ``uv.lock`` on ``origin/<integration>`` becomes ONE pull request.

FRESHNESS IS ONE PARTY'S JOB (2026-10-21). The ``lock`` pre-push row used to judge every push on freshness, so
whenever any dependency published, every lane carried a hand-made relock commit before each push and stacked
branches repeated it. Now a lane is judged on its PIN alone (:mod:`lab_commons.dev.lockcheck`), and each
``forge serve`` tick runs :func:`carry` (:func:`lab_commons.dev.forgeservesteps.relock`):

* an open pull request whose head is under :data:`PREFIX` is waited for -- nothing resolves, nothing is pushed;
* else :func:`decision` reads ``origin/<integration>`` through :func:`lab_commons.dev.lockcheck.stale` -- the SAME
  reading the pre-push row makes, never a copy -- in a detached worktree under the repository's git directory;
* a stale lock is rewritten by the dependency door (``lab_commons.dev.dep --lock-upgrade``, the one writer of a
  lock), committed alone on top of integration, pushed as ``pr/relock-<dist>-<integration short sha>`` and
  opened as a pull request into integration, which merges like every other once its parts pass;
* a lane takes the new lock with ``forge sync``.

A step that cannot finish RAISES :class:`RelockFailed` naming why (no integration branch, the resolution could
not run, the door failed or moved nothing, the push failed); the serve step alarms it and the next tick tries
afresh.
"""

from __future__ import annotations

import contextlib
import sys
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.dev.forge import _GIT, _GIT_TIMEOUT_S
from lab_commons.dev.lockcheck import LOCK, mount_submodules, stale
from lab_commons.dev.netverb import run_network_verb

if TYPE_CHECKING:
    from lab_commons.dev.forgework import PullRequest
    from lab_commons.dev.lanepolicy import Policy
    from lab_commons.dev.netverb import Report

__all__ = ['PREFIX', 'Relock', 'RelockFailed', 'branch_for', 'carry', 'decision', 'dist_of', 'door_upgrade']

#: The prefix every relock branch carries, inside the declared ephemeral ``pr/*`` namespace.
PREFIX: Final = 'pr/relock'

#: How much of a sha names a branch -- enough to be unique on one host, short enough to read.
SHORT: Final = 12

#: How long the dependency door may take: a cold cache resolving every source, then a frozen sync.
DOOR_TIMEOUT_S: Final = 1800.0

#: The verbs a resolution's change line opens with, and where the distribution sits after one.
_VERBS: Final = frozenset({'Update', 'Add', 'Remove'})
_NAME_INDEX: Final = 2


class RelockFailed(OSError):
    """A relock that could not be carried, with the reason; the next tick tries afresh."""


@dataclass(frozen=True)
class Relock:
    """One relock: the dist that moved, the branch to push, and what the pull request says."""

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
    """``pr/relock-<dist>-<short sha>``: named by the integration commit it relocks."""
    return f'{PREFIX}-{dist}-{sha[:SHORT]}'


def decision(tree: Path, sha: str, *, resolve: Callable[[Path], Report] | None = None) -> Relock | None:
    """The relock *tree* (a checkout of integration at *sha*) needs, or ``None`` when its lock is the newest.

    *resolve* is the resolution :func:`stale` reads; left out it dry-runs ``uv lock --upgrade``, exactly as the
    pre-push row does. A resolution that could not run RAISES rather than relocks.
    """
    found = stale(tree) if resolve is None else stale(tree, resolve=resolve)
    if not found:
        return None
    if not all(line.startswith(f'{LOCK} is not the newest resolution') for line in found):
        raise RelockFailed('; '.join(found))
    dist = dist_of(found[0])
    branch = branch_for(dist, sha)
    changes = '\n'.join(f'- {line}' for line in found)
    title = f'build(deps): relock {dist} to the newest resolution'
    body = (
        f'Integration at `{sha[:SHORT]}` is not at the newest resolution:\n\n{changes}\n\n'
        f'Relocked by the forge through the dependency door (`lab_commons.dev.dep --lock-upgrade`) on '
        f'`{branch}` (`lab_commons.dev.relock`). A lane takes it with `python -m lab_commons.dev.forge sync`.'
    )
    return Relock(dist, branch, title, body)


def _git(root: Path, *argv: str) -> tuple[int, str]:
    done = _door.run(
        [_GIT, '-C', str(root), *argv], capture_output=True, text=True, encoding='utf-8', errors='replace',
        check=False, timeout=_GIT_TIMEOUT_S,
    )  # fmt: skip
    return done.returncode, (done.stdout + done.stderr).strip()


def _must(root: Path, *argv: str) -> str:
    code, out = _git(root, *argv)
    if code != 0:
        msg = f'git {" ".join(argv[:2])} failed in {root}: {out}'
        raise RelockFailed(msg)
    return out


@contextlib.contextmanager
def _worktree(root: Path, sha: str) -> Iterator[Path]:
    """A detached worktree of *root* at *sha* under its git directory, with its submodules; removed after."""
    common = Path(_must(root, 'rev-parse', '--path-format=absolute', '--git-common-dir'))
    tree = common / 'relock' / sha[:SHORT]
    _git(root, 'worktree', 'remove', '--force', str(tree))
    _must(root, 'worktree', 'add', '--detach', str(tree), sha)
    try:
        mount_submodules(root, tree)
        yield tree
    finally:
        _git(root, 'worktree', 'remove', '--force', str(tree))


def door_upgrade(tree: Path) -> int:
    """The one writer of a lock: ``lab_commons.dev.dep --lock-upgrade <tree>``."""
    argv = [sys.executable, '-m', 'lab_commons.dev.dep', '--lock-upgrade', str(tree)]
    return _door.run(argv, check=False, timeout=DOOR_TIMEOUT_S, cwd=tree).returncode


def _push(tree: Path, branch: str) -> None:
    report = run_network_verb([_GIT, 'push', 'origin', f'HEAD:refs/heads/{branch}'], cwd=tree, timeout=300)
    if not report.ok:
        msg = f'the push of {branch} failed: {report.remedy}'
        raise RelockFailed(msg)


def carry(
    root: Path,
    policy: Policy,
    *,
    pulls: Callable[[], Sequence[PullRequest]],
    create: Callable[..., PullRequest],
    resolve: Callable[[Path], Report] | None = None,
    upgrade: Callable[[Path], int] = door_upgrade,
    push: Callable[[Path, str], None] = _push,
) -> str:
    """Relock ``origin/<integration>`` of *root* through one pull request, if it needs one; the line said.

    *pulls* lists the open pull requests and *create* opens one (``Client.pr_create``'s signature); *resolve*,
    *upgrade* and *push* are the resolution, the door and the push, each a seam a test plants.
    """
    for pull in pulls():
        if pull.head.startswith(f'{PREFIX}-'):
            return f'a relock is already open: #{pull.number} {pull.head}'
    base = f'origin/{policy.integration}'
    code, sha = _git(root, 'rev-parse', '--verify', '--quiet', f'refs/remotes/{base}^{{commit}}')
    if code != 0:
        msg = f'there is no {base} in {root} to relock'
        raise RelockFailed(msg)
    with _worktree(root, sha) as tree:
        found = decision(tree, sha, resolve=resolve)
        if found is None:
            return f'the lock of {policy.integration} at {sha[:SHORT]} is the newest resolution'
        if (exited := upgrade(tree)) != 0:
            msg = f'the dependency door exited {exited} relocking {found.dist} at {sha[:SHORT]}'
            raise RelockFailed(msg)
        if not _must(tree, 'status', '--porcelain', '--', LOCK):
            msg = f'the dependency door left {LOCK} unchanged though the resolution moves {found.dist}'
            raise RelockFailed(msg)
        _must(tree, 'commit', '-q', '-m', found.title, '-m', found.body, '--', LOCK)
        push(tree, found.branch)
    opened = create(found.title, found.body, head=found.branch, base=policy.integration)
    return f'relocked {found.dist} onto {found.branch}: {opened.url}'
