"""A checkout's git dir and common dir, read off ``.git`` and ``commondir`` without starting git.

A hook pays for every process it starts (``HOOK-UNDER-FIVE-SECONDS``, user ruling D24): ``git rev-parse`` costs 60-300
ms on a loaded Windows workstation, and the answer is two small files away. A linked worktree's ``.git`` is a file
naming its own git dir (``gitdir: <path>``), whose ``commondir`` names the repository's shared one; a main checkout's
``.git`` is the directory itself. Anything unreadable answers ``None``, and the caller decides what that means.

THE WALK STOPS WHERE GIT'S DOES: at a directory named in ``GIT_CEILING_DIRECTORIES`` (git's own contract), so a
tree below a ceiling is outside any checkout here exactly as it is to ``git`` itself. One walk, :func:`ancestors`,
serves every reader.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

__all__ = ['CEILING', 'ancestors', 'checkout_of', 'common_dir', 'git_dir', 'run_owner', 'same_owner']

#: git's own variable naming the directories its discovery never climbs into.
CEILING = 'GIT_CEILING_DIRECTORIES'


def _ceilings() -> frozenset[str]:
    return frozenset(
        os.path.normcase(os.path.normpath(entry)) for entry in os.environ.get(CEILING, '').split(os.pathsep) if entry
    )


def ancestors(start: Path) -> Iterator[Path]:
    """*start* (absolute) and each parent, stopping before a ``GIT_CEILING_DIRECTORIES`` entry as git does."""
    at = Path(os.path.normpath(start.absolute()))
    ceilings = _ceilings()
    yield at
    for folder in at.parents:
        if os.path.normcase(str(folder)) in ceilings:
            return
        yield folder


def checkout_of(path: Path) -> Path | None:
    """The nearest directory at or above *path* holding a ``.git`` (a worktree's is a file); ``None`` outside one."""
    return next((folder for folder in ancestors(path) if (folder / '.git').exists()), None)


def git_dir(cwd: Path) -> Path | None:
    """The git dir of the checkout *cwd* lies in (a linked worktree's own), absolute; ``None`` outside one."""
    for folder in ancestors(cwd):
        dot = folder / '.git'
        if dot.is_dir():
            return dot
        if dot.is_file():
            try:
                line = dot.read_text(encoding='utf-8').strip()
            except OSError:
                return None
            return (folder / line.removeprefix('gitdir:').strip()).resolve() if line.startswith('gitdir:') else None
    return None


def common_dir(cwd: Path) -> Path | None:
    """The git dir every worktree of *cwd*'s repository shares; ``None`` outside a checkout."""
    own = git_dir(cwd)
    if own is None:
        return None
    pointer = own / 'commondir'
    try:
        return (own / pointer.read_text(encoding='utf-8').strip()).resolve() if pointer.is_file() else own
    except OSError:
        return None


def run_owner(root: Path | str) -> str:
    """The identity of a run's owner: its checkout's RESOLVED absolute path, never the bare worktree name.

    Two repos may each hold a worktree of the same name (``.claude/worktrees/<name>``); measured 2026-11-26, a
    queue labeled by that name let one repo's agent stop the other repo's pytest. The full path tells them apart.
    """
    return Path(root).resolve().as_posix()


def same_owner(one: Path | str, other: Path | str) -> bool:
    """Whether *one* and *other* name the same checkout (resolved, case-normalized as the filesystem compares)."""
    return os.path.normcase(run_owner(one)) == os.path.normcase(run_owner(other))
