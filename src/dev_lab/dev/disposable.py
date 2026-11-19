"""The DISPOSABLE declaration of a throwaway worktree.

Read by :mod:`dev_lab.dev.reclaim` and written by :mod:`dev_lab.dev.scratchtree`: a leaf both import.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from dev_lab.dev.checkout import git_out

__all__ = ['DISPOSABLE', 'disposable_base', 'marker', 'unheld_head']


#: The file in a linked tree's OWN git admin directory that declares it DISPOSABLE; it holds the sha it was made at.
DISPOSABLE: Final = 'dev-lab-disposable'


def marker(tree: Path) -> Path | None:
    """*tree*'s :data:`DISPOSABLE` path inside its own admin directory; ``None`` when git cannot say."""
    path = (git_out(tree, 'rev-parse', '--path-format=absolute', '--git-path', DISPOSABLE) or '').strip()
    return Path(path) if path else None


def disposable_base(tree: Path) -> str:
    """The sha *tree* was made at when declared DISPOSABLE (:mod:`dev_lab.dev.scratchtree`); ``''`` when not.

    The declaration lives in git's per-worktree admin directory, so it is born with the registration and goes with
    its prune: there is no second registry to drift from ``git worktree list``.
    """
    path = marker(tree) if (tree / '.git').is_file() else None
    try:
        return path.read_text(encoding='utf-8').strip() if path and path.is_file() else ''
    except OSError:
        return ''


def unheld_head(tree: Path, base: str) -> str:
    """Why *tree*'s HEAD is unsaved: not its *base* and held by no ref; ``''`` when it is either."""
    head = (git_out(tree, 'rev-parse', 'HEAD') or '').strip()
    if head == base or (git_out(tree, 'for-each-ref', '--count=1', '--contains', 'HEAD') or '').strip():
        return ''
    return f'HEAD {head[:12]} is a commit no ref holds -- branch it (git branch <name>) first'
