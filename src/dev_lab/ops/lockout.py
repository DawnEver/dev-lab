"""THE CODE LOCKOUT: after ``lockout_after`` consecutive wrong codes, refuse every code for ``lockout_minutes``.

User ruling 2026-11-03: 5 and 15 by default, both configured. Persisted in the role's state directory
(``lockout.json``), so a restart does not reset it; a correct code resets the count; while locked even a correct
code is refused (and not consumed); the lockout alerts once, when it begins. Its read-modify-write is atomic only
under the role lock the caller holds (:func:`dev_lab.ops.statelock.exclusive`).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

__all__ = ['Lockout', 'guarded']


@dataclass
class Lockout:
    """Consecutive wrong codes, and until when every code is refused (``0`` = not locked)."""

    failures: int = 0
    until: float = 0.0


def _file(state: Path) -> Path:
    return state / 'lockout.json'


def _load(state: Path) -> Lockout:
    path = _file(state)
    return Lockout(**json.loads(path.read_text(encoding='utf-8'))) if path.is_file() else Lockout()


def _save(state: Path, lock: Lockout) -> None:
    state.mkdir(parents=True, exist_ok=True)
    partial = _file(state).with_suffix('.partial')
    partial.write_text(json.dumps(asdict(lock)), encoding='utf-8')
    partial.replace(_file(state))


def guarded(
    state: Path,
    check: Callable[[], None],
    *,
    now: float,
    after: int,
    minutes: float,
    on_lock: Callable[[float], None],
    refused: type[Exception],
) -> None:
    """Run *check* (raising *refused* on a wrong code) unless locked; count, lock and reset around it.

    Raises:
        Exception: *refused*, from *check* or because the lockout holds (naming until when).

    """
    lock = _load(state)
    if now < lock.until:
        msg = f'too many wrong codes: every code is refused for {(lock.until - now) / 60:.0f} more minute(s)'
        raise refused(msg)
    try:
        check()
    except refused:
        lock.failures += 1
        if lock.failures >= after:
            lock.failures, lock.until = 0, now + minutes * 60
            _save(state, lock)
            on_lock(lock.until)
        else:
            _save(state, lock)
        raise
    if lock.failures or lock.until:
        _save(state, Lockout())
