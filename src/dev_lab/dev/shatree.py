"""A LOCAL PART IS JUDGED IN A TREE AT THE CLAIMED SHA -- one the producer builds, runs in, and removes.

THE DEFECT (live 2026-10-12, integrate/main 4e394b6). A workstation's ``forge serve`` ran ``verify``
in the checkout it serves from -- the integrator's MAIN checkout, which sat at e9bc0d4. Verify judged
THAT tree and posted on THAT sha, and the claim on 4e394b6 was released with no part. A producer that
judges whatever its serving checkout holds judges the wrong commit whenever the two differ.

THE CLUSTER'S RULE, LOCALLY. A cluster run is judged in ``~/ci/trees/<sha>``, a detached worktree of
that one commit with its submodules at their pinned commits (:mod:`lab_commons.hpc.run`). A local
part is judged the same way: :func:`open_tree` adds ``<main checkout>/.claude/worktrees/forge-<sha12>-<context>``
(:data:`~dev_lab.dev.worktreeplace.WORKTREES_REL` -- a tree stays inside its repository), detached
at the claimed sha, and bootstraps its OWN environment through the dependency door
(``python -m dev_lab.dev.dep --bootstrap <tree>``: the commit's own lock and declared extras).
The producer's argv runs there with that tree's interpreter; :func:`close_tree` removes the tree after
the part is posted. The serving checkout's HEAD therefore decides nothing about what is judged.

WHAT SURVIVES THE TREE. The outbox and the run cache resolve through git's common directory to the
MAIN checkout (:mod:`dev_lab.dev.forgeoutbox`, :mod:`dev_lab.dev.runcache`), so a post queued
before its commit reached origin outlives the tree. THE RUN RECORD DOES TOO, and :func:`close_tree` is
what guarantees it (defect live 2026-10-12, dd30117: the windows part's record was written inside the
tree and removed with it, so nothing on this box could say why the part was red). Before removing the
tree it copies the tree's ``<output>/<yy>/<mm>/<dd>/parts/<sha>/`` and the producer's streamed output
(``produce-<utc>.log``) into the SAME place in the SERVING checkout -- where the cluster keeps its own.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import lab_commons.launch as _door

from dev_lab.dev.diskusage import remove_tree
from dev_lab.dev.forge import _GIT
from dev_lab.dev.platformparts import UndeclaredPart, record_directory
from dev_lab.dev.venvpath import checkout_interpreter, current_os_name
from dev_lab.dev.worktreeplace import WORKTREES_REL, main_checkout

__all__ = [
    'TREE_PREFIX',
    'Tree',
    'TreeFailed',
    'close_tree',
    'keep_record',
    'open_tree',
    'record_manifest',
    'tree_path',
]

#: A producer's tree is ``forge-<sha12>-<context>`` under the main checkout's worktrees: ONE PER JOB, so two
#: jobs of one sha (a part and a request, two requests) each own a tree and run side by side.
TREE_PREFIX: Final = 'forge-'

_SHA_SHOWN: Final = 12


class TreeFailed(RuntimeError):
    """The tree at the claimed sha could not be built: no part, and the message says which step refused."""


@dataclass(frozen=True)
class Tree:
    """A producer's tree at one sha and the interpreter of its own environment."""

    path: Path
    python: Path


def tree_path(root: Path, sha: str, context: str) -> Path:
    """Where the tree of job *context* at *sha* lives: ``<main checkout>/.claude/worktrees/forge-<sha12>-<context>``."""
    slug = context.replace('/', '-')
    return main_checkout(root) / WORKTREES_REL / f'{TREE_PREFIX}{sha[:_SHA_SHOWN]}-{slug}'


def _step(run: Callable[..., Any], argv: list[str], what: str) -> None:
    done = run(argv, capture_output=True, text=True, encoding='utf-8', errors='replace', check=False)
    if done.returncode:
        tail = (done.stdout or '').strip().splitlines()[-3:] + (done.stderr or '').strip().splitlines()[-3:]
        msg = f'{what} exited {done.returncode}: {" | ".join(tail) or "no output"}'
        raise TreeFailed(msg)


