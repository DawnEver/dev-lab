"""END A TEST RUN WHEN IT IS DEAD, not when the wall says so.

A run lost its xdist worker (``node down: Not properly terminated``) and the box seat stayed held for
hours: the only exit besides a clean finish was the wall. A live run does at least one of two things in
every window -- it WRITES (a progress character per test) or it BURNS CPU somewhere in its tree. Silence
alone is not death (one test may run for minutes), idleness alone is not either; BOTH for longer than
twice the per-test timeout is, because that timeout would have fired inside the window on any test still
running. The window is therefore DERIVED from ``[tool.pytest.ini_options] timeout`` (:func:`stall_window`)
and never a second guessed constant; a repo declaring no per-test timeout gets no watch -- the wall alone.

The kill is the run's own tree only (:func:`dev_lab.dev.bounded.terminate_tree`).
"""

from __future__ import annotations

import threading
import tomllib
from typing import TYPE_CHECKING

from lab_commons.proc import process_tree
from lab_commons.proccpu import cpu_seconds

from dev_lab.dev.bounded import terminate_tree

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Callable, Sequence
    from pathlib import Path
    from typing import IO

__all__ = ['StallWatch', 'stall_window', 'watch_process']

#: Seconds between two looks at a watched run.
_POLL_S = 5.0


def stall_window(root: Path, argv: Sequence[str] = ()) -> float | None:
    """Twice the per-test ``timeout`` in seconds; ``None`` when there is none (or 0).

    A ``--timeout=N`` in *argv* (the last wins, as in pytest) outranks *root*'s declared one: a priced run's
    ``--timeout=0`` has no ceiling to derive a window from, so it keeps the wall alone.
    """
    given = [arg.split('=', 1)[1] for arg in argv if arg.startswith('--timeout=')]
    if given:
        return _doubled(given[-1])
    manifest = root / 'pyproject.toml'
    if not manifest.is_file():
        return None
    options = tomllib.loads(manifest.read_text(encoding='utf-8')).get('tool', {}).get('pytest', {})
    return _doubled(options.get('ini_options', {}).get('timeout'))


def _doubled(value: object) -> float | None:
    try:
        seconds = float(value) if isinstance(value, (int, float, str)) else 0.0
    except ValueError:
        return None
    return 2 * seconds if seconds > 0 else None


class StallWatch:
    """Silence and idleness of one run, judged against *window_s*; :meth:`check` names a stall."""

    def __init__(self, *, window_s: float, clock: Callable[[], float], tree_cpu: Callable[[], float]) -> None:
        """Start the window now: *clock* and *tree_cpu* are read on every :meth:`check`."""
        self._window = window_s
        self._clock = clock
        self._tree_cpu = tree_cpu
        self._last_write = self._last_busy = clock()
        self._cpu = tree_cpu()

    def wrote(self) -> None:
        """The run printed something."""
        self._last_write = self._clock()

    def check(self) -> str | None:
        """Why the run is dead, or ``None`` while it wrote or burned CPU inside the window."""
        now, cpu = self._clock(), self._tree_cpu()
        if cpu > self._cpu:
            self._cpu, self._last_busy = cpu, now
        quiet = now - max(self._last_write, self._last_busy)
        if quiet < self._window:
            return None
        return (
            f'no output and no CPU in the run tree for {quiet:.0f} s '
            f'(window {self._window:.0f} s, twice the per-test timeout)'
        )


def _tree_cpu(pid: int) -> float:
    return sum(cpu_seconds(member) or 0.0 for member in {pid, *process_tree(pid)})


def watch_process(
    process: subprocess.Popen[str], *, window_s: float, handle: IO[str], clock: Callable[[], float]
) -> StallWatch:
    """Start a daemon that ends *process*'s tree on a stall, writing the named reason to *handle*.

    The caller calls :meth:`StallWatch.wrote` on each line it reads.
    """
    watch = StallWatch(window_s=window_s, clock=clock, tree_cpu=lambda: _tree_cpu(process.pid))
    done = threading.Event()

    def loop() -> None:
        while not done.wait(_POLL_S) and process.poll() is None:
            if (why := watch.check()) is not None:
                handle.write(f'verify: STALLED -- {why}; ending the run tree\n')
                handle.flush()
                terminate_tree(process)
                return

    threading.Thread(target=loop, name='stallwatch', daemon=True).start()
    return watch
