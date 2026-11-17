"""A checkout's git dir and common dir, read off ``.git`` and ``commondir`` without starting git.

A hook pays for every process it starts (``HOOK-UNDER-FIVE-SECONDS``, user ruling D24): ``git rev-parse`` costs 60-300
ms on a loaded Windows workstation, and the answer is two small files away. A linked worktree's ``.git`` is a file
naming its own git dir (``gitdir: <path>``), whose ``commondir`` names the repository's shared one; a main checkout's
``.git`` is the directory itself. Anything unreadable answers ``None``, and the caller decides what that means.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ['common_dir', 'git_dir']


def git_dir(cwd: Path) -> Path | None:
    """The git dir of the checkout *cwd* lies in (a linked worktree's own), absolute; ``None`` outside one."""
    for folder in (cwd.absolute(), *cwd.absolute().parents):
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
