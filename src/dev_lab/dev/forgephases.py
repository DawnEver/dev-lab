"""Where a forge read's time went: forge HTTP, ``git fetch``, local git, and the compute left over.

THE INCIDENT (2026-11-13): ``forge queue`` took 170 s and "the forge is slow" was the guess; a profile
measured 5 s of Gitea HTTP and the rest parsing one table 139 times and asking git 200 times. A read verb
that says where its time went answers that question itself (every-wall-teaches): :class:`Phases` times each
forge connection from open to close (:meth:`Phases.transport`) and each child process (:meth:`Phases.children`),
and :meth:`Phases.line` prints them, compute being the wall clock nothing measured accounts for.

Phases are BUSY seconds: reads run concurrently overlap, so their sum may pass the wall clock, and compute
is then ``0``.
"""

from __future__ import annotations

import subprocess
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    import http.client

    from dev_lab.dev.forge import Transport

__all__ = ['COMPUTE', 'FETCH', 'HTTP', 'LOCAL_GIT', 'Phases']

HTTP: Final = 'forge HTTP'
FETCH: Final = 'git fetch'
LOCAL_GIT: Final = 'local git'
COMPUTE: Final = 'compute'


def _phase_of(argv: object) -> str:
    """The phase a child process with *argv* is: a network ``fetch``, else local git (any other child too)."""
    words = [str(word) for word in argv] if isinstance(argv, Sequence) and not isinstance(argv, str) else [str(argv)]
    return FETCH if 'fetch' in words else LOCAL_GIT


class _Timed:
    """A connection whose life, open to close, is counted as :data:`HTTP` (the request and its whole answer)."""

    def __init__(self, conn: http.client.HTTPConnection, phases: Phases) -> None:
        self._conn, self._phases, self._opened = conn, phases, phases.clock()

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401 -- the connection's own attributes
        return getattr(self._conn, name)

    def close(self) -> None:
        try:
            self._conn.close()
        finally:
            self._phases.add(HTTP, self._phases.clock() - self._opened)


class Phases:
    """Busy seconds per phase since construction, on *clock*."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        """Start the wall clock now."""
        self.clock = clock
        self.started = clock()
        self.spent: dict[str, float] = {}
        self._lock = threading.Lock()

    def add(self, phase: str, seconds: float) -> None:
        """Count *seconds* to *phase* (thread-safe: concurrent reads report into one ledger)."""
        with self._lock:
            self.spent[phase] = self.spent.get(phase, 0.0) + seconds

    def timed[**P, R](self, phase: str, call: Callable[P, R]) -> Callable[P, R]:
        """*call*, each call counted to *phase* (a door that runs its child outside :func:`subprocess.run`)."""

        def counted(*args: P.args, **kwargs: P.kwargs) -> R:
            began = self.clock()
            try:
                return call(*args, **kwargs)
            finally:
                self.add(phase, self.clock() - began)

        return counted

    def transport(self, transport: Transport) -> Transport:
        """*transport*, each connection it opens timed as :data:`HTTP` until closed."""

        def opened(host: str, timeout: float) -> http.client.HTTPConnection:
            return _Timed(transport(host, timeout), self)  # type: ignore[return-value]

        return opened

    @contextmanager
    def children(self) -> Iterator[None]:
        """Within it, every :func:`subprocess.run` (git's door, :mod:`lab_commons.launch`, included) is timed."""
        real = subprocess.run

        def timed(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[Any]:  # noqa: ANN401
            began = self.clock()
            try:
                return real(*args, **kwargs)
            finally:
                self.add(_phase_of(args[0] if args else kwargs.get('args', '')), self.clock() - began)

        subprocess.run = timed  # type: ignore[assignment]
        try:
            yield
        finally:
            subprocess.run = real  # type: ignore[assignment]

    def totals(self) -> dict[str, float]:
        """Every phase, :data:`COMPUTE` (the wall clock no phase accounts for, never below 0) included."""
        with self._lock:
            spent = dict(self.spent)
        wall = self.clock() - self.started
        return spent | {COMPUTE: max(0.0, wall - sum(spent.values()))}

    def dominant(self) -> tuple[str, float]:
        """The phase that took the most time, and its seconds."""
        return max(self.totals().items(), key=lambda item: item[1])

    def line(self) -> str:
        """``time 170.2 s -- compute 140.0 s, local git 20.1 s, forge HTTP 5.0 s, git fetch 5.1 s``."""
        wall = self.clock() - self.started
        named = sorted(self.totals().items(), key=lambda item: -item[1])
        return f'time {wall:.1f} s -- ' + ', '.join(f'{phase} {seconds:.1f} s' for phase, seconds in named)