def open_tree(
    root: Path, sha: str, context: str, *, run: Callable[..., Any] = _door.run, python: str = sys.executable
) -> Tree:
    """Add (or reuse) the detached tree of *sha*, its submodules, and its own environment.

    Raises:
        TreeFailed: a step refused; the message names it and the tail of its output.

    """
    tree = tree_path(root, sha, context)
    if not (tree / '.git').exists():  # debris of an earlier run (half removed, still registered) blocks the add
        remove_tree(tree)
        _step(run, [_GIT, '-C', str(root), 'worktree', 'prune'], 'git worktree prune')
        # a tree nested under the serving checkout adds its own prefix to every tracked path: past MAX_PATH the add
        # exits 128 though the commit is fine (downstream #392), so the tree, not the repo's config, takes long paths
        add = [_GIT, '-C', str(root), '-c', 'core.longpaths=true', 'worktree', 'add', '--detach', str(tree), sha]
        _step(run, add, 'git worktree add')
    # A commit's tree INCLUDES its submodules at their pinned commits: `dep --bootstrap` initialises them first,
    # through the network door and with a local-path submodule's transport opened (_dep_network.init_submodules).
    _step(run, [python, '-m', 'dev_lab.dev.dep', '--bootstrap', str(tree)], 'dep --bootstrap')
    try:
        return Tree(tree, checkout_interpreter(tree, os_name=current_os_name()))
    except FileNotFoundError as missing:
        raise TreeFailed(str(missing)) from None


def record_manifest(root: Path, sha: str, context: str) -> tuple[str, tuple[tuple[str, str], ...]]:
    """Where *sha*'s record is kept in *root* (posix, relative) and ``(name, sha256)`` of each file its tree made.

    What a request's requester is told before the tree is removed: the record path on the serving host and a
    checksum per file, so a copy fetched later is verified. ``('', ())`` when the tree declares no record.
    """
    tree = tree_path(root, sha, context)
    try:
        judged = record_directory(tree, sha)
    except (UndeclaredPart, FileNotFoundError):
        return '', ()
    made = sorted(one for one in judged.parents[4].glob(f'*/*/*/parts/{sha}/*') if one.is_file())
    sums = tuple((one.name, hashlib.sha256(one.read_bytes()).hexdigest()) for one in made)
    return judged.relative_to(tree).as_posix(), sums


def keep_record(root: Path, sha: str, context: str, *, log: str) -> str:
    """Copy the tree's ``parts/<sha>/`` and *log* to the same place in *root*; one line says what happened."""
    tree = tree_path(root, sha, context)
    try:
        judged = record_directory(tree, sha)
    except UndeclaredPart as why:
        return f'record NOT kept: {why}'
    except FileNotFoundError:
        return 'record NOT kept: the tree has no pyproject.toml to declare [tool.dev_lab.parts] output'
    kept = root / judged.relative_to(tree)
    kept.mkdir(parents=True, exist_ok=True)
    base = judged.parents[4]  # <output>, above <yy>/<mm>/<dd>/parts/<sha>
    for made in base.glob(f'*/*/*/parts/{sha}/*'):  # a run may cross midnight
        if made.is_file():
            shutil.copy2(made, kept / made.name)
    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
    (kept / f'produce-{stamp}.log').write_text(log, encoding='utf-8')
    return f'record kept in {kept.relative_to(root).as_posix()}'


def close_tree(root: Path, sha: str, context: str, *, log: str = '', run: Callable[..., Any] = _door.run) -> str:
    """Keep the run record of *sha* in *root*, then remove its tree (:func:`~dev_lab.dev.diskusage.remove_tree`).

    *log* is the producer's streamed output; it is kept beside the record. One line says what happened.
    """
    tree = tree_path(root, sha, context)
    if not tree.exists():
        return f'tree {tree.name}: none to remove'
    kept = keep_record(root, sha, context, log=log)
    try:  # the contents first, long-path safe; then git forgets the tree (a `worktree remove` hits MAX_PATH)
        remove_tree(tree)
    except OSError as why:
        return f'tree {tree.name}: NOT removed ({why}); remove it by hand; {kept}'
    done = run(
        [_GIT, '-C', str(root), 'worktree', 'prune'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=False,
    )
    if done.returncode:
        why = (done.stderr or '').strip() or done.returncode
        return f'tree {tree.name}: removed, NOT pruned ({why}); {kept}'
    return f'tree {tree.name}: removed; {kept}'
