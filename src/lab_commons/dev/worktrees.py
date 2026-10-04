"""The LOCAL WORKTREE CLEANUP DOOR: ``python -m lab_commons.dev.worktrees [--root R] [--prune]``.

User rulings 2026-10-04 (AUTO-MODE-RUNS-THE-DOORS): local cleanup is a checked door an agent may run
unattended, nothing here pushes or touches origin, and a worktree is removed ONLY when it is CLEAN --
nothing modified, staged or untracked (``git status --porcelain`` empty). Work is committed or cleared
by a human first; this door never moves work aside to make a tree removable.

THE INCIDENT IT ENCODES (a consumer, 2026-10-04): a cleanup loop ran ``mkdir -p "$D" && mv output "$D"``
and then ``; git worktree remove --force``. The archive helper failed, ``mv`` never ran, and the ``;``
let the removal delete five worktrees' ignored ``output/``. So:

* a registered worktree is PRUNED only when it is clean, its HEAD is contained in a remote-tracking
  branch, and it holds no ignored content beyond regenerable caches (:data:`DISPOSABLE`) -- an
  ignored ``output/`` BLOCKS it and is listed. Removal is ``git worktree remove`` WITHOUT ``--force``.
* a directory under ``.claude/worktrees/`` that git does not register is the ONE automatic move: an
  EMPTY one (no files at any depth) is moved into the dated archive and verified gone; one that holds
  files is listed with them and refused.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path, PurePosixPath
from typing import Final

from lab_commons.dev.checkout import git_out, orphan_directories, worktrees
from lab_commons.dev.datedlog import dated_log
from lab_commons.log import emit

__all__ = ['ARCHIVE_BASE', 'DISPOSABLE', 'archive_dir', 'blockers', 'main', 'prune']

#: Ignored entries that are regenerated on demand and may go with their tree.
DISPOSABLE: Final = frozenset(
    {'__pycache__', '.pytest_cache', '.ruff_cache', '.mypy_cache', '.venv', 'node_modules', '.verify'}
)

#: Where an archived unregistered directory lands, under the checkout's dated output tree.
ARCHIVE_BASE: Final = 'output/logs'

_SHOWN: Final = 5


def archive_dir(root: Path, name: str) -> Path:
    """``<root>/output/logs/<yy>/<mm>/<dd>/worktree-archive/<name>`` (parent created, path NOT yet)."""
    return dated_log(root, name, base=ARCHIVE_BASE, kind='worktree-archive')


def blockers(tree: Path) -> tuple[str, ...] | None:
    """Every path that stops *tree* from being removed: modified, staged, untracked, or kept-ignored."""
    out = git_out(tree, 'status', '--porcelain', '--ignored=matching')
    if out is None:
        return None
    found: list[str] = []
    for line in out.splitlines():
        code, path = line[:2], line[3:].strip().rstrip('/')
        if code == '!!' and set(PurePosixPath(path).parts) & DISPOSABLE:
            continue
        found.append(f'{code.strip() or "?"} {path}')
    return tuple(found)


def _files(directory: Path) -> list[str]:
    return sorted(str(p.relative_to(directory)) for p in directory.rglob('*') if not p.is_dir())


def _shown(paths: tuple[str, ...] | list[str]) -> str:
    more = f' (+{len(paths) - _SHOWN} more)' if len(paths) > _SHOWN else ''
    return ', '.join(paths[:_SHOWN]) + more


def _tree_line(root: Path, path: Path, branch: str, *, apply: bool) -> str:
    blocking = blockers(path)
    if blocking is None:
        return f'kept     {path}  [{branch}]  (unreadable)'
    if blocking:
        return f'kept     {path}  [{branch}]  (not clean -- commit or clear first: {_shown(blocking)})'
    if not (git_out(path, 'branch', '-r', '--contains', 'HEAD') or '').strip():
        return f'kept     {path}  [{branch}]  (HEAD is on no remote branch)'
    if not apply:
        return f'prunable {path}  [{branch}]'
    removed = git_out(root, 'worktree', 'remove', str(path)) is not None
    return f'{"removed " if removed else "FAILED  "} {path}  [{branch}]'


def _orphan_line(root: Path, orphan: Path, *, apply: bool) -> str:
    files = _files(orphan)
    if files:
        return f'kept     {orphan}  (unregistered, holds files -- a human decides: {_shown(files)})'
    if not apply:
        return f'orphan   {orphan}  (unregistered and empty; --prune archives it)'
    target = archive_dir(root, orphan.name)
    if target.exists():
        return f'FAILED   {orphan}  (archive target {target} already exists)'
    shutil.move(str(orphan), str(target))
    moved = target.exists() and not orphan.exists()
    return f'{"archived" if moved else "FAILED  "} {orphan} -> {target}'


def prune(root: Path, *, apply: bool) -> tuple[str, ...] | None:
    """One line per non-main worktree and orphan directory; with *apply*, act. ``None``: unreadable."""
    trees = worktrees(root)
    orphans = orphan_directories(root)
    if trees is None or orphans is None:
        return None
    out = [_tree_line(root, path, branch, apply=apply) for path, branch in trees[1:]]
    out += [_orphan_line(root, orphan, apply=apply) for orphan in orphans]
    if apply:
        git_out(root, 'worktree', 'prune')
    return tuple(out)


def main(argv: list[str] | None = None) -> int:
    """List worktrees and leftovers; ``--prune`` removes the clean ones. Exit 1 on a failure, 2 when unread."""
    parser = argparse.ArgumentParser(prog='python -m lab_commons.dev.worktrees', description=main.__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--prune', action='store_true', help='remove CLEAN worktrees; never --force, never origin')
    args = parser.parse_args(argv)
    lines = prune(args.root.resolve(), apply=args.prune)
    if lines is None:
        emit(f'git could not read the worktrees of {args.root}; nothing was touched')
        return 2
    for line in lines:
        emit(line)
    return 1 if any(line.startswith('FAILED') for line in lines) else 0


if __name__ == '__main__':
    raise SystemExit(main())
