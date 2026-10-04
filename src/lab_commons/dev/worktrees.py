"""The LOCAL WORKTREE CLEANUP DOOR: ``python -m lab_commons.dev.worktrees [--root R] [--prune]``.

User rulings 2026-10-04 (AUTO-MODE-RUNS-THE-DOORS): local cleanup is a checked door an agent may run
unattended, nothing here pushes or touches origin, and a worktree is removed ONLY when it is CLEAN --
nothing modified, staged or untracked (``git status --porcelain`` empty). Work is committed or cleared
by a human first; this door never moves work aside to make a tree removable.

THE INCIDENT IT ENCODES (a consumer, 2026-10-04): a cleanup loop ran ``mkdir -p "$D" && mv output "$D"``
and then ``; git worktree remove --force``. The archive helper failed, ``mv`` never ran, and the ``;``
let the removal delete five worktrees' ignored ``output/``. So:

* a registered worktree is PRUNED only when it is clean, its HEAD is contained in a remote-tracking
  branch, and every ignored path in it is REGENERABLE (:func:`regenerable`) -- an ignored
  ``output/`` is work, BLOCKS it and is listed. Removal is ``git worktree remove`` WITHOUT ``--force``.
* a directory under ``.claude/worktrees/`` that git does not register is never moved: an EMPTY one
  (no files at any depth) is removed in place, bottom-up with ``Path.rmdir``, which itself refuses a
  directory that is not empty; one that holds files is listed with them and refused.
"""

from __future__ import annotations

import argparse
import tomllib
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Final

from lab_commons.dev.checkout import git_out, orphan_directories, worktrees
from lab_commons.log import emit

__all__ = ['REGENERABLE', 'blockers', 'main', 'prune', 'regenerable']

#: THE family default: ignored path parts (``fnmatch`` patterns) a build or a tool regenerates on
#: demand, so they may go with their tree. A repo adds its own in ``[tool.lab_commons.worktrees]
#: regenerable`` of its ``pyproject.toml``; anything ignored and not matched is WORK and blocks.
REGENERABLE: Final = frozenset(
    {
        '__pycache__',
        '.pytest_cache',
        '.ruff_cache',
        '.mypy_cache',
        '.venv',
        'node_modules',
        '.verify',
        '*.egg-info',
        '*.py[cod]',
        '.coverage*',
        'htmlcov',
        'build',
        'dist',
        'target',
        '__version__.py',
    }
)

_SHOWN: Final = 5


def regenerable(tree: Path) -> frozenset[str]:
    """:data:`REGENERABLE` plus *tree*'s declared ``[tool.lab_commons.worktrees] regenerable``."""
    manifest = tree / 'pyproject.toml'
    if not manifest.is_file():
        return REGENERABLE
    with manifest.open('rb') as handle:
        declared = tomllib.load(handle).get('tool', {}).get('lab_commons', {}).get('worktrees', {})
    extra = declared.get('regenerable', [])
    if not isinstance(extra, list) or not all(isinstance(item, str) for item in extra):
        msg = f'[tool.lab_commons.worktrees] regenerable in {manifest} must be a list of strings, got {extra!r}'
        raise ValueError(msg)
    return REGENERABLE | frozenset(extra)


def _is_regenerable(path: str, patterns: frozenset[str]) -> bool:
    return any(fnmatch(part, pattern) for part in PurePosixPath(path).parts for pattern in patterns)


def blockers(tree: Path) -> tuple[str, ...] | None:
    """Every path that stops *tree* from being removed: modified, staged, untracked, or ignored work."""
    out = git_out(tree, 'status', '--porcelain', '--ignored=matching')
    if out is None:
        return None
    patterns = regenerable(tree)
    found: list[str] = []
    for line in out.splitlines():
        code, path = line[:2], line[3:].strip().rstrip('/')
        if code == '!!' and _is_regenerable(path, patterns):
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


def _orphan_line(orphan: Path, *, apply: bool) -> str:
    files = _files(orphan)
    if files:
        return f'kept     {orphan}  (unregistered, holds files -- a human decides: {_shown(files)})'
    if not apply:
        return f'orphan   {orphan}  (unregistered and empty; --prune removes it)'
    try:
        for directory in sorted(orphan.rglob('*'), key=lambda p: len(p.parts), reverse=True):
            directory.rmdir()
        orphan.rmdir()
    except OSError as error:
        return f'FAILED   {orphan}  ({error})'
    return f'removed  {orphan}  (unregistered and empty)'


def prune(root: Path, *, apply: bool) -> tuple[str, ...] | None:
    """One line per non-main worktree and orphan directory; with *apply*, act. ``None``: unreadable."""
    trees = worktrees(root)
    orphans = orphan_directories(root)
    if trees is None or orphans is None:
        return None
    out = [_tree_line(root, path, branch, apply=apply) for path, branch in trees[1:]]
    out += [_orphan_line(orphan, apply=apply) for orphan in orphans]
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
