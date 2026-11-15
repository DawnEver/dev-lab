"""A venv update that waits its turn: ``dep --bootstrap ROOT --when-free`` queues itself instead of refusing.

THE WALL (2026-11-14). ``dep`` refuses to move an environment any other process executes from, and a
long-lived ``forge watch --stream`` of another session holds one for hours. A stale venv -- every hook failing
``No module named ...`` -- then had no way forward but stopping someone else's run, and a local wait loop is the
wrong shape: the reaper kills idle background shells.

THE SHAPE: no waiter process. A held ``--when-free`` request is RECORDED in the environment itself
(:data:`PENDING`, under the venv, so it dies with it) and performed by the FIRST door that starts while the
environment is free:

* the hook launcher (``agent_launcher.js``) runs on every tool call from OUTSIDE the venv; seeing a request it
  replays it -- one launcher at a time, its siblings waiting on the claim -- before its own hook starts;
* a long-lived read-only watcher (:mod:`dev_lab.dev.forgewatch`) polls :func:`pending` at each safe point and
  exits, telling its session to re-arm, so it stops being the holder.

The request is cleared once an attempt RAN (green or red: a failing bootstrap reports its failure once, it does
not re-run on every tool call); it stays while the environment is held.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Final

__all__ = ['PENDING', 'clear', 'pending', 'request']

#: The request's file name, directly under the environment's prefix. ``agent_launcher.js`` spells it too.
PENDING: Final = 'dev-lab-pending-bootstrap.json'


def request(prefix: Path | str, argv: Sequence[str]) -> Path:
    """Record that ``dep <argv> --when-free`` waits for *prefix* to be free; the latest request wins."""
    path = Path(prefix) / PENDING
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(f'{PENDING}.{os.getpid()}.tmp')
    staged.write_text(json.dumps({'argv': list(argv)}), encoding='utf-8')
    staged.replace(path)
    return path


def pending(prefix: Path | str) -> tuple[str, ...] | None:
    """The queued ``dep`` argv for *prefix*, or ``None`` when no update waits (an unreadable request is none)."""
    try:
        argv = json.loads((Path(prefix) / PENDING).read_text(encoding='utf-8'))['argv']
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return tuple(str(word) for word in argv) if isinstance(argv, list) else None


def clear(prefix: Path | str) -> None:
    """Drop *prefix*'s request: an attempt ran."""
    (Path(prefix) / PENDING).unlink(missing_ok=True)
