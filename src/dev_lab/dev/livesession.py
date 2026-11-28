"""LIVE SESSION: a worktree is live while its HEAD moves -- judged by what a read can never write.

Issue dev-lab#1125 (2026-11-28): the guard read the index mtime, and ``git status`` refreshes the index stat
cache, so the reading session itself made a tree look live. A commit, checkout, reset or rebase writes ``HEAD``
or its reflog ``logs/HEAD``; nothing read-only does. Split from :mod:`dev_lab.dev.reclaim`, which, with
:mod:`dev_lab.dev.branchfate` and :mod:`dev_lab.dev.worktrees`, judges a tree by it.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Final

from dev_lab.dev.checkout import git_out

__all__ = ['LIVE_SESSION', 'live_session', 'moved_age_s']

#: The stable head of a live-session refusal: the key a summary counts it under.
LIVE_SESSION: Final = 'live session'


def moved_age_s(tree: Path) -> float | None:
    """Seconds since *tree*'s HEAD last moved; ``None`` when it has none to read.

    A commit, checkout, reset or rebase writes the tree's ``HEAD`` or its reflog ``logs/HEAD``; a READ never does.
    Issue dev-lab#1125 (2026-11-28): liveness was the index mtime, and ``git status`` refreshes the index stat
    cache, so a session merely reading a tree looked live. A session that only stages is held by its process
    instead (:func:`dev_lab.dev.reclaim.occupancy`, the REMOVAL lock).
    """
    out = git_out(tree, 'rev-parse', '--path-format=absolute', '--git-path', 'HEAD', '--git-path', 'logs/HEAD')
    stamps: list[float] = []
    for line in (out or '').splitlines():
        try:
            stamps.append(Path(line.strip()).stat().st_mtime)
        except OSError:
            continue
    return time.time() - max(stamps) if stamps else None


def live_session(tree: Path, quiet_s: float) -> str:
    """Why *tree* is a LIVE SESSION -- its HEAD moved within *quiet_s* -- with the wait left; ``''`` when quiet."""
    age = moved_age_s(tree)
    if age is None or age >= quiet_s:
        return ''
    return (
        f'{LIVE_SESSION}: its HEAD moved {age / 60:.0f} min ago; re-run once it has been quiet '
        f'{quiet_s / 60:g} min (about {(quiet_s - age) / 60:.0f} min left)'
    )
