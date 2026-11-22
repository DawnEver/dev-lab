"""WORKTREES-STAY-INSIDE, as the assertion every consumer runs: no checkout of this repo lives outside it.

The PREVENTION half is the deny row of the same ID; this is the DETECTION half, for whatever got past
it -- a tree made before the row shipped, from a shell no hook watches, or by an absolute path into
some other directory's ``.claude/worktrees`` that a text pattern cannot tell from this repo's own.

THE ONE REPO-SHAPED FACT ARRIVES AS AN ARGUMENT WITH NO DEFAULT: *root*, any checkout of the repo.
Everything else -- the location, the reader, the remedy -- is :mod:`dev_lab.dev.worktreeplace`'s,
so a consumer's test file is one call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dev_lab.dev import worktreename
from dev_lab.dev.worktreeplace import WORKTREES_REL, listed_worktrees, misplaced_worktrees, remedy

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['assert_every_worktree_names_its_task', 'assert_every_worktree_stays_inside']


def assert_every_worktree_stays_inside(*, root: Path) -> None:
    """Every linked worktree of *root*'s repository lies inside ``<main>/.claude/worktrees/``.

    The floor is that git listed at least the main checkout: an empty list is an unread one. A red
    names every misplaced tree with the exact ``git worktree move`` that puts it where it belongs.
    """
    if not listed_worktrees(root):
        msg = f'git listed no worktree for {root}; the scan read nothing'
        raise AssertionError(msg)
    found = misplaced_worktrees(root)
    if found:
        moves = '\n'.join(f'  {remedy(item)}' for item in found)
        msg = (
            f'{len(found)} worktree(s) of this repository live OUTSIDE <toplevel>/{WORKTREES_REL}/ '
            f'(WORKTREES-STAY-INSIDE). Move each one in:\n{moves}'
        )
        raise AssertionError(msg)


def assert_every_worktree_names_its_task(*, root: Path) -> None:
    """No linked worktree of *root*'s repository has a hash-like directory name (WORKTREE-NAMES-ITS-TASK).

    The DETECTION half of the deny row of the same ID, for a tree no shell command made -- a harness minting
    ``agent-<hex>`` itself. The floor is the same: an empty list is an unread one. A red names every such tree
    with the ``git worktree move`` that renames it; the new name is its task's, so it is left to be filled in.
    """
    listed = listed_worktrees(root)
    if not listed:
        msg = f'git listed no worktree for {root}; the scan read nothing'
        raise AssertionError(msg)
    found = worktreename.hash_named(root)
    if found:
        moves = '\n'.join(f'  {worktreename.remedy(item, listed[0])}' for item in found)
        msg = (
            f'{len(found)} worktree(s) of this repository are named by a hash, not for their task '
            f'({worktreename.RULE}): {", ".join(item.name for item in found)}. Rename each one:\n{moves}'
        )
        raise AssertionError(msg)
