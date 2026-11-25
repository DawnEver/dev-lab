"""THE LOCAL BRANCH DELETE door: ``python -m dev_lab.dev.branchdelete --local [--apply]``.

Wall 2026-11-25 (a user-ruled cleanup of ~170 landed local branches across the family): no local door knew the
rule and spared the live lanes -- ``branchset --apply`` also reclaims worktrees, ``branchprune`` acts on origin.
This one touches LOCAL refs only and nothing else:

* a local branch is DELETABLE when its tip is an ancestor of ``origin/integrate/main``, of any ``origin/pr/*``
  head, or of a ref the caller declares with ``--contained-in`` -- every commit on it is held there;
* never one checked out in any worktree, one matching a ``--keep`` glob, nor the trunk or integration branch;
* a dry run LISTS (the default); ``--apply`` deletes each pinned to the sha it was judged at
  (``update-ref -d <ref> <sha>``), so a branch that moved in between is kept.
"""

from __future__ import annotations

from collections.abc import Sequence
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Final

from dev_lab.dev.branchset import checked_out
from dev_lab.dev.checkout import git_out

__all__ = ['ALWAYS_KEPT', 'INTEGRATION', 'sweep_local']

#: The origin integration ref every family repo lands on.
INTEGRATION: Final = 'refs/remotes/origin/integrate/main'
#: Local branches never deleted by this door, whatever contains them.
ALWAYS_KEPT: Final = ('main', 'integrate/main')


def _contained(root: Path, sha: str, holders: Sequence[str]) -> str:
    """The first of *holders* whose history holds *sha*; ``''`` when none does."""
    return next((ref for ref in holders if git_out(root, 'merge-base', '--is-ancestor', sha, ref) is not None), '')


def _holders(root: Path, contained_in: Sequence[str]) -> tuple[str, ...]:
    listed = git_out(root, 'for-each-ref', '--format=%(refname)', 'refs/remotes/origin/pr/') or ''
    found = [INTEGRATION] if git_out(root, 'rev-parse', '--verify', '--quiet', INTEGRATION) else []
    return (*found, *listed.split(), *contained_in)


def _judged(root: Path, keep: Sequence[str], contained_in: Sequence[str]) -> list[tuple[str, str, str, str]]:
    """``(verdict, branch, sha, why)`` for every local branch; verdict ``deletable`` or ``kept``."""
    busy = checked_out(root)
    holders = _holders(root, contained_in)
    listed = git_out(root, 'for-each-ref', '--format=%(refname:short) %(objectname)', 'refs/heads/') or ''
    rows = []
    for line in listed.splitlines():
        branch, _, sha = line.partition(' ')
        if branch in ALWAYS_KEPT or any(fnmatchcase(branch, glob) for glob in keep):
            rows.append(('kept', branch, sha, 'keep'))
        elif branch in busy:
            rows.append(('kept', branch, sha, 'checked out in a worktree'))
        elif holder := _contained(root, sha, [ref for ref in holders if ref not in {branch, f'refs/heads/{branch}'}]):
            rows.append(('deletable', branch, sha, f'contained in {holder}'))
        else:
            rows.append(('kept', branch, sha, 'commits only here -- fold or discard'))
    return rows


def sweep_local(
    root: Path, *, keep: Sequence[str] = (), contained_in: Sequence[str] = (), apply: bool = False
) -> tuple[str, ...]:
    """One line per local branch; with *apply*, delete the deletable ones pinned to their judged sha."""
    lines = []
    for judged, branch, sha, reason in _judged(root, keep, contained_in):
        verdict, why = judged, reason
        if judged == 'deletable' and apply:
            gone = git_out(root, 'update-ref', '-d', f'refs/heads/{branch}', sha) is not None
            verdict, why = ('deleted', reason) if gone else ('kept', f'moved since judged; {reason}')
        lines.append(f'{verdict:<9} {branch}  {sha[:10]}  ({why})')
    return tuple(lines)
