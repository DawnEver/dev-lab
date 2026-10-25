"""One serve LANE per repo: a busy repo never starves the others (incident 2026-10-25).

:func:`dev_lab.dev.workstation.serve` hands each ``[serve] repos`` checkout to :func:`serve_lanes`, which serves
each in a thread of its own and re-serves a finished lane every period while any other lane still runs.
"""

from __future__ import annotations

import subprocess
import threading
from typing import TYPE_CHECKING

from lab_commons.config import section
from lab_commons.log import emit

from dev_lab.dev.hpchost.spec import KIT, host_serve_argv

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path
    from typing import IO, Any

__all__ = ['serve_lanes', 'serving']


def serve_lanes(
    names: Sequence[str], refreshed: Callable[[str], int], served: Callable[[str], int], *, period_s: float | None
) -> int:
    """Refresh each of *names*, the kit first, serving each in its own thread once it is fresh; the worst exit.

    A lane whose serve ended waits *period_s* and serves again (refreshing first, except the kit) while any
    other lane's serve still runs; once none runs, every lane ends. *period_s* defaults to ``[schedule] tick_minutes``.
    """
    names = sorted(names, key=lambda name: name != KIT)
    period_s = float(section('schedule').get('tick_minutes', 5)) * 60 if period_s is None else period_s
    busy = set(names)  # a lane yet to start counts as running, so an early lane never ends before it starts
    worst = [0]
    cond = threading.Condition()

    def ended(name: str, rc: int) -> None:
        with cond:
            worst[0] = max(worst[0], rc)
            busy.discard(name)
            cond.notify_all()

    def lane(name: str) -> None:
        rc = 3  # a lane that raised reports a crash and never holds the others
        try:
            rc = served(name)
            while True:
                ended(name, rc)
                with cond:
                    if cond.wait_for(lambda: not busy, period_s):
                        return
                    busy.add(name)
                rc = 3
                if name != KIT and (rc := refreshed(name)):
                    return
                rc = served(name)
        finally:
            ended(name, rc)

    threads: list[threading.Thread] = []
    for name in names:
        if rc := refreshed(name):
            ended(name, rc)
            continue
        threads.append(threading.Thread(target=lane, args=(name,), name=f'serve-{name}'))
        threads[-1].start()
    for thread in threads:
        thread.join()
    return worst[0]


def serving(root: Path, run: Callable[..., Any], out: IO[str] | None) -> Callable[[str], int]:
    """``forge serve`` in ``root/<name>`` through *run*, its exit code; *out*, when given, receives its output."""
    streams = {'stdin': subprocess.DEVNULL, 'stdout': out, 'stderr': subprocess.STDOUT} if out else {}

    def served(name: str) -> int:
        rc = run(host_serve_argv(), cwd=root / name, check=False, **streams).returncode
        if rc:
            emit(f'[serve] {name} exited {rc}', err=True)
        return rc

    return served
