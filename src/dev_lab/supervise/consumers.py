"""WHO HOLDS A PRESSED DISK: the biggest directories under a declared path, each marked owned or not (D54).

Split from :mod:`dev_lab.supervise.pressure` (2026-11-03, the module-size band): pressure judges a disk, this
names what fills it. An owned tree (an :data:`OWNED` glob) is one the forge and the agents make and may clean;
any other is named and never touched. The walk is bounded (:data:`WALK_BUDGET`, one device), because it runs
when the disk is already pressed. Nothing here deletes.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = ['OWNED', 'TOP_CONSUMERS', 'WALK_BUDGET', 'Consumer', 'consumers', 'tree_bytes']

#: How many directory entries one reading's consumer walk may visit: a pressed disk is not walked whole.
WALK_BUDGET: Final = 200_000

#: How many consumers a disk alarm names.
TOP_CONSUMERS: Final = 5

#: The trees the forge and the agents make and may clean, as globs under a declared path (``*/`` one checkout
#: deeper too) -- a consumer matching one is marked ``owned``; any other is named and never touched.
OWNED: Final = (
    '.claude/worktrees/*',
    'output/logs/*',
    '.cache/act/*',
    '.cache/actcache/*',
    '_work/_temp/*',
    'ci/*',
)


@dataclass(frozen=True)
class Consumer:
    """One directory holding a pressed disk: its path AS READ FROM DISK (untrusted text), bytes, and ownership."""

    path: str
    bytes: int
    owned: bool


def tree_bytes(path: Path, budget: list[int], device: int) -> int:
    """The bytes under *path* on the DECLARED ROOT'S filesystem *device*, symlinks not followed, within *budget*.

    Bounded twice, because it runs when a disk is ALREADY pressed and on every tick while it stays so: it never
    descends into another mount (``/proc``, ``/sys``, another disk are not this disk), and it stops when the
    shared *budget* (:data:`WALK_BUDGET` entries per reading) is spent -- the sizes then read as lower bounds. An
    entry that cannot be read is skipped, never raised.
    """
    total, stack = 0, [path]
    while stack and budget[0] > 0:
        try:
            entries = list(os.scandir(stack.pop()))
        except OSError:
            continue
        for entry in entries:
            if budget[0] <= 0:
                break
            budget[0] -= 1
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            total += info.st_size
            if entry.is_dir(follow_symlinks=False) and info.st_dev == device:
                stack.append(Path(entry.path))
    return total


def _device(path: Path) -> int | None:
    try:
        return path.lstat().st_dev
    except OSError:
        return None


def consumers(
    roots: Sequence[Path], *, top: int = TOP_CONSUMERS, device: Callable[[Path], int | None] = _device
) -> tuple[Consumer, ...]:
    """The *top* directories under *roots* by bytes, each marked owned (an :data:`OWNED` glob) or not.

    An owned tree is named per child (one worktree, one log day), any other directory as one entry holding
    what is NOT owned under it -- so no byte is counted twice, and the agent sees what it may clean. A root
    that cannot be listed names nothing: the alarm stands without its consumers, never vanishes. A directory on
    ANOTHER device than its declared root (``/proc``, ``/sys``, ``/dev``, ``/run`` under ``/``) is not a consumer
    of this disk and is never walked.
    """
    seen: dict[Path, bool] = {}
    devices: dict[Path, int] = {}
    for root in roots:
        home = device(root)
        if home is None:
            continue
        try:
            for pattern in OWNED:
                for hit in (*root.glob(pattern), *root.glob(f'*/{pattern}')):
                    if hit.is_dir() and not hit.is_symlink() and device(hit) == home:
                        seen[hit], devices[hit] = True, home
            for child in sorted(root.iterdir()) if root.is_dir() else ():
                if child.is_dir() and not child.is_symlink() and device(child) == home and child not in seen:
                    seen[child], devices[child] = False, home
        except OSError:
            continue
    budget = [WALK_BUDGET]
    sizes = {p: tree_bytes(p, budget, devices[p]) for p in seen}
    rest = {p: n - sum(sizes[o] for o, mine in seen.items() if mine and p in o.parents) for p, n in sizes.items()}
    ranked = sorted(seen, key=lambda p: -rest[p])[:top]
    return tuple(Consumer(p.as_posix(), max(rest[p], 0), seen[p]) for p in ranked)
