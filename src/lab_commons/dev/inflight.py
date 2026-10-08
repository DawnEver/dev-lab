"""IN-FLIGHT DEDUPE: one run per ``(tree, env, selector)`` on this box; a duplicate ATTACHES to it.

THE MEASURED PROBLEM. On 2026-10-08 one consumer repo logged 98 runner invocations, and 95 were the
SAME key, re-launched about twice a minute by agents polling a box held by one gate. Each re-launch
paid a process start and a tree hash and learned nothing. A queue alone turns those 95 into 95
queued runs of the same suite; this module turns them into one run and 94 readers of its answer.

THE MECHANISM, and why it is a file and not a lock. The first caller CLAIMS the key by creating
``<digest>.claim`` exclusively (``O_CREAT|O_EXCL``, atomic on every platform this family runs on),
naming its pid and a run id. A later caller with the same key finds the claim and WAITS for the
leader's ``<digest>.<run>.result``; it never runs. The leader writes the result atomically and then
releases the claim. A claim whose pid is dead is a crashed leader: it is removed and the key is
claimed afresh, so a crash never leaves a queue waiting forever. A leader that RAISES releases its
claim and writes no result, and its followers take the key over in turn -- nothing was measured,
so there is nothing to share.

THE DIRECTORY IS BOX-WIDE, NOT PER REPO: the caller passes the box lock's own resource directory,
outside every repository, because two worktrees whose trees hash alike ARE the same request.

WHAT THE RESULT IS, is the caller's: an opaque string (a verify run serialises its verdict line, its
rendering and its exit code). This module only moves it from one leader to many readers.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from lab_commons.dev.boxlock import BoxLock
from lab_commons.proc import pid_alive

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

__all__ = ['RESULT_TTL_S', 'RunKey', 'box_directory', 'claim_path', 'run_once']

#: How long a published result is kept for a late reader before it is pruned, in seconds. A reader
#: only ever waits for the run id it saw in a live claim, so this bounds disk, not correctness.
RESULT_TTL_S: Final = 24 * 3600.0


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
    """The box-wide claim directory: beside the box lock's records, outside every repository."""
    return BoxLock.resource_dir() / 'inflight'


def claim_path(directory: Path, key: RunKey) -> Path:
    """Where the claim on *key* lives inside *directory*."""
    return directory / f'{key.digest()}.claim'


def _result_path(directory: Path, key: RunKey, run: str) -> Path:
    return directory / f'{key.digest()}.{run}.result'


def _read_claim(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _try_claim(path: Path, run: str) -> bool:
    try:
        handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(handle, 'w', encoding='utf-8') as out:
        out.write(json.dumps({'pid': os.getpid(), 'run': run}))
    return True


def _prune(directory: Path, now: float) -> None:
    for stale in directory.glob('*.result'):
        with contextlib.suppress(OSError):
            if now - stale.stat().st_mtime > RESULT_TTL_S:
                stale.unlink()


def _lead(directory: Path, key: RunKey, run: str, work: Callable[[], str]) -> str:
    claim = claim_path(directory, key)
    try:
        answer = work()
        target = _result_path(directory, key, run)
        temporary = target.with_suffix('.tmp')
        temporary.write_text(answer, encoding='utf-8')
        temporary.replace(target)
    finally:
        with contextlib.suppress(OSError):
            claim.unlink()
    return answer


def run_once(key: RunKey, work: Callable[[], str], *, directory: Path, poll_s: float) -> tuple[str, bool]:
    """Run *work* for *key*, or attach to the run already in flight for it.

    Returns:
        ``(answer, attached)`` -- *attached* is ``True`` when another process's run answered and
        *work* was never called.

    """
    directory.mkdir(parents=True, exist_ok=True)
    _prune(directory, time.time())
    claim = claim_path(directory, key)
    while True:
        mine = uuid.uuid4().hex[:12]
        if _try_claim(claim, mine):
            return _lead(directory, key, mine, work), False
        held = _read_claim(claim)
        if held is None:
            time.sleep(poll_s)  # the claim is being written, or was just released
            continue
        leader, theirs = held.get('pid'), str(held.get('run', ''))
        if not isinstance(leader, int) or not pid_alive(leader):
            with contextlib.suppress(OSError):
                if _read_claim(claim) == held:
                    claim.unlink()
            continue
        answer = _wait_for(directory, key, theirs, leader, poll_s=poll_s)
        if answer is not None:
            return answer, True


def _wait_for(directory: Path, key: RunKey, run: str, leader: int, *, poll_s: float) -> str | None:
    """The leader's answer, or ``None`` when it released the claim (or died) without one."""
    result, claim = _result_path(directory, key, run), claim_path(directory, key)
    while True:
        with contextlib.suppress(OSError):
            return result.read_text(encoding='utf-8')
        held = _read_claim(claim)
        if held is None or str(held.get('run', '')) != run or not pid_alive(leader):
            with contextlib.suppress(OSError):
                return result.read_text(encoding='utf-8')
            return None
        time.sleep(poll_s)
