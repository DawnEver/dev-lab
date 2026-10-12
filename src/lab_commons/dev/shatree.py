"""A LOCAL PART IS JUDGED IN A TREE AT THE CLAIMED SHA -- one the producer builds, runs in, and removes.

THE DEFECT (live 2026-10-12, integrate/main 4e394b6). A workstation's ``forge serve`` ran ``verify``
in the checkout it serves from -- the integrator's MAIN checkout, which sat at e9bc0d4. Verify judged
THAT tree and posted on THAT sha, and the claim on 4e394b6 was released with no part. A producer that
judges whatever its serving checkout holds judges the wrong commit whenever the two differ.

THE CLUSTER'S RULE, LOCALLY. A cluster run is judged in ``~/ci/trees/<sha>``, a detached worktree of
that one commit with its submodules at their pinned commits (:mod:`lab_commons.hpc.run`). A local
part is judged the same way: :func:`open_tree` adds ``<main checkout>/.claude/worktrees/forge-<sha12>``
(:data:`~lab_commons.dev.worktreeplace.WORKTREES_REL` -- a tree stays inside its repository), detached
at the claimed sha, and bootstraps its OWN environment through the dependency door
(``python -m lab_commons.dev.dep --bootstrap <tree>``: the commit's own lock and declared extras).
The producer's argv runs there with that tree's interpreter; :func:`close_tree` removes the tree after
the part is posted. The serving checkout's HEAD therefore decides nothing about what is judged.

WHAT SURVIVES THE TREE. The outbox and the run cache resolve through git's common directory to the
MAIN checkout (:mod:`lab_commons.dev.forgeoutbox`, :mod:`lab_commons.dev.runcache`), so a post queued
before its commit reached origin, and the record copied beside it, outlive the tree.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from lab_commons.dev.forge import _GIT
from lab_commons.dev.venvpath import checkout_interpreter, current_os_name
from lab_commons.dev.worktreeplace import WORKTREES_REL, main_checkout

__all__ = ['TREE_PREFIX', 'Tree', 'TreeFailed', 'close_tree', 'open_tree', 'tree_path']

#: A producer's tree is ``forge-<sha12>`` under the main checkout's worktrees.
TREE_PREFIX: Final = 'forge-'

_SHA_SHOWN: Final = 12


class TreeFailed(RuntimeError):
    """The tree at the claimed sha could not be built: no part, and the message says which step refused."""


@dataclass(frozen=True)
class Tree:
    """A producer's tree at one sha and the interpreter of its own environment."""

    path: Path
    python: Path


def tree_path(root: Path, sha: str) -> Path:
    """Where the tree of *sha* lives: ``<main checkout of root>/.claude/worktrees/forge-<sha12>``."""
    return main_checkout(root) / WORKTREES_REL / f'{TREE_PREFIX}{sha[:_SHA_SHOWN]}'


def _step(run: Callable[..., Any], argv: list[str], what: str) -> None:
    done = run(argv, capture_output=True, text=True, encoding='utf-8', errors='replace', check=False)
    if done.returncode:
        tail = (done.stdout or '').strip().splitlines()[-3:] + (done.stderr or '').strip().splitlines()[-3:]
        msg = f'{what} exited {done.returncode}: {" | ".join(tail) or "no output"}'
        raise TreeFailed(msg)


def open_tree(root: Path, sha: str, *, run: Callable[..., Any] = subprocess.run, python: str = sys.executable) -> Tree:
    """Add (or reuse) the detached tree of *sha*, its submodules, and its own environment.

    Raises:
        TreeFailed: a step refused; the message names it and the tail of its output.

    """
    tree = tree_path(root, sha)
    if not (tree / '.git').exists():
        _step(run, [_GIT, '-C', str(root), 'worktree', 'add', '--detach', str(tree), sha], 'git worktree add')
    if (tree / '.gitmodules').is_file():  # a commit's tree INCLUDES its submodules at their pinned commits
        _step(run, [_GIT, '-C', str(tree), 'submodule', 'update', '-q', '--init', '--recursive'], 'submodules')
    _step(run, [python, '-m', 'lab_commons.dev.dep', '--bootstrap', str(tree)], 'dep --bootstrap')
    try:
        return Tree(tree, checkout_interpreter(tree, os_name=current_os_name()))
    except FileNotFoundError as missing:
        raise TreeFailed(str(missing)) from None


def close_tree(root: Path, sha: str, *, run: Callable[..., Any] = subprocess.run) -> str:
    """Remove the tree of *sha* (it is the producer's own, so ``--force``); one line says what happened."""
    tree = tree_path(root, sha)
    if not tree.exists():
        return f'tree {tree.name}: none to remove'
    done = run(
        [_GIT, '-C', str(root), 'worktree', 'remove', '--force', str(tree)],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=False,
    )
    if done.returncode:
        return f'tree {tree.name}: NOT removed ({(done.stderr or "").strip() or done.returncode}); remove it by hand'
    return f'tree {tree.name}: removed'
