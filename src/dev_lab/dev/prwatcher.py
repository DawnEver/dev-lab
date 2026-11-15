"""SESSION-HEARS-ITS-PRS, the machine watcher: ONE process per machine hears every session's PRs (dev-lab#581).

The session watch (``forge watch --session <id> --stream``, :mod:`dev_lab.dev.forgewatch`) runs as a harness
``Monitor``, and the harness kills every Monitor after 30 minutes -- so a session waiting on a long PR was refused
at every stop. So one watcher per machine does the polling, outside any harness:

* ``run`` holds the machine lock (:func:`held`; a second ``run`` exits 1, a dead holder's lock is taken over) and
  every :data:`POLL_S` reads every open or pending PR of every session recorded on this machine
  (:mod:`dev_lab.dev.sessionprs`, through :func:`dev_lab.dev.sessionpoll.poll_session`), appends each change the
  session has not heard to that session's INBOX (``sessions/<id>.inbox.jsonl`` in the machine home, beside the
  record it caches -- the forge's statuses stay the truth), and writes the BEAT: its pid, the time and every PR
  key it covered. It exits :data:`YIELDED` when an update of its venv is queued; the next start re-runs it;
* ``start`` and ``session-start`` (the ``SessionStart`` hook) detach ``run`` through the one launch door unless a
  watcher already runs -- idempotent, pure Python, the same on Windows and Linux;
* :func:`heard` is what the ``Stop`` gate (:func:`dev_lab.dev.pushstop.unwatched_refusal`) reads: the beat is
  younger than :data:`FRESH_S`, its writer is alive, and it covers every open PR of the session. A red still needs
  act-or-ack (:func:`dev_lab.dev.pushstop.red_refusal`);
* ``inbox`` (the ``UserPromptSubmit`` hook) surfaces the session's unread events as additional context and marks
  them read.

``python -m dev_lab.dev.prwatcher run | start | session-start | inbox``; the hooks always exit 0.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Final, TextIO

from lab_commons import home as _home
from lab_commons.liveness import creation_stamp, still_the_same_process
from lab_commons.log import emit

from dev_lab.dev import native_session, sessionprs
from dev_lab.dev.forgewatch import SESSION_EVERY_S, YIELDED, clients_at, update_waits
from dev_lab.dev.reclaimrun import detach_argv
from dev_lab.dev.sessionpoll import poll_session

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from dev_lab.dev.forge import Forge
    from dev_lab.dev.forgework import Client

__all__ = [
    'FRESH_S',
    'POLL_S',
    'YIELDED',
    'deliver',
    'ensure',
    'heard',
    'held',
    'main',
    'poll_once',
    'run',
    'running',
    'sessions',
    'take_unread',
]

#: The watcher's poll period: the session watch's (two reads per open PR per poll).
POLL_S: Final = SESSION_EVERY_S
#: A beat older than this is a watcher that stopped polling: two polls missed.
FRESH_S: Final = 2 * POLL_S
#: The directory, under the machine home, holding the watcher's lock and beat.
WATCHER: Final = 'prwatcher'


def _dir() -> Path:
    return _home.home() / WATCHER


def _lock() -> Path:
    return _dir() / 'lock.json'


def _beat() -> Path:
    return _dir() / 'beat.json'


def _read(path: Path) -> dict:
    try:
        found = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def _alive(held_by: dict) -> bool:
    try:
        return still_the_same_process(int(held_by['pid']), held_by.get('created'))
    except (KeyError, TypeError, ValueError):
        return False


def running() -> bool:
    """Whether a live watcher holds the machine lock (a recycled pid reads as gone)."""
    return _alive(_read(_lock()))


@contextlib.contextmanager
def held() -> Iterator[bool]:
    """Hold the machine lock for the block; ``False`` (holding nothing) while a live watcher has it."""
    lock = _lock()
    lock.parent.mkdir(parents=True, exist_ok=True)
    me = {'pid': os.getpid(), 'created': creation_stamp(os.getpid())}
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if _alive(_read(lock)):
                yield False
                return
            lock.unlink(missing_ok=True)  # a crashed watcher's: taken over
            continue
        os.write(fd, json.dumps(me).encode())
        os.close(fd)
        try:
            yield True
        finally:
            if _read(lock).get('pid') == me['pid']:
                lock.unlink(missing_ok=True)
        return
    yield False


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
    except (OSError, ValueError):
        done = 0
    fresh = []
    for raw in lines[done:]:
        with contextlib.suppress(ValueError, TypeError):
            fresh.append(str(json.loads(raw)['line']))
    _cursor(session).write_text(str(len(lines)), encoding='utf-8')
    return fresh


def poll_once(*, clients: Callable[[Forge], Client], now: float | None = None) -> tuple[str, ...]:
    """ONE read of every session's PRs into their inboxes, then the beat; the PR keys it covered."""
    started = time.time() if now is None else now
    covers: list[str] = []
    for session in sessions():
        # what this poll reads: a PR recorded while it runs is covered by the next poll, never by this beat
        polled = {row.key for row in sessionprs.open_rows(session)}
        polled |= {sessionprs.Row(row.forge, row.branch).key for row in sessionprs.pending_rows(session)}
        poll_session(
            session, clients=clients, say=lambda line, s=session: deliver(s, line), seen=sessionprs.heard(session)
        )
        covers += [
            row.key
            for row in sessionprs.open_rows(session)
            if row.key in polled or sessionprs.Row(row.forge, row.branch).key in polled
        ]
    beat = {'pid': os.getpid(), 'created': creation_stamp(os.getpid()), 'at': started, 'covers': sorted(covers)}
    _beat().parent.mkdir(parents=True, exist_ok=True)
    _beat().write_text(json.dumps(beat), encoding='utf-8')
    return tuple(covers)


