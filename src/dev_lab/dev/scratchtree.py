"""Trees the worktree door makes: ``--add`` a lane, ``--scratch`` a DISPOSABLE one, ``--discard`` removes it now.

Split from :mod:`dev_lab.dev.reclaim`, which keeps the disposable declaration (:mod:`dev_lab.dev.disposable`)
because its reclaim pass judges such a tree too.

EVERY TREE THIS DOOR MAKES IS WIRED (HOOKS-ARE-WIRED, v1 FAM-14 2026-11-27): under ``extensions.worktreeConfig`` a
``git worktree add`` starts with no ``core.hooksPath`` of its own, so each lane committed, merged and pushed with zero
family stages. :func:`lane` adds the branch, bootstraps the tree's venv and installs its hooks; :func:`scratch`
installs the hooks of its detached tree. A tree the door could not wire is reported ``FAILED`` by name.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import lab_commons.launch as _door

from dev_lab.dev.checkout import git_out, locked_trees, worktrees
from dev_lab.dev.disposable import disposable_base, marker
from dev_lab.dev.hook_install import HookInstallError, install
from dev_lab.dev.reclaim import (
    _LIVE,
    _removed,
    _scrap_unsaved,
    declared_generated,
    occupancy,
    repository_at,
)
from dev_lab.dev.venvpath import running_interpreter
from dev_lab.dev.worktreeplace import home as worktree_home

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ['bootstrap', 'discard', 'lane', 'scratch']


def _scratch_path(root: Path, name: str, home: Path | None, door: str) -> tuple[Path, Path] | str:
    """(main checkout, ``<home>/<name>``) when *name* is one plain segment and git reads *root*; else the refusal.

    Each cause is refused on its own with its door: *door* is the verb template (``--discard {}``) filled with the
    bare name. *home* None is the repository's worktree home (:func:`dev_lab.dev.worktreeplace.home`).
    """
    if name in {'', '.', '..'} or any(sep in name for sep in '/\\:'):
        bare = Path(name.replace('\\', '/')).name or '<name>'
        return (
            f"refused: {name!r} is not one plain directory name -- give the tree's bare name under the worktree "
            f'home: {door.format(bare)}'
        )
    trees = worktrees(root)
    if not trees:
        return f'refused: git cannot read the worktrees of {root} -- run from the repository or pass --root <checkout>'
    main = trees[0][0].resolve()
    return main, (main / home if home is not None else worktree_home(main)) / name


def scratch(root: Path, name: str, sha: str, *, home: Path | None = None) -> str:
    """Make a DETACHED tree ``<home>/<name>`` of *root*'s main checkout at *sha* and declare it DISPOSABLE.

    The throwaway comparison checkout (a base to diff tests against): its untracked and ignored content is scratch,
    so :func:`discard` removes it, and :func:`reclaim` once it is quiet, with no landing to wait for. One line:
    ``made ...`` or ``refused: ...``.
    """
    place = _scratch_path(root, name, home, '--scratch {} <sha>')
    if isinstance(place, str):
        return place
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
    if unwired := _wire(tree):
        return unwired
    return f'made     {tree}  [detached {commit[:12]}, disposable, hooks wired]'


def _wire(tree: Path) -> str:
    """Install *tree*'s hook shims; ``''`` when it is protected, else the ``FAILED`` line naming why."""
    try:
        install(tree)
    except (HookInstallError, subprocess.SubprocessError, OSError) as why:
        return f'FAILED   {tree} was made but its hooks are not wired: {why}'
    return ''


#: Seconds a lane's venv bootstrap may take: a cold one resolves and installs the whole lock.
BOOTSTRAP_TIMEOUT_S = 1800


def bootstrap(tree: Path) -> int:
    """The tree's own venv, through the family door: ``<this python> -m dev_lab.dev.dep --bootstrap <tree>``."""
    argv = [running_interpreter(), '-m', 'dev_lab.dev.dep', '--bootstrap', str(tree)]
    return 0 if _door.run(argv, cwd=tree, check=False, timeout=BOOTSTRAP_TIMEOUT_S).returncode == 0 else 1


def lane(
    root: Path, name: str, branch: str, base: str, *, home: Path | None = None, venv: Callable[[Path], int] = bootstrap
) -> str:
    """Make the lane ``<home>/<name>`` on a NEW *branch* cut from *base*, bootstrap its venv and wire its hooks.

    One line: ``made ...``, ``refused: ...`` (nothing made), or ``FAILED ...`` (the tree stands, named unwired).
    """
    place = _scratch_path(root, name, home, '--add {} <branch> <base>')
    if isinstance(place, str):
        return place
    main, tree = place
    if tree.exists():
        return f'refused: {tree} already exists'
    if git_out(main, 'worktree', 'add', '-b', branch, str(tree), base) is None:
        return f'refused: git worktree add -b {branch} {tree} {base} failed'
    if (exited := venv(tree)) != 0:
        return (
            f'FAILED   {tree} was made but its venv was not: the bootstrap exited {exited}; run '
            f'`{running_interpreter()} -m dev_lab.dev.dep --bootstrap {tree}` then '
            f'`{running_interpreter()} -m dev_lab.dev.hook_install --repo {tree} --install`'
        )
    return _wire(tree) or f'made     {tree}  [{branch} from {base}, venv bootstrapped, hooks wired]'


def discard(root: Path, name: str, *, home: Path | None = None, occupied: Callable[[Path], bool] | None = None) -> str:
    """Remove the DISPOSABLE tree ``<home>/<name>`` of *root*'s main checkout now; one line, ``removed`` or why not.

    Refused: a path that is not a registered linked worktree, a main checkout or repository
    (:func:`repository_at`), a tree :func:`scratch` did not declare, a locked one, one with a tracked change or a
    HEAD no ref holds, one any process works in, executes from or reads (:func:`occupancy`, the asker's own family
    included), and one holding run outputs (a writer defect). Submodule checkouts inside it go with it: git keeps
    their repositories in the tree's admin directory, which the prune removes.
    """
    place = _scratch_path(root, name, home, '--discard {}')
    if isinstance(place, str):
        return place
    locked = locked_trees(root)
    trees = worktrees(root)
    if locked is None or trees is None:
        return f'refused: git cannot read the worktrees of {root} -- run from the repository or pass --root <checkout>'
    main, tree = place[0], place[1].resolve()
    if tree not in {path.resolve() for path, _ in trees[1:]}:
        return f'refused: {tree} is not a linked worktree of {main}'
    base = disposable_base(tree)
    reason = (
        repository_at(main, tree)
        or (
            ''
            if base
            else f'not declared disposable -- only a tree made by --scratch is discarded; an ordinary or '
            f'detached tree holding nothing unlanded goes by: --remove {name}'
        )
        or ('locked (git worktree unlock first)' if tree in locked else '')
        or _scrap_unsaved(tree, base, declared_generated(main))
        or (_LIVE if (occupied or occupancy())(tree) else '')
    )
    if reason:
        return f'refused: {tree} ({reason})'
    if refused := _removed(tree):
        return refused.replace('{label}', str(tree))
    git_out(main, 'worktree', 'prune')
    return f'removed  {tree}'
