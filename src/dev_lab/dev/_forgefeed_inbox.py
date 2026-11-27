"""THE HEARER'S MAILBOXES: each session's inbox and each task's queue, with the read cursors over them.

:mod:`dev_lab.dev.forgefeed` writes them as it hears the forge; a session's hooks and ``task status`` read them.
"""

from __future__ import annotations

import contextlib
import json
import time
from pathlib import Path

from lab_commons import home as _home

from dev_lab.dev import native_session, sessionprs, taskledger
from dev_lab.dev.forgethreads import feed_dir

__all__ = ['deliver', 'keep', 'pr_tasks', 'queue', 'sessions', 'take_task_unread', 'take_unread', 'task_pending']


def sessions() -> tuple[str, ...]:
    """Every session with a PR record on this machine."""
    found = _home.home() / sessionprs.SESSIONS
    return tuple(sorted(p.stem for p in found.glob('*.json') if native_session.valid(p.stem))) if found.is_dir() else ()


def _inbox(session: str) -> Path:
    return _home.home() / sessionprs.SESSIONS / f'{session}.inbox.jsonl'


def _cursor(session: str) -> Path:
    return _home.home() / sessionprs.SESSIONS / f'{session}.inbox.read'


def deliver(session: str, line: str, *, at: float | None = None) -> None:
    """Append *line* to *session*'s inbox."""
    path = _inbox(session)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as out:
        out.write(json.dumps({'at': time.time() if at is None else at, 'line': line}) + '\n')


def take_unread(session: str) -> list[str]:
    """*session*'s inbox lines not yet read, oldest first; they are marked read."""
    if not native_session.valid(session):
        return []
    try:
        lines = _inbox(session).read_text(encoding='utf-8').splitlines()
    except OSError:
        return []
    try:
        done = int(_cursor(session).read_text(encoding='utf-8').strip() or 0)
    except OSError, ValueError:
        done = 0
    fresh = []
    for raw in lines[done:]:
        with contextlib.suppress(ValueError, TypeError):
            fresh.append(str(json.loads(raw)['line']))
    _cursor(session).write_text(str(len(lines)), encoding='utf-8')
    return fresh


def pr_tasks() -> dict[str, set[str]]:
    """PR key -> the task its branch ``pr/<slug>/<feature>`` names, for every open PR a session here pushed."""
    tasks: dict[str, set[str]] = {}
    for session in sessions():
        for row in sessionprs.open_rows(session):
            if slug := taskledger.slug_on(row.branch):
                tasks.setdefault(row.key, set()).add(slug)
    return tasks


def queue(slug: str) -> Path:
    """Task *slug*'s queue file."""
    return feed_dir() / 'tasks' / f'{slug}.jsonl'


def task_pending(slug: str) -> list[str]:
    """Every event kept for task *slug*, oldest first; read, not consumed (``task status``)."""
    try:
        raws = queue(slug).read_text(encoding='utf-8').splitlines()
    except OSError:
        return []
    found = []
    for raw in raws:
        with contextlib.suppress(ValueError, KeyError, TypeError):
            found.append(str(json.loads(raw)['line']))
    return found


def take_task_unread(session: str, slug: str) -> list[str]:
    """Task *slug*'s events *session* has not read yet, oldest first; marked read for *session* only."""
    if not native_session.valid(session):
        return []
    found = task_pending(slug)
    cursor = _home.home() / sessionprs.SESSIONS / f'{session}.{slug}.read'
    try:
        done = int(cursor.read_text(encoding='utf-8').strip() or 0)
    except OSError, ValueError:
        done = 0
    cursor.parent.mkdir(parents=True, exist_ok=True)
    cursor.write_text(str(len(found)), encoding='utf-8')
    return found[done:]


def keep(slug: str, line: str) -> None:
    """Append *line* to task *slug*'s queue."""
    queue(slug).parent.mkdir(parents=True, exist_ok=True)
    with queue(slug).open('a', encoding='utf-8') as out:
        out.write(json.dumps({'at': time.time(), 'line': line}) + '\n')
