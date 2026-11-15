"""TWO-FATES: every local branch and linked worktree is merged and cleaned up, or cleaned up. Nothing lingers.

User ruling 2026-11-15. The doors before it each covered one state: :func:`dev_lab.dev.reclaim.reclaim` removes a
LANDED and CLEAN tree, :func:`dev_lab.dev.branchset.apply_local` deletes a LANDED branch no tree holds, and
``branchset --discard`` drops ONE unlanded lane the user names. Every other state had no fate and lingered -- an
unlanded lane nobody works on, a never-pushed branch with no tree, a landed tree with a stray tracked edit (incident
2026-10-31: the door refused them and offered no path, so they stayed). :func:`settle` runs after those doors and
gives each local branch and linked tree still standing exactly ONE verdict, with its reason:

* ``owned``: it has a LIVE OWNER and is kept, listed with that owner -- a process works in the tree (the removal
  lock, :func:`dev_lab.dev.reclaim.occupancy`), a ``git worktree lock``, a host runtime lives in it
  (:func:`dev_lab.dev.reclaim.runtime_of`), a session touched its index or tip within the window -- *quiet_s*
  (reclaim's live-session hour) for MERGED work, :data:`ABANDONED_S` for UNMERGED work -- or, unlanded, origin
  carries the branch: its open PR or pushed lane is origin's to judge (:mod:`dev_lab.dev.branchprune` deletes it
  once the PR is gone, and the next run here finds it ownerless);
* ``merged`` / ``abandoned``: no owner. It is PRESERVED LOSSLESSLY first -- a verified ``git bundle`` of the tip,
  the tree's uncommitted tracked work and untracked files (:func:`dev_lab.dev.worktree_archive.save_work`), and a
  ``manifest.json`` with every file's sha256, under the checkout's ``archive-to`` directory -- then the tree is
  removed (:func:`dev_lab.dev.reclaim.removed_approved`: outputs home, all or nothing) and the branch deleted,
  pinned to the sha that was bundled. A step that fails keeps the rest and is a ``FAILED`` line naming why; the
  next run retries it.

THE ONE LANE THE USER NAMES is :func:`discard` (``branchset --discard <branch> --approved "<words>"``, ruling
2026-11-13): it needs no abandonment, only the user's words. ``python -m dev_lab.dev.branchset --apply`` is the
door; the ``SessionStart`` reclaim (:mod:`dev_lab.dev.reclaimrun`) runs it in the background.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from dev_lab.dev.checkout import git_out, worktrees
from dev_lab.dev.forgereview_runtimes import host_runtimes
from dev_lab.dev.reclaim import QUIET_S, index_age_s, locked_trees, occupancy, removed_approved, runtime_of
from dev_lab.dev.worktree_archive import archive_home, save_work

if TYPE_CHECKING:
    from dev_lab.dev.branchset import BranchSet

__all__ = ['ABANDONED_S', 'Fate', 'discard', 'judge', 'preserve', 'settle']

#: How long UNMERGED work must sit untouched (index and tip) before it counts as abandoned: sessions pause
#: overnight and lanes wait on long forge runs, so the 1 h live-session window that suffices for MERGED trees is
#: far too short here. 24 h -- the same value as the orphaned-PR age of the integrator hand-off (``ORPHAN_AGE``),
#: stated here rather than imported.
ABANDONED_S: Final = 24 * 3600.0

#: The verdict words, padded so every line's subject starts in one column.
_OWNED: Final = 'owned    '
_DETACHED: Final = 'detached'


@dataclass(frozen=True)
class Fate:
    """One local branch or linked tree, and its fate: kept for *owner*, or (no owner) cleaned as *verdict*."""

    branch: str
    sha: str
    tree: Path | None
    owner: str
    merged: bool

    @property
    def label(self) -> str:
        """The branch name, or the tree's name for a detached HEAD."""
        return self.branch if self.branch != _DETACHED else f'{_DETACHED}:{self.tree.name if self.tree else "?"}'


def _sha(root: Path, rev: str) -> str:
    return (git_out(root, 'rev-parse', '--verify', '--quiet', f'{rev}^{{commit}}') or '').strip()


def _tip_age_s(root: Path, sha: str) -> float | None:
    out = (git_out(root, 'log', '-1', '--format=%ct', sha) or '').strip()
    return time.time() - int(out) if out.isdigit() else None


