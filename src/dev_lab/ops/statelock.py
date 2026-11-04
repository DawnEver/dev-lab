"""ONE EXCLUSIVE LOCK PER ROLE INVOCATION over the role's state directory.

Parallel ssh sessions are parallel processes: the TOTP step (:mod:`dev_lab.ops.totp`), the lockout count
(:mod:`dev_lab.ops.lockout`) and the waves (:mod:`dev_lab.ops.wave`) are each a read-modify-write, and without one
lock around the whole request two sessions read the same state and both act on it -- a code spent twice, a lockout
outrun. :func:`exclusive` holds the OS lock of :func:`dev_lab.dev.servelock.held` (``fcntl.flock`` /
``msvcrt.locking``; dropped by the OS when its holder dies) on ``<state>/role.lock``, waiting for it up to a
bound rather than refusing at once, because a second session is usually a moment behind the first.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from dev_lab.dev.servelock import held

__all__ = ['WAIT_S', 'StateBusy', 'exclusive']

#: How long a request waits for the role lock before it is refused, in seconds.
WAIT_S: Final = 60.0
_POLL_S: Final = 0.02


class StateBusy(TimeoutError):
    """Another session held the role lock past :data:`WAIT_S`."""


@contextlib.contextmanager
def exclusive(state: Path, *, wait_s: float = WAIT_S) -> Iterator[None]:
    """Hold the role's exclusive lock for the body; raise :class:`StateBusy` past *wait_s*."""
    state.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + wait_s
    while True:
        with held(state / 'role.lock') as got:
            if got:
                yield
                return
        if time.monotonic() >= deadline:
            msg = f'another break-glass session held {state / "role.lock"} for {wait_s:g} s'
            raise StateBusy(msg)
        time.sleep(_POLL_S)
