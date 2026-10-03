"""WORKTREES-STAY-INSIDE, as the assertion every consumer runs: no checkout of this repo lives outside it.

The PREVENTION half is the deny row of the same ID; this is the DETECTION half, for whatever got past
it -- a tree made before the row shipped, from a shell no hook watches, or by an absolute path into
some other directory's ``.claude/worktrees`` that a text pattern cannot tell from this repo's own.

THE ONE REPO-SHAPED FACT ARRIVES AS AN ARGUMENT WITH NO DEFAULT: *root*, any checkout of the repo.
Everything else -- the location, the reader, the remedy -- is :mod:`lab_commons.dev.worktreeplace`'s,
so a consumer's test file is one call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lab_commons.dev.worktreeplace import WORKTREES_REL, listed_worktrees, misplaced_worktrees, remedy

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['assert_every_worktree_stays_inside']


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
