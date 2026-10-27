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

import fnmatch
import shutil
import stat
import subprocess
import sys
import time
import tomllib
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

__all__ = [
    'QUIET_S',
    'Lease',
    'blockers',
    'declared_generated',
    'reclaim',
    'reclaimable',
    'remove_tree',
    'repository_at',
]

#: How many paths a kept line names before it counts the rest.
_SHOWN: Final = 5
#: A tree whose index moved this recently is a LIVE SESSION (it staged, committed or checked out): never reclaimed.
QUIET_S: Final = 3600.0
_LONG: Final = '\\\\?\\'


def declared_generated(main: Path) -> tuple[str, ...]:
    """The globs ``[tool.lab_commons.worktrees] generated`` of *main* declares: TRACKED files a tool regenerates.

    A change to one is not work (a re-rendered lock or settings file), so it never keeps a tree. Default none.
    """
    manifest = main / 'pyproject.toml'
    if not manifest.is_file():
        return ()
    with manifest.open('rb') as handle:
        table = tomllib.load(handle).get('tool', {}).get('lab_commons', {}).get('worktrees', {})
    globs = table.get('generated', [])
    if not isinstance(globs, list) or not all(isinstance(one, str) and one for one in globs):
        msg = f'[tool.lab_commons.worktrees] generated in {manifest} must be a list of path globs'
        raise ValueError(msg)
    return tuple(globs)


def blockers(tree: Path, generated: tuple[str, ...] = ()) -> tuple[str, ...] | None:
    """Every TRACKED path really changed in *tree* against HEAD, staged or not; untracked and ignored are not work.

    User ruling 2026-10-25: the work is committed; what git does not track (scratch, untracked, ignored:
    ``.venv``, caches, builds) goes with the tree, except run outputs, which :func:`reclaim` moves home first.
    Ruling 2026-10-27: a change that is only CR/LF at line ends (``--ignore-cr-at-eol``: line-ending churn of a
    checkout) or only to a path matching a *generated* glob is not work either.
    """
    out = git_out(tree, 'diff', 'HEAD', '--ignore-cr-at-eol', '--no-renames', '--numstat', '-z')
    if out is None:
        return None
    paths = (row.split('\t', 2)[-1] for row in out.split('\0') if row.strip())
    return tuple(p for p in paths if not any(fnmatch.fnmatchcase(p, glob) for glob in generated))


def _index_age_s(tree: Path) -> float | None:
    """Seconds since *tree*'s index last changed; ``None`` when it has none to read."""
    index = (git_out(tree, 'rev-parse', '--path-format=absolute', '--git-path', 'index') or '').strip()
    try:
        return time.time() - Path(index).stat().st_mtime if index else None
    except OSError:
        return None


def _writable(func: Callable[[str], object], path: str, _: BaseException) -> None:
    Path(path).chmod(stat.S_IWRITE)  # a read-only file (a git object) refuses deletion on Windows
    func(path)


def remove_tree(path: Path) -> None:
    r"""Delete directory *path* recursively, FAST and long-path safe: no git, no 260-character limit.

    ``git worktree remove`` measured minutes per tree on Windows (deep ``.venv`` paths); a recursive delete
    through the ``\\?\`` namespace measured seconds. Links and junctions are unlinked, never followed.
    """
    target = str(path.resolve())
    if sys.platform == 'win32' and not target.startswith(_LONG):
        target = _LONG + target
    shutil.rmtree(target, onexc=_writable)


def repository_at(root: Path, path: Path) -> str:
    """Why *path* must never be deleted as a lease: it is, or holds, *root*'s main checkout, or any repository.

    Incident 2026-10-27: a cleanup that took its leases from ``git worktree list`` and matched branches deleted
    a main checkout whose branch had landed -- ``.git``, unpushed work and ``output/`` with it. A linked
    worktree's ``.git`` is a FILE; a directory there is a repository of its own. Checked at the delete, not
    trusted to the listing. ``''`` when *path* is an ordinary linked tree.
    """
    tree, main = path.resolve(), root.resolve()
    if tree == main or main.is_relative_to(tree):
        return f'refused: {tree} is or holds the main checkout {main}'
    if (tree / '.git').is_dir():
        return f'refused: {tree} is a repository (its .git is a directory), never a linked worktree'
    return ''


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


