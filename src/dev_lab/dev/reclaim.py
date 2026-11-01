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
import subprocess
import time
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

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
from dev_lab.dev.diskusage import remove_tree
from dev_lab.dev.family import declared_table
from dev_lab.dev.forgereview_runtimes import host_runtimes
from dev_lab.dev.liverun import Census, removal_holders
from dev_lab.dev.worktree_archive import home_outputs

__all__ = [
    'QUIET_S',
    'Lease',
    'blockers',
    'declared_generated',
    'orphan_reason',
    'reclaim',
    'reclaimable',
    'remove_tree',
    'repository_at',
    'runtime_of',
    'untracked',
]

#: How many paths a kept line names before it counts the rest.
_SHOWN: Final = 5
#: A tree whose index moved this recently is a LIVE SESSION (it staged, committed or checked out): never reclaimed.
QUIET_S: Final = 3600.0


def declared_generated(main: Path) -> tuple[str, ...]:
    """The globs ``[tool.dev_lab.worktrees] generated`` of *main* declares: TRACKED files a tool regenerates.

    A change to one is not work (a re-rendered lock or settings file), so it never keeps a tree. Default none.
    """
    manifest = main / 'pyproject.toml'
    if not manifest.is_file():
        return ()
    with manifest.open('rb') as handle:
        table = declared_table(tomllib.load(handle), 'worktrees', {})
    globs = table.get('generated', [])
    if not isinstance(globs, list) or not all(isinstance(one, str) and one for one in globs):
        msg = f'[tool.dev_lab.worktrees] generated in {manifest} must be a list of path globs'
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


def untracked(tree: Path) -> tuple[str, ...]:
    """The untracked, NOT ignored files in *tree*: a file never added is work only this tree holds.

    User ruling 2026-10-27 (superseding 10-25 for the automatic path): an automatic delete keeps such a tree;
    ignored content (``.venv``, caches, builds) is still disposable, and run outputs are moved home first.
    """
    out = git_out(tree, 'ls-files', '--others', '--exclude-standard', '-z')
    return tuple(p for p in (out or '').split('\0') if p)


def _index_age_s(tree: Path) -> float | None:
    """Seconds since *tree*'s index last changed; ``None`` when it has none to read."""
    index = (git_out(tree, 'rev-parse', '--path-format=absolute', '--git-path', 'index') or '').strip()
    try:
        return time.time() - Path(index).stat().st_mtime if index else None
    except OSError:
        return None


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


def occupancy(*, census: Census = processes, me: int | None = None) -> Callable[[Path], bool]:
    """The REMOVAL lock (:func:`dev_lab.dev.liverun.removal_holders`) over ONE process snapshot."""
    table = tuple(census())
    return lambda path: bool(removal_holders(path, census=lambda: table, me=me))


_LIVE: Final = 'live -- a process works in, executes from or reads it'


@dataclass(frozen=True)
class _Judge:
    holders: tuple[str, ...]
    generated: tuple[str, ...]
    quiet_s: float


def _unsaved(tree: Path, generated: tuple[str, ...]) -> str:
    """Why *tree* holds work that exists nowhere else -- a tracked change or an untracked file; ``''`` when none."""
    blocking = blockers(tree, generated) if tree.is_dir() else None
    if blocking is None:
        return 'unreadable'
    if blocking:
        return f'tracked changes -- commit or revert first: {_shown(blocking)}'
    loose = untracked(tree)
    return f'untracked files -- add, move or delete them first: {_shown(loose)}' if loose else ''


def _tree_reason(tree: Path, branch: str, judge: _Judge, *, locked: bool) -> str:
    holders = judge.holders
    if locked:
        return 'locked (git worktree unlock first)'
    if unsaved := _unsaved(tree, judge.generated):
        return unsaved
    age = _index_age_s(tree)
    if age is not None and age < judge.quiet_s:
        return f'index changed {age / 60:.0f} min ago -- a live session'
    if not _landed(tree, branch, holders):
        return f'not landed -- its content is on none of {", ".join(holders)}'
    return ''


#: Why an orphan that was a worktree is kept: its repository is gone, so its files may be the only copy.
_SEVERED: Final = 'a severed worktree (its .git points nowhere) -- its files may be the only copy; salvage them first'


def runtime_of(tree: Path, runtimes: Mapping[str, Mapping[str, Any]]) -> str:
    """Why *tree* stays because the host runs from it: ``runtime of <name>``; ``''`` when no runtime lives there.

    Issue dev-lab#26 (2026-11-01): ``branchset --apply`` reclaimed the detached, landed tree whose ``.venv`` the
    machine file's ``[runtimes.ai_lab] python`` names -- the forge serve's review interpreter. A tree holding
    any path a ``[runtimes.<name>]`` value declares is that host's runtime, never a finished lease. A value is
    judged by where it LIVES, never where its leaf points: a POSIX venv's ``bin/python`` links outside the tree.
    """
    home = tree.resolve()

    def lives_in_tree(value: str) -> bool:
        path = Path(value).expanduser()
        return (path.parent.resolve() / path.name).is_relative_to(home)

    names = sorted(
        name
        for name, row in runtimes.items()
        for value in row.values()
        if isinstance(value, str) and value and lives_in_tree(value)
    )
    return (
        f'runtime of {", ".join(dict.fromkeys(names))} -- the host config [runtimes] names a path in it'
        if names
        else ''
    )


def orphan_reason(orphan: Path, is_occupied: Callable[[Path], bool]) -> str:
    """Why *orphan* stays: occupied, or SEVERED -- it still has a ``.git`` file (incident 2026-10-27).

    A directory git no longer lists that holds a ``.git`` FILE was a linked worktree whose repository record is
    gone (a deleted main checkout, a re-clone): nothing else holds what was never pushed.
    """
    if is_occupied(orphan):
        return _LIVE
    return _SEVERED if (orphan / '.git').is_file() else ''


