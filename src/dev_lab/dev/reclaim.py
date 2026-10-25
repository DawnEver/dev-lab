"""WORKTREE LEASES: a worktree is a lease on a branch for one task, reclaimed once that task is over.

Worktrees created for a task (by an agent, a human, codex) were never reclaimed: :mod:`dev_lab.dev.checkout`
DETECTED them and ``branchset --apply`` deleted merged local branches but skipped every branch checked out in a
worktree, so a finished tree pinned its branch forever. First principles: a lease ends when its branch's CONTENT
is landed (or its PR closed and its origin ref deleted after a squash merge) AND the tree holds nothing that exists
nowhere else. :func:`reclaimable` is that one decision, built on :mod:`dev_lab.dev.checkout`'s readings (content
by ``git cherry``, never ancestry; ``None`` when git cannot answer); :func:`reclaim` acts on it. The doors are
``python -m dev_lab.dev.worktrees --prune`` (which the session debris hook runs) and ``python -m
dev_lab.dev.branchset --apply``, which reclaims first so the freed branch is deleted in the same run.
"""

from __future__ import annotations

import shutil
import subprocess
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
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

__all__ = ['REGENERABLE', 'Lease', 'blockers', 'reclaim', 'reclaimable', 'regenerable']

#: THE family default: ignored path parts (``fnmatch`` patterns) a build or a tool regenerates on
#: demand, so they may go with their tree. A repo adds its own in ``[tool.lab_commons.worktrees]
#: regenerable`` of its ``pyproject.toml``; anything ignored and not matched is WORK and blocks.
REGENERABLE: Final = frozenset(
    {
        '__pycache__',
        '.pytest_cache',
        '.ruff_cache',
        '.mypy_cache',
        '.venv',
        'node_modules',
        '.verify',
        '*.egg-info',
        '*.py[cod]',
        '.coverage*',
        'htmlcov',
        'build',
        'dist',
        'target',
        '__version__.py',
    }
)

#: How many paths a kept line names before it counts the rest.
_SHOWN: Final = 5


def regenerable(tree: Path) -> frozenset[str]:
    """:data:`REGENERABLE` plus *tree*'s declared ``[tool.lab_commons.worktrees] regenerable``."""
    manifest = tree / 'pyproject.toml'
    if not manifest.is_file():
        return REGENERABLE
    with manifest.open('rb') as handle:
        declared = tomllib.load(handle).get('tool', {}).get('lab_commons', {}).get('worktrees', {})
    extra = declared.get('regenerable', [])
    if not isinstance(extra, list) or not all(isinstance(item, str) for item in extra):
        msg = f'[tool.lab_commons.worktrees] regenerable in {manifest} must be a list of strings, got {extra!r}'
        raise ValueError(msg)
    return REGENERABLE | frozenset(extra)


def _is_regenerable(path: str, patterns: frozenset[str]) -> bool:
    return any(fnmatch(part, pattern) for part in PurePosixPath(path).parts for pattern in patterns)


def blockers(tree: Path) -> tuple[str, ...] | None:
    """Every path that stops *tree* from being removed: modified, staged, untracked, or ignored work."""
    out = git_out(tree, 'status', '--porcelain', '--ignored=matching')
    if out is None:
        return None
    patterns = regenerable(tree)
    found: list[str] = []
    for line in out.splitlines():
        code, path = line[:2], line[3:].strip().rstrip('/')
        if code == '!!' and _is_regenerable(path, patterns):
            continue
        found.append(f'{code.strip() or "?"} {path}')
    return tuple(found)


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
        return f'not clean -- commit or clear first: {_shown(blocking)}'
    if not _landed(tree, branch, holders):
        return f'not landed -- its content is on none of {", ".join(holders)}'
    return ''


def _orphan_reason(orphan: Path, patterns: frozenset[str]) -> str:
    work = sorted(
        p.relative_to(orphan).as_posix()
        for p in orphan.rglob('*')
        if not p.is_dir() and not _is_regenerable(p.relative_to(orphan).as_posix(), patterns)
    )
    return f'unregistered and holds more than regenerable files -- a human decides: {_shown(work)}' if work else ''


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
    * CLEAN: nothing staged, modified or untracked, and every ignored path regenerable (:func:`blockers`);
    * LANDED: its HEAD's content is on one of *holders* (``git cherry`` empty -- content, not ancestry), or
      its branch's origin ref is gone and its whole change is one commit's change on a holder (squash merge);
    * UNOCCUPIED: no process works in, executes from or reads it (LIVE-RUN's :func:`occupants` by default).

    An orphan directory under *home* is reclaimable iff every file in it is regenerable and nothing occupies
    it. *holders* are the refs whose content counts as landed: the trunk's authority and every declared session
    (``dev_lab.dev.branchset.holders``).
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
    patterns = regenerable(root)
    for orphan in orphans:
        reason = _orphan_reason(orphan, patterns)
        leases.append(Lease(orphan, '', reason or (_LIVE if is_occupied(orphan) else '')))
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

    A worktree goes by ``git worktree remove`` WITHOUT ``--force``, so git's own clean check stands behind
    this one; its branch stays for ``dev_lab.dev.branchset.apply_local``, which deletes it pinned to its sha.
    An orphan holds only regenerable files and goes by ``shutil.rmtree``. Without *apply* nothing is touched.
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
        elif lease.branch:
            done = git_out(root, 'worktree', 'remove', str(lease.path)) is not None
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
