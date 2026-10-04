"""The LOCAL WORKTREE CLEANUP DOOR: ``python -m lab_commons.dev.worktrees [--root R] [--prune]``.

User ruling 2026-10-04 (AUTO-MODE-RUNS-THE-DOORS): local cleanup is a checked door an agent may run
unattended; nothing here pushes or touches origin.

THE INCIDENT IT ENCODES (consumer-a, 2026-10-04): a cleanup loop ran ``mkdir -p "$D" && mv output "$D"``
and then ``; git worktree remove --force``. The archive helper failed, ``mv`` never ran, and the ``;``
let the removal delete five worktrees' ignored ``output/``. So every destructive step here runs only
AFTER its precondition is VERIFIED (target exists, source gone), and removal is ``git worktree remove``
WITHOUT ``--force`` -- git itself refuses a tree with modified or untracked files.

A registered worktree is PRUNED when it is clean and its HEAD is contained in a remote-tracking branch;
first, every ignored entry that is not a regenerable cache (:data:`DISPOSABLE`) -- ``output/`` above
all -- is MOVED into the dated archive. A directory under ``.claude/worktrees/`` that git does not
register is moved into the archive whole. Everything else is LISTED with the reason it was kept.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path, PurePosixPath
from typing import Final

from lab_commons.dev.checkout import git_out, orphan_directories, worktrees
from lab_commons.dev.datedlog import dated_log
from lab_commons.log import emit

__all__ = ['ARCHIVE_BASE', 'DISPOSABLE', 'archive_dir', 'main', 'prune']

#: Ignored entries that are regenerated on demand and may go with their tree.
DISPOSABLE: Final = frozenset(
    {'__pycache__', '.pytest_cache', '.ruff_cache', '.mypy_cache', '.venv', 'node_modules', '.verify'}
)

#: Where archived content lands, under the checkout's dated output tree.
ARCHIVE_BASE: Final = 'output/logs'


def archive_dir(root: Path, name: str) -> Path:
    """``<root>/output/logs/<yy>/<mm>/<dd>/worktree-archive/<name>`` (parent created, path NOT yet)."""
    return dated_log(root, name, base=ARCHIVE_BASE, kind='worktree-archive')


def _move_verified(source: Path, target: Path) -> bool:
    """Move *source* to *target*; True only when the target exists AND the source is gone."""
    if target.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(source), str(target))
    except OSError:
        return False
    return target.exists() and not source.exists()


def _kept_ignored(tree: Path) -> tuple[str, ...] | None:
    out = git_out(tree, 'status', '--porcelain', '--ignored=matching')
    if out is None:
        return None
    entries = [line[3:].strip().rstrip('/') for line in out.splitlines() if line.startswith('!! ')]
    return tuple(e for e in entries if not set(PurePosixPath(e).parts) & DISPOSABLE)


def _why_kept(tree: Path) -> str | None:
    status = git_out(tree, 'status', '--porcelain')
    if status is None:
        return 'unreadable'
    if status.strip():
        return 'modified or untracked files'
    holders = git_out(tree, 'branch', '-r', '--contains', 'HEAD')
    if not (holders or '').strip():
        return 'HEAD is on no remote branch'
    return None


def prune(root: Path, *, apply: bool) -> tuple[str, ...] | None:
    """One line per non-main worktree and orphan directory; with *apply*, act. ``None``: unreadable."""
    trees = worktrees(root)
    orphans = orphan_directories(root)
    if trees is None or orphans is None:
        return None
    out: list[str] = []
    for path, branch in trees[1:]:
        why = _why_kept(path)
        if why is not None:
            out.append(f'kept     {path}  [{branch}]  ({why})')
            continue
        if not apply:
            out.append(f'prunable {path}  [{branch}]')
            continue
        keep = _kept_ignored(path)
        moved = keep is not None and all(
            _move_verified(path / entry, archive_dir(root, path.name) / entry) for entry in keep
        )
        if not moved:
            out.append(f'FAILED   {path}  (archiving ignored content failed; tree left in place)')
            continue
        removed = git_out(root, 'worktree', 'remove', str(path)) is not None
        out.append(f'{"removed " if removed else "FAILED  "} {path}  [{branch}]  archived={list(keep or ())}')
    for orphan in orphans:
        if not apply:
            out.append(f'orphan   {orphan}  (unregistered; --prune archives it)')
            continue
        target = archive_dir(root, orphan.name)
        out.append(f'{"archived" if _move_verified(orphan, target) else "FAILED  "} {orphan} -> {target}')
    if apply:
        git_out(root, 'worktree', 'prune')
    return tuple(out)


def main(argv: list[str] | None = None) -> int:
    """List worktrees and leftovers; ``--prune`` removes the safe ones. Exit 1 on a failure, 2 when unread."""
    parser = argparse.ArgumentParser(prog='python -m lab_commons.dev.worktrees', description=main.__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--prune', action='store_true', help='archive-then-remove; never --force, never origin')
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