def reclaimable(
    root: Path,
    holders: tuple[str, ...],
    *,
    home: Path = DEFAULT_WORKTREE_HOME,
    occupied: Callable[[Path], bool] | None = None,
    quiet_s: float = QUIET_S,
    runtimes: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[Lease, ...] | None:
    """Every LINKED worktree and orphan directory of *root*, judged; ``None`` when git could not answer.

    A linked worktree (never the main one) is reclaimable iff ALL hold, checked in this order:

    * not ``git worktree lock``-ed;
    * no TRACKED change, staged or not (:func:`blockers`) -- ignored files, CR/LF-only changes and declared
      generated paths never block;
    * no UNTRACKED, not-ignored file (:func:`untracked`): a file never added exists nowhere else;
    * QUIET: its index unchanged for *quiet_s* seconds (a session that stages, commits or checks out is live);
    * LANDED: its HEAD's content is on one of *holders* (``git cherry`` empty -- content, not ancestry), or
      its branch's origin ref is gone and its whole change is one commit's change on a holder (squash merge);
    * NOT A RUNTIME: no ``[runtimes.<name>]`` value of *runtimes* (default this host's machine file,
      :func:`dev_lab.dev.forgereview_runtimes.host_runtimes`) names a path inside it (:func:`runtime_of`);
    * UNOCCUPIED: no process works in, executes from or reads it -- the sweep's own ancestors included
      (:func:`occupancy` by default).

    An orphan directory under *home* is reclaimable iff nothing occupies it and it is not SEVERED (a ``.git``
    file) and holds no runtime. *holders* are the refs whose content counts
    as landed: the trunk's authority and every declared session (``dev_lab.dev.branchset.holders``).
    """
    trees = worktrees(root)
    locked = _locked(root)
    orphans = orphan_directories(root, home=home)
    if trees is None or locked is None or orphans is None:
        return None
    is_occupied = occupied or occupancy()
    judge = _Judge(holders, declared_generated(root), quiet_s)
    declared = host_runtimes() if runtimes is None else runtimes
    leases: list[Lease] = []
    for path, branch in trees[1:]:
        tree = path.resolve()
        reason = _tree_reason(tree, branch, judge, locked=tree in locked) or runtime_of(tree, declared)
        leases.append(Lease(tree, branch, reason or (_LIVE if is_occupied(tree) else '')))
    leases += [
        Lease(orphan, '', runtime_of(orphan, declared) or orphan_reason(orphan, is_occupied)) for orphan in orphans
    ]
    return tuple(leases)


def _removed(tree: Path) -> str:
    """Delete *tree* all or nothing; ``''`` when gone, else the line saying why it stays and in what state.

    Incident 2026-10-31: a deletion refused partway by a held interpreter left every tracked file deleted. So
    the tree is first MOVED ASIDE -- Windows refuses to move a directory a process holds, before a byte is gone
    -- and a deletion that still fails moves it back and restores its tracked files from HEAD.
    """
    aside = tree.with_name(f'{tree.name}.reclaiming')
    link = tree / '.git'
    gitfile = link.read_bytes() if link.is_file() else None
    try:
        tree.rename(aside)
    except OSError as error:
        return f'kept     {{label}}  (in use -- {error}; nothing was deleted)'
    try:
        remove_tree(aside)
    except OSError as error:
        return f'FAILED   {{label}}  ({error}; {_restored(aside, tree, gitfile)})'
    return ''


def _restored(aside: Path, tree: Path, gitfile: bytes | None) -> str:
    """Put a half-deleted *aside* back at *tree*, its ``.git`` link and tracked files from HEAD; the state, in words."""
    try:
        aside.rename(tree)
    except OSError as error:
        return f'left half-deleted at {aside}: {error}'
    if gitfile is not None and not (tree / '.git').exists():
        (tree / '.git').write_bytes(gitfile)
    restore = git_out(tree, 'restore', '--source=HEAD', '--worktree', '--', '.')
    return 'restored from HEAD' if restore is not None else f'left half-deleted at {tree}: git restore failed'


def reclaim(
    root: Path,
    holders: tuple[str, ...],
    *,
    home: Path = DEFAULT_WORKTREE_HOME,
    occupied: Callable[[Path], bool] | None = None,
    apply: bool = True,
    limit: int | None = None,
    quiet_s: float = QUIET_S,
    runtimes: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[str, ...] | None:
    """Remove every reclaimable lease; one line per lease, a kept one with its reason. ``None``: unreadable.

    Every lease's run outputs are moved HOME first (:func:`dev_lab.dev.worktree_archive.home_outputs`) and
    the copy verified; only then is the tree deleted by :func:`remove_tree` (its untracked and ignored content
    is declared disposable) and git's registration pruned. An unverified archive keeps the lease, with the
    reason. A removed tree's branch stays for ``dev_lab.dev.branchset.apply_local``, which deletes it pinned
    to its sha. *runtimes* is :func:`reclaimable`'s. Without *apply* nothing is touched; past *limit*
    removals the rest are ``deferred`` to a later run.
    """
    leases = reclaimable(root, holders, home=home, occupied=occupied, quiet_s=quiet_s, runtimes=runtimes)
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
        elif refused := _removed(lease.path):
            out.append(refused.replace('{label}', label))
        else:
            removed += 1
            out.append(f'removed  {label}')
    if apply:
        git_out(root, 'worktree', 'prune')
    return tuple(out)
