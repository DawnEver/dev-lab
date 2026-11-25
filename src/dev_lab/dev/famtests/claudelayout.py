"""CLAUDE-DIR-IS-CLOSED, as the body every consumer runs: `.claude/` only at the root, every entry declared.

The list and the walk live in :mod:`dev_lab.dev.claudelayout`; this body turns a non-empty answer into a red
naming every stray, retired ones with their reason.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dev_lab.dev.claudelayout import stray_entries

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['assert_claude_layout_is_closed']


def assert_claude_layout_is_closed(*, root: Path) -> None:
    """Every entry of *root*'s `.claude/` is in the closed inventory, and no `.claude/` sits below the root."""
    strays = stray_entries(root)
    if strays:
        msg = (
            'CLAUDE-DIR-IS-CLOSED: `.claude/` holds only dev_lab.dev.claudelayout.CLAUDE_ENTRIES, at the root only. '
            'Remove each stray (a retired one names where its content went):\n  ' + '\n  '.join(strays)
        )
        raise AssertionError(msg)
