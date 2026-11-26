"""A producer's process PRIORITY: below normal, so an interactive run on the same box keeps the scheduler's favor.

:mod:`dev_lab.dev.forgeproduce` starts every producer through :func:`below_normal`; its descendants inherit it.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ['BELOW_NORMAL_NICE', 'below_normal']

#: The POSIX niceness a producer runs at: below normal, so an interactive run keeps the scheduler's favor.
BELOW_NORMAL_NICE: Final = 10


def below_normal[P](spawn: Callable[..., P], argv: list[str], **kwargs: object) -> P:
    """Start *argv* through *spawn* at BELOW-NORMAL priority, which its descendants inherit.

    Windows: ``BELOW_NORMAL_PRIORITY_CLASS`` at creation. POSIX has no creation flag (``preexec_fn`` is
    unsafe beside serve's threads), so a real child is reniced at once, before it spawns workers; a
    renice the OS refuses (a parent already nicer, a child already gone) leaves it where it is.
    """
    if sys.platform == 'win32':
        flags = int(kwargs.pop('creationflags', 0) or 0) | subprocess.BELOW_NORMAL_PRIORITY_CLASS
        return spawn(argv, creationflags=flags, **kwargs)
    proc = spawn(argv, **kwargs)
    if isinstance(proc, subprocess.Popen):
        with contextlib.suppress(OSError):
            os.setpriority(os.PRIO_PROCESS, proc.pid, BELOW_NORMAL_NICE)
    return proc
