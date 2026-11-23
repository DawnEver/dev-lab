"""WHO HOLDS A TICK'S LOCK, AND WHAT IT IS DOING: the holder record beside a cluster tick's lock file.

A tick holds an OS lock (:func:`dev_lab.dev.servelock.held`) on ``<serve>/<repo>.lock``; the lock says only THAT
it is held. Measured 2026-11-23: one tick gathering a run in its tenth retry round held it for hours, every cron
tick after it exited 1 with nothing named, and the queue guessed STALE for three reasons none of which was the
cause. So the holder writes a RECORD beside the lock (``<lock>.holder``, JSON): its pid and that pid's creation
stamp (a recycled pid is never read as the holder, :func:`lab_commons.liveness.still_the_same_process`), when it
started, its wall, and the PHASE it is in. The serve the tick runs is handed the record's path in :data:`ENV` and
names its own phases into it (:func:`phase`), so the phase read at the wall is the step that ran long.

The record is written by the holder only while it holds the lock, replaced atomically, and deleted when it lets
go; a record found beside a FREE lock is a holder that died holding it.
"""

from __future__ import annotations

import contextlib
import json
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from lab_commons.liveness import still_the_same_process

__all__ = ['ENV', 'Holder', 'age', 'alive', 'describe', 'forget', 'phase', 'read', 'record_of', 'span', 'write']

#: The environment variable a tick hands its serve: the path of its holder record.
ENV: Final = 'LAB_TICK_HOLDER'


@dataclass(frozen=True)
class Holder:
    """One tick holding its lock: who (pid, creation stamp), since when (ISO UTC), its wall, and its phase now."""

    pid: int
    created: int | None
    since: str
    wall_s: float
    repo: str
    phase: str = 'starting'

    def started(self) -> datetime:
        """When the holder took the lock."""
        return datetime.fromisoformat(self.since)


def record_of(lock: Path) -> Path:
    """The holder record of *lock*: ``<lock>.holder``."""
    return lock.with_name(lock.name + '.holder')


def read(record: Path) -> Holder | None:
    """The holder *record* names; ``None`` when absent or torn (a torn record names no holder)."""
    try:
        raw = json.loads(record.read_text(encoding='utf-8'))
        return Holder(**{key: raw[key] for key in Holder.__dataclass_fields__ if key in raw})
    except (OSError, ValueError, TypeError):
        return None


def write(record: Path, holder: Holder) -> None:
    """Replace *record* with *holder*, atomically: a reader never sees half a record."""
    record.parent.mkdir(parents=True, exist_ok=True)
    partial = record.with_name(f'{record.name}.{os.getpid()}.tmp')
    partial.write_text(json.dumps(asdict(holder)), encoding='utf-8')
    partial.replace(record)


def forget(record: Path) -> None:
    """Delete *record*: its holder let go."""
    record.unlink(missing_ok=True)


def phase(text: str, *, env: Mapping[str, str] | None = None) -> None:
    """Name the phase the running tick is in, in the record :data:`ENV` names; nothing outside a tick.

    Only the record's own holder or the serve it runs calls this, so the read-modify-write never races a writer.
    """
    path = (os.environ if env is None else env).get(ENV)
    if not path or (holder := read(Path(path))) is None:
        return
    with contextlib.suppress(OSError):  # a phase that cannot be written never stops the work it names
        write(Path(path), replace(holder, phase=text))


def alive(holder: Holder) -> bool:
    """Whether *holder*'s process still runs (a recycled pid does not)."""
    return still_the_same_process(holder.pid, holder.created)


def age(holder: Holder, now: datetime | None = None) -> float:
    """Seconds since *holder* took the lock."""
    return ((now or datetime.now(UTC)) - holder.started()).total_seconds()


def span(seconds: float) -> str:
    """*seconds* as a person reads an age: ``7 min``, ``2 h 05 min``."""
    hours, minutes = divmod(int(seconds // 60), 60)
    return f'{hours} h {minutes:02d} min' if hours else f'{minutes} min'


def describe(holder: Holder, now: datetime | None = None) -> str:
    """``held by tick pid <p> since <t> (<age>) in <phase>``."""
    return f'held by tick pid {holder.pid} since {holder.since} ({span(age(holder, now))}) in {holder.phase}'