def heard(session: str, *, now: float | None = None) -> bool:
    """Whether a live watcher's beat is younger than :data:`FRESH_S` and covers every open PR of *session*."""
    beat = _read(_beat())
    clock = time.time() if now is None else now
    try:
        fresh = clock - float(beat['at']) <= FRESH_S
        covers = {str(key) for key in beat['covers']}
    except (KeyError, TypeError, ValueError):
        return False
    return fresh and _alive(beat) and {row.key for row in sessionprs.open_rows(session)} <= covers


def run(
    *,
    clients: Callable[[Forge], Client],
    every_s: float = POLL_S,
    sleep: Callable[[float], None] = time.sleep,
    yielding: Callable[[], str] = update_waits,
) -> int:
    """Hold the machine lock and poll until the venv is wanted (:data:`YIELDED`); 1 when another watcher runs."""
    with held() as mine:
        if not mine:
            return 1
        while not yielding():
            poll_once(clients=clients)
            sleep(every_s)
        return YIELDED


def ensure(root: Path) -> bool:
    """Detach a watcher from *root* unless one runs; whether one was started."""
    if running():
        return False
    detach_argv(root, ['-m', 'dev_lab.dev.prwatcher', 'run'])
    return True


def _payload(stdin: TextIO) -> dict:
    try:
        found = json.load(stdin)
    except ValueError:
        return {}
    return found if isinstance(found, dict) else {}


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None) -> int:
    """``run`` the watcher, ``start`` it, or the ``session-start`` / ``inbox`` hook (see the module doc)."""
    args = list(sys.argv[1:] if argv is None else argv)
    match args[:1]:
        case ['run']:
            return run(clients=clients_at(Path.cwd()))
        case ['start']:
            emit('prwatcher: started' if ensure(Path.cwd()) else 'prwatcher: already running')
            return 0
        case ['session-start']:
            with contextlib.suppress(OSError):
                ensure(Path(_payload(stdin or sys.stdin).get('cwd') or Path.cwd()))
            return 0
        case ['inbox']:
            session = str(_payload(stdin or sys.stdin).get('session_id') or '')
            if lines := take_unread(session):
                said = f"{sessionprs.RULE}: news on this session's PRs:\n" + '\n'.join(lines)
                emit(
                    json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': said}})
                )
            return 0
        case _:
            emit('usage: python -m dev_lab.dev.prwatcher run | start | session-start | inbox', err=True)
            return 2


if __name__ == '__main__':
    raise SystemExit(main())
