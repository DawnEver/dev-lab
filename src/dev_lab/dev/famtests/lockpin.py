"""PIN, as the assertion every consumer runs over its own checkout -- judged on the forge, never at a local push.

User ruling 2026-10-24 (toolchain plan P3): a local hook keeps only irreversible-harm and second-scale format
checks, so the lock leaves the pre-push entirely. The forge runs the repo's suite on the pushed sha, and this body
judges that checkout's ``HEAD`` with the one reading :func:`dev_lab.dev.lockcheck.lock_problems`. A consumer calls::

    from dev_lab.dev.famtests.lockpin import assert_the_lock_is_pinned

    def test_this_repo_pins_its_lock() -> None:
        assert_the_lock_is_pinned(ROOT)

FRESHNESS stays the serve tick's relock (:mod:`dev_lab.dev.relock`); this body never resolves.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dev_lab.dev.lockcheck import REMEDY, lock_problems

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['LockNotPinned', 'assert_the_lock_is_pinned']


class LockNotPinned(AssertionError):
    """The checked-out commit commits no ``uv.lock``, or holds a requirement below the newest with no reason."""


def assert_the_lock_is_pinned(root: Path) -> None:
    """Raise :class:`LockNotPinned` naming every problem of *root*'s ``HEAD`` and the one remedy."""
    problems = lock_problems(root, 'HEAD')
    if problems:
        raise LockNotPinned('\n'.join([*problems, f'REMEDY: {REMEDY}.']))