def _owner(root: Path, fate: Fate, *, occupied: Callable[[Path], bool], quiet_s: float, abandoned_s: float,
           locked: frozenset[Path],
           runtimes: Mapping[str, Mapping[str, Any]]) -> str:  # fmt: skip
    """Who keeps *fate* alive, in words; ``''`` when nobody does."""
    tree = fate.tree
    if tree is not None:
        if tree in locked:
            return 'locked (git worktree lock)'
        if runtime := runtime_of(tree, runtimes):
            return runtime
        if occupied(tree):
            return 'live -- a process works in, executes from or reads it'
    ages = [_tip_age_s(root, fate.sha), index_age_s(tree) if tree is not None else None]
    window = quiet_s if fate.merged else max(quiet_s, abandoned_s)
    if (age := min((a for a in ages if a is not None), default=None)) is not None and age < window:
        return f'live session -- touched {age / 3600:.1f} h ago, quiet less than {window / 3600:g} h'
    on_origin = fate.branch != _DETACHED and _sha(root, f'refs/remotes/origin/{fate.branch}')
    if on_origin and not fate.merged:
        return 'on origin -- its PR or lane is judged there (branchprune)'
    return ''


def judge(
    root: Path,
    holders: tuple[str, ...],
    declared: frozenset[str],
    *,
    occupied: Callable[[Path], bool] | None = None,
    quiet_s: float = QUIET_S,
    abandoned_s: float = ABANDONED_S,
    runtimes: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[Fate, ...] | None:
    """Every linked tree and every undeclared local branch of *root*, judged; ``None`` when git could not answer.

    The main checkout and its branch, and every *declared* branch, are never judged: they are the repo's own.
    """
    trees = worktrees(root)
    locked = locked_trees(root)
    local = git_out(root, 'for-each-ref', '--format=%(refname:short)', 'refs/heads/')
    if trees is None or locked is None or local is None:
        return None
    is_occupied = occupied or occupancy()
    hosts = host_runtimes() if runtimes is None else runtimes
    held = {branch: path.resolve() for path, branch in trees[1:] if branch != _DETACHED}
    subjects = [(branch, path.resolve()) for path, branch in trees[1:] if branch not in declared]
    subjects += [(n, None) for n in sorted(set(local.split()) - declared - set(held) - {trees[0][1]})]
    fates: list[Fate] = []
    for branch, tree in subjects:
        sha = _sha(tree if tree is not None else root, 'HEAD' if tree is not None else f'refs/heads/{branch}')
        if not sha:
            continue
        merged = any(git_out(root, 'merge-base', '--is-ancestor', sha, h) is not None for h in holders)
        fate = Fate(branch, sha, tree, '', merged)
        owner = _owner(
            root, fate, occupied=is_occupied, quiet_s=quiet_s, abandoned_s=abandoned_s, locked=locked, runtimes=hosts
        )
        fates.append(Fate(branch, sha, tree, owner, merged))
    return tuple(fates)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preserve(root: Path, fate: Fate, *, today: datetime | None = None) -> tuple[Path | None, str]:
    """Save *fate* losslessly under *root*'s archive home; ``(directory, '')``, or ``(None, why it failed)``."""
    stamp = (today or datetime.now(UTC)).strftime('%Y%m%d')
    saved = archive_home(root) / stamp / fate.label.replace('/', '--').replace(':', '--')
    if saved.exists():
        saved = saved.with_name(f'{saved.name}-{fate.sha[:10]}')
    saved.mkdir(parents=True, exist_ok=True)
    bundle = saved / 'branch.bundle'
    where, ref = (fate.tree, 'HEAD') if fate.branch == _DETACHED and fate.tree else (root, f'refs/heads/{fate.branch}')
    if git_out(where, 'bundle', 'create', str(bundle), ref) is None:
        return None, f'git bundle create {ref} failed'
    if git_out(root, 'bundle', 'verify', str(bundle)) is None:
        return None, f'git bundle verify {bundle} failed'
    if fate.tree is not None:
        try:
            save_work(fate.tree, saved)
        except (OSError, RuntimeError) as error:
            return None, f'the tree work was not saved: {error}'
    files = {p.relative_to(saved).as_posix(): _digest(p) for p in sorted(saved.rglob('*')) if p.is_file()}
    manifest = {
        'branch': fate.branch,
        'sha': fate.sha,
        'tree': str(fate.tree) if fate.tree else None,
        'fate': 'merged' if fate.merged else 'abandoned',
        'restore': f'git fetch {bundle.name} {ref}:refs/heads/<name>',
        'files': files,
    }
    (saved / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return saved, ''


def _cleaned(root: Path, fate: Fate, quiet_s: float) -> str:
    """Remove *fate*'s tree, then delete its branch pinned to the bundled sha; ``''`` when both are done."""
    if fate.tree is not None and (refused := removed_approved(root, fate.tree, quiet_s=quiet_s)):
        return refused
    if fate.branch == _DETACHED:
        return ''
    if git_out(root, 'update-ref', '-d', f'refs/heads/{fate.branch}', fate.sha) is None:
        return f'the branch delete pinned at {fate.sha[:10]} failed (it moved?)'
    return ''


def settle(
    root: Path,
    holders: tuple[str, ...],
    declared: frozenset[str] = frozenset(),
    *,
    occupied: Callable[[Path], bool] | None = None,
    quiet_s: float = QUIET_S,
    abandoned_s: float = ABANDONED_S,
    limit: int | None = None,
    runtimes: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[str, ...] | None:
    """Give every judged branch and tree its fate; one line each. ``None``: git could not answer, nothing touched.

    *limit* bounds the cleanups per run; the rest are ``deferred`` to the next.
    """
    fates = judge(
        root, holders, declared, occupied=occupied, quiet_s=quiet_s, abandoned_s=abandoned_s, runtimes=runtimes
    )
    if fates is None:
        return None
    out: list[str] = []
    done = 0
    for fate in fates:
        verdict = 'merged   ' if fate.merged else 'abandoned'
        where = f'  [{fate.tree}]' if fate.tree else ''
        if fate.owner:
            out.append(f'{_OWNED} {fate.label}{where}  ({fate.owner})')
            continue
        if limit is not None and done >= limit:
            out.append(f'deferred  {fate.label}{where}  (batch of {limit} reached)')
            continue
        saved, why = preserve(root, fate)
        if saved is None:
            out.append(f'FAILED    {fate.label}{where}  (not archived, nothing removed: {why})')
            continue
        if why := _cleaned(root, fate, quiet_s):
            out.append(f'FAILED    {fate.label}{where}  (archived at {saved}; {why})')
            continue
        done += 1
        out.append(f'{verdict} {fate.label} ({fate.sha[:10]})  archived at {saved}, cleaned up')
    return tuple(out)


def discard(
    root: Path, branchset: BranchSet, branch: str, approved: str, *, quiet_s: float = QUIET_S
) -> tuple[int, str]:
    """Drop ONE lane the user approved: its worktree, then its local branch; ``(exit code, the one line)``.

    *approved* is the user's own words, echoed into the line so the record says who decided. Refused (exit 1,
    nothing touched): no approval, a declared branch (trunk or session), no local branch of that name, the main
    checkout's branch, a live session (:func:`dev_lab.dev.reclaim.removed_approved`).
    """
    ref = f'refs/heads/{branch}'
    sha = (git_out(root, 'rev-parse', '--verify', '--quiet', ref) or '').strip()
    trees = worktrees(root)
    held = [path for path, name in trees or () if name == branch]
    if why := _discard_refusal(root, branchset, branch, approved, sha=sha, trees=trees):
        return 1, f'refused  {branch}  ({why})'
    for tree in held:
        if why := removed_approved(root, tree, quiet_s=quiet_s):
            return 1, f'refused  {branch}  ({tree}: {why})'
    if git_out(root, 'update-ref', '-d', ref, sha) is None:
        return 1, f'FAILED   {branch}  (its worktree is gone; the branch delete at {sha[:10]} failed)'
    where = f'worktree {held[0]} and ' if held else ''
    return 0, f'discarded {where}local {branch} ({sha[:10]}) -- approved: "{approved.strip()}"'


def _discard_refusal(
    root: Path,
    branchset: BranchSet,
    branch: str,
    approved: str,
    *,
    sha: str,
    trees: tuple[tuple[Path, str], ...] | None,
) -> str:
    """Why :func:`discard` touches nothing, read before any delete; ``''`` when it may go on."""
    if not approved.strip():
        return '--approved "<the user words>" is required: the user decides a discard'
    if branch in branchset.declared:
        return 'declared in [tool.dev_lab.branchset]: the trunk and sessions are never discarded'
    if not sha:
        return 'no local branch of that name; origin is never discarded here'
    if trees is None:
        return f'git could not list the worktrees of {root}'
    if trees and trees[0][1] == branch:
        return f'the main checkout holds it at {trees[0][0]}'
    return ''
