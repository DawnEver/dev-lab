"""WORKTREE LEASES: a worktree is a lease on a branch for one task, reclaimed once that task is over.

Worktrees created for a task (by an agent, a human, codex) were never reclaimed: :mod:`dev_lab.dev.checkout`
DETECTED them and ``branchset --apply`` deleted merged local branches but skipped every branch checked out in a
worktree, so a finished tree pinned its branch forever. First principles: a lease ends when its branch's CONTENT
is landed (or its PR closed and its origin ref deleted after a squash merge) AND no TRACKED file is changed:
what git does not track is not the work and goes with the tree, its run outputs moved home first (user ruling
2026-10-25). :func:`reclaimable` is that one decision, built on :mod:`dev_lab.dev.checkout`'s readings (content
by ``git cherry``, never ancestry; ``None`` when git cannot answer); :func:`reclaim` acts on it. The doors are
``python -m dev_lab.dev.worktrees --prune`` (which the session debris hook runs) and ``python -m
dev_lab.dev.branchset --apply``, which reclaims first so the freed branch is deleted in the same run.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from lab_commons.census import processes

from dev_lab.dev.checkout import (
    _GIT,
    _GIT_TIMEOUT_S,
    DEFAULT_WORKTREE_HOME,
    git_bytes,
    git_out,
    orphan_directories,
    unmerged_changes,
    worktrees,
)
from dev_lab.dev.liverun import occupants
from dev_lab.dev.worktree_archive import home_outputs

__all__ = ['Lease', 'blockers', 'reclaim', 'reclaimable']

#: How many paths a kept line names before it counts the rest.
_SHOWN: Final = 5


def blockers(tree: Path) -> tuple[str, ...] | None:
    """Every TRACKED path changed in *tree*, staged or not. Untracked and ignored files are not the work.

    User ruling 2026-10-25: the work is committed; what git does not track (scratch, untracked, ignored:
    ``.venv``, caches, builds) goes with the tree, except run outputs, which :func:`reclaim` moves home first.
    """
    out = git_out(tree, 'status', '--porcelain', '--untracked-files=no')
    if out is None:
        return None
    return tuple(f'{line[:2].strip()} {line[3:].strip()}' for line in out.splitlines() if line.strip())


def _shown(paths: tuple[str, ...] | list[str]) -> str:
    more = f' (+{len(paths) - _SHOWN} more)' if len(paths) > _SHOWN else ''
    return ', '.join(paths[:_SHOWN]) + more


@dataclass(frozen=True)
class Lease:
    """One linked worktree (or orphan directory under the worktree home) and why it may not be reclaimed.

    A worktree is a LEASE on a branch for one task: its life ends when the branch's CONTENT is landed on a
    holder and the tree holds nothing that exists nowhere else, and *reason* is empty exactly then. *branch*
    is ``''`` for an orphan directory, which leases nothing.
    """

    path: Path
    branch: str
    reason: str

    @property
    def reclaimable(self) -> bool:
        """Every criterion of :func:`reclaimable` holds."""
        return not self.reason


def _locked(root: Path) -> frozenset[Path] | None:
    out = git_out(root, 'worktree', 'list', '--porcelain')
    if out is None:
        return None
    found: set[Path] = set()
    path: Path | None = None
    for line in out.splitlines():
        if line.startswith('worktree '):
            path = Path(line.removeprefix('worktree ').strip()).resolve()
        elif (line == 'locked' or line.startswith('locked ')) and path is not None:
            found.add(path)
    return frozenset(found)


def _patch_ids(root: Path, patch: bytes) -> frozenset[str]:
    try:
        done = _door.run(
            [_GIT, 'patch-id', '--stable'], cwd=root, input=patch, capture_output=True, check=False,
            timeout=_GIT_TIMEOUT_S,
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired):
        return frozenset()
    text = done.stdout.decode('utf-8', 'replace') if done.returncode == 0 else ''
    return frozenset(line.split()[0] for line in text.splitlines() if line.strip())


def _squash_landed(tree: Path, holder: str) -> bool:
    """Whether the branch's WHOLE change since its fork point is one commit's change on *holder* (a squash)."""
    base = (git_out(tree, 'merge-base', holder, 'HEAD') or '').strip()
    if not base:
        return False
    whole = git_bytes(tree, 'diff', base, 'HEAD')
    landed = git_bytes(tree, 'log', '-p', '--no-merges', f'{base}..{holder}')
    if not whole or landed is None:
        return False
    return bool(_patch_ids(tree, whole) & _patch_ids(tree, landed))


def _landed(tree: Path, branch: str, holders: tuple[str, ...]) -> bool:
    """CONTENT on a holder (``git cherry`` empty), or -- its origin ref deleted -- squash-merged into one."""
    if any(unmerged_changes(tree, holder, 'HEAD') == 0 for holder in holders):
        return True
    if branch == 'detached':
        return False
    track = git_out(tree, 'for-each-ref', '--format=%(upstream:track)', f'refs/heads/{branch}')
    return (track or '').strip() == '[gone]' and any(_squash_landed(tree, holder) for holder in holders)


def _occupancy() -> Callable[[Path], bool]:
    """LIVE-RUN's whole-tree lock (:func:`dev_lab.dev.liverun.occupants`) over ONE process snapshot."""
    table = tuple(processes())
    return lambda path: bool(occupants(path, census=lambda: table))