@dataclass(frozen=True)
class _Judge:
    holders: tuple[str, ...]
    generated: tuple[str, ...]
    quiet_s: float


def _tree_reason(tree: Path, branch: str, judge: _Judge, *, locked: bool) -> str:
    holders = judge.holders
    if locked:
        return 'locked (git worktree unlock first)'
    blocking = blockers(tree, judge.generated) if tree.is_dir() else None
    if blocking is None:
        return 'unreadable'
    if blocking:
        return f'tracked changes -- commit or revert first: {_shown(blocking)}'
    age = _index_age_s(tree)
    if age is not None and age < judge.quiet_s:
        return f'index changed {age / 60:.0f} min ago -- a live session'
    if not _landed(tree, branch, holders):
        return f'not landed -- its content is on none of {", ".join(holders)}'
    return ''


def reclaimable(
    root: Path,
    holders: tuple[str, ...],
    *,
    home: Path = DEFAULT_WORKTREE_HOME,
    occupied: Callable[[Path], bool] | None = None,
    quiet_s: float = QUIET_S,
) -> tuple[Lease, ...] | None:
    """Every LINKED worktree and orphan directory of *root*, judged; ``None`` when git could not answer.

    A linked worktree (never the main one) is reclaimable iff ALL hold, checked in this order:

    * not ``git worktree lock``-ed;
    * no TRACKED change, staged or not (:func:`blockers`) -- untracked and ignored files, CR/LF-only changes
      and declared generated paths never block;
    * QUIET: its index unchanged for *quiet_s* seconds (a session that stages, commits or checks out is live);
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
    judge = _Judge(holders, declared_generated(root), quiet_s)
    leases: list[Lease] = []
    for path, branch in trees[1:]:
        tree = path.resolve()
        reason = _tree_reason(tree, branch, judge, locked=tree in locked)
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
    limit: int | None = None,
    quiet_s: float = QUIET_S,
) -> tuple[str, ...] | None:
    """Remove every reclaimable lease; one line per lease, a kept one with its reason. ``None``: unreadable.

    Every lease's run outputs are moved HOME first (:func:`dev_lab.dev.worktree_archive.home_outputs`) and
    the copy verified; only then is the tree deleted by :func:`remove_tree` (its untracked and ignored content
    is declared disposable) and git's registration pruned. An unverified archive keeps the lease, with the
    reason. A removed tree's branch stays for ``dev_lab.dev.branchset.apply_local``, which deletes it pinned
    to its sha. Without *apply* nothing is touched; past *limit* removals the rest are ``deferred`` to a later run.
    """
    leases = reclaimable(root, holders, home=home, occupied=occupied, quiet_s=quiet_s)
    if leases is None:
        return None
    out: list[str] = []
    removed = 0
    for lease in leases:
        label = f'{lease.path}  [{lease.branch}]' if lease.branch else f'{lease.path}  (unregistered)'
        if not lease.reclaimable:
            out.append(f'kept     {label}  ({lease.reason})')
        elif not apply:
            out.append(f'prunable {label}')
        elif limit is not None and removed >= limit:
            out.append(f'deferred {label}  (batch of {limit} reached)')
        elif unarchived := repository_at(root, lease.path) or home_outputs(root, lease.path):
            out.append(f'kept     {label}  ({unarchived}; nothing was deleted)')
        else:
            try:
                remove_tree(lease.path)
            except OSError as error:
                out.append(f'FAILED   {label}  ({error})')
            else:
                removed += 1
                out.append(f'removed  {label}')
    if apply:
        git_out(root, 'worktree', 'prune')
    return tuple(out)
