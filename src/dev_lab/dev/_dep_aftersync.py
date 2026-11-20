"""What a successful environment change does next, in order: migrate the box ledger, then refresh auto-mode.

LEDGER-MIGRATES-ON-INSTALL runs before anything in the new environment opens the ledger; the auto-mode prose is
rendered in its own process so this door imports nothing of the forge it does not need.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

from dev_lab.dev._dep_network import CHILD_WALL_S
from dev_lab.dev.boxmigrate import migrate as migrate_box

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

__all__ = ['after_sync', 'refresh_automode', 'retire_anchors']


def after_sync(root: Path, python: str, *, run: Callable[..., Any]) -> int:
    """Migrate the box ledger *python*'s environment holds, refresh *root*'s auto-mode; the migration's exit code."""
    migrated = migrate_box(python, run=run)
    refresh_automode(root, run=run)
    return migrated


def refresh_automode(root: Path, *, run: Callable[..., Any]) -> None:
    """Render the checkout's machine-local auto-mode prose (:mod:`dev_lab.dev.automode`), in its own process.

    It always exits 0 and prints why it wrote nothing when a fleet source is unreadable here, so it never fails
    the sync.
    """
    run(
        [sys.executable, '-m', 'dev_lab.dev.automode', 'write', '--repo', str(root)],
        check=False,
        timeout=CHILD_WALL_S,
        cwd=root,
    )


def retire_anchors(paths: Sequence[Path]) -> tuple[str, ...]:
    """H2, REMEDIED. Delete every anchor that exists, and return what was retired.

    DELETED rather than rewritten to FAIL: a missing anchor cannot be mistaken for a verdict about
    anything, whereas a synthetic FAIL line would put on record a result that no run produced.
    """
    retired = [path for path in paths if path.exists()]
    for path in retired:
        path.unlink()
    return tuple(str(path) for path in retired)