_LIVE: Final = 'live -- a process works in, executes from or reads it'


def _tree_reason(tree: Path, branch: str, holders: tuple[str, ...], *, locked: bool) -> str:
    if locked:
        return 'locked (git worktree unlock first)'
    blocking = blockers(tree) if tree.is_dir() else None
    if blocking is None:
        return 'unreadable'
    if blocking:
        return f'tracked changes -- commit or revert first: {_shown(blocking)}'
    if not _landed(tree, branch, holders):
        return f'not landed -- its content is on none of {", ".join(holders)}'
    return ''


def reclaimable(
    root: Path,
    holders: tuple[str, ...],
    *,
    home: Path = DEFAULT_WORKTREE_HOME,
    occupied: Callable[[Path], bool] | None = None,
) -> tuple[Lease, ...] | None:
    """Every LINKED worktree and orphan directory of *root*, judged; ``None`` when git could not answer.

    A linked worktree (never the main one) is reclaimable iff ALL hold, checked in this order:

    * not ``git worktree lock``-ed;
    * no TRACKED change, staged or not (:func:`blockers`) -- untracked and ignored files never block;
    * LANDED: its HEAD's content is on one of *holders* (``git cherry`` empty -- content, not ancestry), or
      its branch's origin ref is gone and its whole change is one commit's change on a holder (squash merge);
    * UNOCCUPIED: no process works in, executes from or reads it (LIVE-RUN's :func:`occupants` by default).

    An orphan directory under *home* is reclaimable iff nothing occupies it. *holders* are the refs whose content counts
    as landed: the trunk's authority and every declared session (``dev_lab.dev.branchset.holders``).
    """
    trees = worktrees(root)
    locked = _locked(root)
    orphans = orphan_directories(root, home=home)
    if trees is None or locked is None or orphans is None:
        return None
    is_occupied = occupied or _occupancy()
    leases: list[Lease] = []
    for path, branch in trees[1:]:
        tree = path.resolve()
        reason = _tree_reason(tree, branch, holders, locked=tree in locked)
        leases.append(Lease(tree, branch, reason or (_LIVE if is_occupied(tree) else '')))
    leases += [Lease(orphan, '', _LIVE if is_occupied(orphan) else '') for orphan in orphans]
    return tuple(leases)


def reclaim(
    root: Path,
    holders: tuple[str, ...],
    *,
    home: Path = DEFAULT_WORKTREE_HOME,
    occupied: Callable[[Path], bool] | None = None,
    apply: bool = True,
) -> tuple[str, ...] | None:
    """Remove every reclaimable lease; one line per lease, a kept one with its reason. ``None``: unreadable.

    Every lease's run outputs are moved HOME first (:func:`dev_lab.dev.worktree_archive.home_outputs`) and
    the copy verified; only then does a worktree go by ``git worktree remove --force`` (its untracked and
    ignored content is declared disposable) or an orphan by ``shutil.rmtree``. An unverified archive keeps
    the lease, with the reason. A removed tree's branch stays for ``dev_lab.dev.branchset.apply_local``,
    which deletes it pinned to its sha. Without *apply* nothing is touched.
    """
    leases = reclaimable(root, holders, home=home, occupied=occupied)
    if leases is None:
        return None
    out: list[str] = []
    for lease in leases:
        label = f'{lease.path}  [{lease.branch}]' if lease.branch else f'{lease.path}  (unregistered)'
        if not lease.reclaimable:
            out.append(f'kept     {label}  ({lease.reason})')
        elif not apply:
            out.append(f'prunable {label}')
        elif unarchived := home_outputs(root, lease.path):
            out.append(f'kept     {label}  ({unarchived}; nothing was deleted)')
        elif lease.branch:
            done = git_out(root, 'worktree', 'remove', '--force', str(lease.path)) is not None
            out.append(f'{"removed " if done else "FAILED  "} {label}')
        else:
            try:
                shutil.rmtree(lease.path)
            except OSError as error:
                out.append(f'FAILED   {label}  ({error})')
            else:
                out.append(f'removed  {label}')
    if apply:
        git_out(root, 'worktree', 'prune')
    return tuple(out)
