"""Throwaway comparison trees: ``worktrees --scratch`` makes one DISPOSABLE, ``--discard`` removes it now.

Split from :mod:`dev_lab.dev.reclaim`, which keeps the disposable declaration (:mod:`dev_lab.dev.disposable`)
because its reclaim pass judges such a tree too.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from dev_lab.dev.checkout import git_out, locked_trees, worktrees
from dev_lab.dev.disposable import disposable_base, marker
from dev_lab.dev.reclaim import (
    _LIVE,
    _removed,
    _scrap_unsaved,
    declared_generated,
    home_outputs,
    occupancy,
    repository_at,
)
from dev_lab.dev.worktreeplace import home as worktree_home

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ['discard', 'scratch']


def _scratch_path(root: Path, name: str, home: Path | None) -> tuple[Path, Path] | None:
    """(main checkout, ``<home>/<name>``) when *name* is one plain segment and git reads *root*.

    *home* None is the repository's worktree home (:func:`dev_lab.dev.worktreeplace.home`), bound or in-tree.
    """
    trees = worktrees(root)
    if not trees or name in {'', '.', '..'} or any(sep in name for sep in '/\\:'):
        return None
    main = trees[0][0].resolve()
    return main, (main / home if home is not None else worktree_home(main)) / name


def scratch(root: Path, name: str, sha: str, *, home: Path | None = None) -> str:
    """Make a DETACHED tree ``<home>/<name>`` of *root*'s main checkout at *sha* and declare it DISPOSABLE.

    The throwaway comparison checkout (a base to diff tests against): its untracked and ignored content is scratch,
    so :func:`discard` removes it, and :func:`reclaim` once it is quiet, with no landing to wait for. One line:
    ``made ...`` or ``refused: ...``.
    """
    place = _scratch_path(root, name, home)
    if place is None:
        return f'refused: {name!r} is not one plain directory name, or git cannot read {root}'
    main, tree = place
    if tree.exists():
        return f'refused: {tree} already exists'
    if git_out(main, 'worktree', 'add', '--detach', str(tree), sha) is None:
        return f'refused: git worktree add --detach {tree} {sha} failed'
    commit = (git_out(tree, 'rev-parse', 'HEAD') or '').strip()
    declared = marker(tree)
    if not commit or declared is None:
        return f'FAILED   {tree} was made but not declared disposable; it is an ordinary lease'
    declared.write_text(commit + '\n', encoding='utf-8')
    return f'made     {tree}  [detached {commit[:12]}, disposable]'


def discard(root: Path, name: str, *, home: Path | None = None, occupied: Callable[[Path], bool] | None = None) -> str:
    """Remove the DISPOSABLE tree ``<home>/<name>`` of *root*'s main checkout now; one line, ``removed`` or why not.

    Refused: a path that is not a registered linked worktree, a main checkout or repository
    (:func:`repository_at`), a tree :func:`scratch` did not declare, a locked one, one with a tracked change or a
    HEAD no ref holds, one any process works in, executes from or reads (:func:`occupancy`, the asker's own family
    included), and one holding run outputs (a writer defect). Submodule checkouts inside it go with it: git keeps
    their repositories in the tree's admin directory, which the prune removes.
    """
    place = _scratch_path(root, name, home)
    locked = locked_trees(root)
    trees = worktrees(root)
    if place is None or locked is None or trees is None:
        return f'refused: {name!r} is not one plain directory name, or git cannot read {root}'
    main, tree = place[0], place[1].resolve()
    if tree not in {path.resolve() for path, _ in trees[1:]}:
        return f'refused: {tree} is not a linked worktree of {main}'
    base = disposable_base(tree)
    reason = (
        repository_at(main, tree)
        or ('' if base else 'not declared disposable -- only a tree made by --scratch is discarded')
        or ('locked (git worktree unlock first)' if tree in locked else '')
        or _scrap_unsaved(tree, base, declared_generated(main))
        or (_LIVE if (occupied or occupancy())(tree) else '')
        or home_outputs(main, tree)
    )
    if reason:
        return f'refused: {tree} ({reason})'
    if refused := _removed(tree):
        return refused.replace('{label}', str(tree))
    git_out(main, 'worktree', 'prune')
    return f'removed  {tree}'
