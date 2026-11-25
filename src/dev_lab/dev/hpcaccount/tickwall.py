"""A CRON TICK IS BOUNDED AND NAMED: its lock, its holder record, and its wall.

Measured 2026-11-23 on a verification account: one tick gathering a run in its tenth retry round held the serve
lock for hours; every cron tick after it found the lock held and exited 1 with nothing named, so one long tick
silenced the host. Three facts close that:

* THE TICK TAKES ITS OWN LOCK (:func:`locked`, the OS lock of :func:`dev_lab.dev.servelock.held` -- the same
  ``flock`` the cron line's ``flock -n`` took, so the deploy's kit refresh, ``flock -w`` on the kit's lock, still
  excludes it) and writes its HOLDER RECORD beside it (:mod:`dev_lab.dev.tickholder`).
* THE TICK HAS A WALL (``[schedule] tick_wall``, :data:`dev_lab.dev.hpcaccount.spec.DEFAULT_TICK_WALL`
  states why its default): the serve runs under what is left of it (:func:`within`); past it the serve is asked to
  stop (SIGTERM, which it turns into a clean exit), given :data:`GRACE_S`, then killed, the lock is released and
  ``tick: ended at its wall after <s> s doing <phase>`` is printed to the cron log. Nothing gathered is lost: a run
  advances by persisted steps (:func:`dev_lab.dev.forgerunstate.touch` after each), so the next tick resumes it from
  its last saved step and re-reads every round's job id (:mod:`dev_lab.dev.forgerun`).
* A TICK IS STOPPABLE: SIGTERM to the tick (``hpcaccount tick-stop``) ends it the same way, ``tick: stopped``.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import lab_commons.launch as _door
from lab_commons.liveness import creation_stamp
from lab_commons.log import emit

from dev_lab.dev import tickholder
from dev_lab.dev.servelock import held

__all__ = ['GRACE_S', 'HELD', 'STOPPED', 'WALL', 'TickStopped', 'Wall', 'locked', 'within']

#: A tick that found its lock held: try again at the next period (``EX_TEMPFAIL``).
HELD: Final = 75
#: A tick that ended at its wall (``timeout(1)``'s code).
WALL: Final = 124
#: A tick stopped on purpose (128 + SIGTERM).
STOPPED: Final = 143
#: How long a serve asked to stop may take to release what it holds before it is killed, in seconds.
GRACE_S: Final = 60.0


class TickStopped(Exception):
    """The tick received SIGTERM: stop the serve and let go of the lock."""


@dataclass
class Wall:
    """One tick's bound: its holder *record*, its *wall_s*, and when (monotonic) it started."""

    record: Path
    wall_s: float
    start: float = field(default_factory=time.monotonic)

    def elapsed(self) -> float:
        """Seconds since the tick took its lock."""
        return time.monotonic() - self.start

    def left(self) -> float:
        """Seconds left before the wall (never negative)."""
        return max(0.0, self.wall_s - self.elapsed())

    def phase(self, text: str) -> None:
        """Name the phase the tick is in now (its holder record)."""
        tickholder.phase(text, env={tickholder.ENV: str(self.record)})

    def doing(self) -> str:
        """The phase the record names now: the tick's own, or the one its serve named last."""
        holder = tickholder.read(self.record)
        return holder.phase if holder else 'an unrecorded phase'

    def env(self) -> dict[str, str]:
        """The serve's environment: this one, plus the record it names its phases in."""
        return {**os.environ, tickholder.ENV: str(self.record)}

    def ended(self, why: str) -> str:
        """The one line a tick ended early prints: why, after how long, doing what."""
        return f'tick: {why} after {self.elapsed():.0f} s doing {self.doing()}'


@dataclass(frozen=True)
class Ran:
    """What :func:`within` returns: the serve's exit code, or :data:`WALL` / :data:`STOPPED`."""

    returncode: int


def _end(proc: subprocess.Popen[Any], grace_s: float) -> None:
    """Ask *proc* to stop, give it *grace_s*, then kill it."""
    with contextlib.suppress(ProcessLookupError):
        proc.terminate()
    try:
        proc.wait(timeout=grace_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def within(
    argv: Sequence[str],
    *,
    cwd: Path,
    wall: Wall | None = None,
    popen: Callable[..., subprocess.Popen[Any]] = _door.popen,
    grace_s: float = GRACE_S,
    say: Callable[[str], None] = emit,
    **_kw: object,
) -> Ran:
    """Run *argv* in *cwd* within what is left of *wall* (unbounded without one); see the module docstring."""
    proc = popen(list(argv), cwd=cwd, env=wall.env() if wall else None)
    try:
        return Ran(proc.wait(timeout=wall.left() if wall else None))
    except subprocess.TimeoutExpired:
        code, why = WALL, 'ended at its wall'
    except TickStopped:
        code, why = STOPPED, 'stopped'
    _end(proc, grace_s)
    if wall is not None:
        say(wall.ended(why))
    return Ran(code)


def _stopped(_signum: int, _frame: object) -> None:
    raise TickStopped


@contextlib.contextmanager
def _stoppable() -> Iterator[None]:
    """SIGTERM raises :class:`TickStopped` in the block (POSIX main thread only; elsewhere nothing changes)."""
    if os.name == 'nt':
        yield
        return
    before = signal.signal(signal.SIGTERM, _stopped)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, before)


def locked(
    lock: Path,
    repo: str,
    wall_s: float,
    body: Callable[[Wall], int],
    *,
    say: Callable[[str], None] = emit,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    on_held: Callable[[tickholder.Holder], object] = lambda _holder: None,
) -> int:
    """``body(wall)`` holding *lock* with a holder record; :data:`HELD`, NAMING the holder, when another has it.

    *on_held* is handed a live recorded holder (the cron tick publishes it on the host card). A record beside a FREE
    lock is a tick that died holding it: its lock is taken over, by name.
    """
    record = tickholder.record_of(lock)
    with held(lock) as mine:
        if not mine:
            say(f'[tick] {repo}: {_holder_of(record, now())} -- this tick does nothing (exit {HELD})')
            if (holder := tickholder.read(record)) is not None and tickholder.alive(holder):
                on_held(holder)
            return HELD
        if (dead := tickholder.read(record)) is not None:
            say(f'[tick] {repo}: took over the lock of dead tick pid {dead.pid} (since {dead.since}, in {dead.phase})')
        pid = os.getpid()
        holder = tickholder.Holder(pid, creation_stamp(pid), now().isoformat(timespec='seconds'), wall_s, repo)
        tickholder.write(record, holder)
        wall = Wall(record, wall_s)
        try:
            with _stoppable():
                return body(wall)
        except TickStopped:
            say(wall.ended('stopped'))
            return STOPPED
        finally:
            tickholder.forget(record)


def _holder_of(record: Path, now: datetime) -> str:
    """Who holds a lock whose holder *record* this is, as one clause."""
    holder = tickholder.read(record)
    if holder is None:
        return 'held by a process that wrote no holder record (a deploy refreshing the kit, or a tick of an older kit)'
    if not tickholder.alive(holder):
        return f'held, though its recorded tick pid {holder.pid} is dead (a process it started still holds the lock)'
    return tickholder.describe(holder, now)
