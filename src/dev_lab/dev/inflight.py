"""IN-FLIGHT DEDUPE: one run per ``(tree, env, selector)`` on this box; a duplicate ATTACHES to it.

THE MEASURED PROBLEM. On 2026-10-08 one consumer repo logged 98 runner invocations, and 95 were the
SAME key, re-launched about twice a minute by agents polling a box held by one gate. Each re-launch
paid a process start and a tree hash and learned nothing. A queue alone turns those 95 into 95
queued runs of the same suite; this module turns them into one run and 94 readers of its answer.

THE CLAIM IS A SEAT ON THE ONE BOX LEDGER (:mod:`lab_commons.box`; one concurrency mechanism, user ruling
2026-10-18). The first caller holds the seat :func:`seat` of the key -- declared nowhere, so the ledger
counts it 1 -- under the ledger key ``<seat>:<run>``. A later caller is refused that seat at once, reads
the leader's run id off its :class:`~lab_commons.box.Holding`, and WAITS for the leader's
``<digest>.<run>.result``; it never runs. The leader writes the result atomically and then releases the
seat. A crashed leader is reaped by the ledger (pid and creation stamp), so a crash never leaves a queue
waiting forever and no lock file is ever left behind. A leader that RAISES releases its seat and writes
no result, and its followers take the key over in turn -- nothing was measured, so nothing is shared.

THE RESULT DIRECTORY IS BOX-WIDE, NOT PER REPO: beside the ledger, outside every repository, because two
worktrees whose trees hash alike ARE the same request.

WHAT THE RESULT IS, is the caller's: an opaque string (a verify run serialises its verdict line, its
rendering and its exit code). This module only moves it from one leader to many readers.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from lab_commons.box import Refused, box_path, hold, holdings
from lab_commons.compute.durable import durable_text

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

__all__ = ['RESULT_TTL_S', 'RUN_WALL_S', 'RunKey', 'box_directory', 'leader_run', 'run_once', 'seat']

#: How long a published result is kept for a late reader before it is pruned, in seconds. A reader
#: only ever waits for the run id it saw on a live claim, so this bounds disk, not correctness.
RESULT_TTL_S: Final = 24 * 3600.0

#: The wall a leader's seat declares: the run is bounded by its own budget, this only ends the seat.
RUN_WALL_S: Final = 24 * 3600


@dataclass(frozen=True, slots=True)
class RunKey:
    """What makes two requests THE SAME run: the tree, the environment and the selection."""

    tree: str
    env: str
    selector: str

    def digest(self) -> str:
        """A filename-safe address for the key; every field moves it."""
        text = json.dumps([self.tree, self.env, self.selector])
        return hashlib.sha256(text.encode('utf-8')).hexdigest()[:24]


def box_directory() -> Path:
    """The box-wide result directory: beside the ledger, outside every repository."""
    return box_path().parent / 'inflight'


def seat(key: RunKey) -> str:
    """The ledger seat one run of *key* holds."""
    return f'inflight:{key.digest()}'


def leader_run(key: RunKey) -> str | None:
    """The run id of the LIVE leader of *key* on the ledger, else ``None``."""
    name = seat(key)
    return next((one.key.rsplit(':', 1)[1] for one in holdings() if one.seats.get(name)), None)


def _result_path(directory: Path, key: RunKey, run: str) -> Path:
    return directory / f'{key.digest()}.{run}.result'


def _prune(directory: Path, now: float) -> None:
    for stale in directory.glob('*.result'):
        with contextlib.suppress(OSError):
            if now - stale.stat().st_mtime > RESULT_TTL_S:
                stale.unlink()


def _publish(directory: Path, key: RunKey, run: str, answer: str) -> None:
    target = _result_path(directory, key, run)
    durable_text(target, answer)


def run_once(key: RunKey, work: Callable[[], str], *, directory: Path, poll_s: float) -> tuple[str, bool]:
    """Run *work* for *key*, or attach to the run already in flight for it.

    Returns:
        ``(answer, attached)`` -- *attached* is ``True`` when another process's run answered and
        *work* was never called.

    """
    directory.mkdir(parents=True, exist_ok=True)
    _prune(directory, time.time())
    name = seat(key)
    while True:
        mine = uuid.uuid4().hex[:12]
        held = hold({name: 1}, RUN_WALL_S, name, 0.0, key=f'{name}:{mine}')
        try:
            held.__enter__()
        except Refused:
            theirs = leader_run(key)
            answer = None if theirs is None else _wait_for(directory, key, theirs, poll_s=poll_s)
            if answer is not None:
                return answer, True
            time.sleep(poll_s)  # the leader left without an answer: take the key over
            continue
        try:
            answer = work()
            _publish(directory, key, mine, answer)
        finally:
            held.__exit__(None, None, None)
        return answer, False


def _wait_for(directory: Path, key: RunKey, run: str, *, poll_s: float) -> str | None:
    """The leader's answer, or ``None`` when it released its seat (or died) without one."""
    result = _result_path(directory, key, run)
    while True:
        with contextlib.suppress(OSError):
            return result.read_text(encoding='utf-8')
        if leader_run(key) != run:
            with contextlib.suppress(OSError):
                return result.read_text(encoding='utf-8')
            return None
        time.sleep(poll_s)
