"""TASK-HEARS-ITS-FORGE-EVENTS, the machine hearer: ONE process per machine hears the forge for every task.

How a task hears the forge (docs-src/dev/forgefeed.md):

* SUBSCRIPTION IS A LABEL. An issue or PR carrying the label ``task:<slug>`` belongs to task ``<slug>``; a PR a
  session of the task opened or pushed (:mod:`dev_lab.dev.sessionprs`) belongs to it too. Nothing else subscribes.
* ONE READ PER REPOSITORY PER TICK. :func:`read_feed` asks each declared repository (the machine file's ``[repos]``)
  for its issues and PRs updated since that repository's persisted cursor
  (``/repos/<o>/<r>/issues?state=all&since=<cursor>``, the same on GitHub and Gitea; further pages only while full) --
  never a request per issue or per PR. Labels come inline, so routing costs no further read; adding a label moves the
  thread's ``updated_at`` (measured on Gitea 2026-11-18), so a labeled thread is heard on the next tick. A reply of
  304 to the stored ETag costs nothing.
* ROUTED TO THE TASK. Each changed thread goes to every task it belongs to -- a PR a session opened belongs to the
  task its branch ``pr/<slug>/<feature>`` names (:func:`dev_lab.dev.taskledger.slug_on`) -- into that task's queue
  (:func:`task_pending`). Every session whose checkout works on the task (its branch,
  :func:`dev_lab.dev.taskledger.task_of`) reads the queue through its own cursor, so each hears every event once.
  A thread whose newest change is this machine's own comment (:func:`record_own`, called by the one comment door,
  within :data:`OWN_WINDOW_S`) is not news.
* COMMIT STATUSES ARE NOT IN ANY FEED: neither forge notifies a status change, so a session's OPEN PRs keep their
  status read (:func:`dev_lab.dev.sessionpoll.poll_session`) -- the only per-PR read left.
* THE TICK IS A SETTING: ``[forgefeed] tick`` in the machine file (:func:`tick_s`, a duration such as ``"2 min"``),
  default :data:`DEFAULT_TICK_S`; anything but a positive duration is refused by name.
* THE PRUNE DUTY RIDES ON ITS OWN INTERVAL: where the family binds ``prune`` to THIS machine (``{ host = "<name>" }``),
  every ``[forgefeed] prune_duty`` (:func:`dev_lab.dev.branchpolicy.prune_duty_s`) the hearer runs
  :func:`dev_lab.dev.branchpolicy.run_here` over its declared checkouts -- one fetch and one branch survey per repo
  per interval: close landed PRs, sweep, prune merged heads, observe the branch policy (D46).

``python -m dev_lab.dev.forgefeed run | start | session-start | inbox | task-pending <slug>``; hooks always exit 0.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Final, TextIO

from lab_commons import home as _home
from lab_commons.config import section
from lab_commons.liveness import creation_stamp, still_the_same_process
from lab_commons.log import emit

from dev_lab.dev import branchpolicy, forgewaves, native_session, sessionprs, taskledger
from dev_lab.dev.backgroundrun import detach_argv
from dev_lab.dev.forge import Forge, forge_from_remote
from dev_lab.dev.forgethreads import (
    Thread,
    declared_seconds,
    feed_dir,
    is_own,
    own,
    read_feed,
    read_json,
    route,
)
from dev_lab.dev.forgewatch import SESSION_EVERY_S, YIELDED, clients_at, env_superseded
from dev_lab.dev.sessionpoll import poll_session
from dev_lab.ops.consent.door import endpoint_send

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

    from dev_lab.dev.forgework import Client

__all__ = [
    'DEFAULT_TICK_S',
    'FRESH_S',
    'POLL_S',
    'RULE',
    'YIELDED',
    'deliver',
    'ensure',
    'hear_feed',
    'heard',
    'held',
    'main',
    'poll_once',
    'run',
    'running',
    'sessions',
    'take_task_unread',
    'take_unread',
    'task_pending',
    'tick_s',
]

#: The tick when the machine file declares none (user ruling D81, 2026-11-19: 2 min until measured live).
DEFAULT_TICK_S: Final = 120
#: The session watch's poll period.
POLL_S: Final = SESSION_EVERY_S
#: A beat older than this is a watcher that stopped polling: two default ticks missed.
FRESH_S: Final = 2 * max(POLL_S, DEFAULT_TICK_S)
#: The directory, under the machine home, holding the hearer's lock, beat, cursors and task queues.
WATCHER: Final = 'forgefeed'
#: The rule this hearer serves.
RULE: Final = 'TASK-HEARS-ITS-FORGE-EVENTS'


def tick_s(table: object = None) -> float:
    """The hearer's tick in seconds: the machine file's ``[forgefeed] tick`` (a duration), else :data:`DEFAULT_TICK_S`.

    Raises:
        ValueError: the declared value is not a positive duration, or is the retired ``tick_s`` (named, with its key).

    """
    return declared_seconds('forgefeed', 'tick', DEFAULT_TICK_S, table)


def _dir() -> Path:
    return feed_dir()


def _lock() -> Path:
    return _dir() / 'lock.json'


def _beat() -> Path:
    return _dir() / 'beat.json'


def _alive(held_by: dict) -> bool:
    try:
        return still_the_same_process(int(held_by['pid']), held_by.get('created'))
    except (KeyError, TypeError, ValueError):
        return False


def running() -> bool:
    """Whether a live watcher holds the machine lock (a recycled pid reads as gone)."""
    return _alive(read_json(_lock()))


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
            if _alive(read_json(lock)):
                yield False
                return
            lock.unlink(missing_ok=True)  # a crashed watcher's: taken over
            continue
        os.write(fd, json.dumps(me).encode())
        os.close(fd)
        try:
            yield True
        finally:
            if read_json(lock).get('pid') == me['pid']:
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


def _pr_tasks() -> dict[str, set[str]]:
    """PR key -> the task its branch ``pr/<slug>/<feature>`` names, for every open PR a session here pushed."""
    tasks: dict[str, set[str]] = {}
    for session in sessions():
        for row in sessionprs.open_rows(session):
            if slug := taskledger.slug_on(row.branch):
                tasks.setdefault(row.key, set()).add(slug)
    return tasks


def _queue(slug: str) -> Path:
    return _dir() / 'tasks' / f'{slug}.jsonl'


def task_pending(slug: str) -> list[str]:
    """Every event kept for task *slug*, oldest first; read, not consumed (``task status``)."""
    try:
        raws = _queue(slug).read_text(encoding='utf-8').splitlines()
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
    except (OSError, ValueError):
        done = 0
    cursor.parent.mkdir(parents=True, exist_ok=True)
    cursor.write_text(str(len(found)), encoding='utf-8')
    return found[done:]


def _keep(slug: str, line: str) -> None:
    _queue(slug).parent.mkdir(parents=True, exist_ok=True)
    with _queue(slug).open('a', encoding='utf-8') as out:
        out.write(json.dumps({'at': time.time(), 'line': line}) + '\n')


def _say(thread: Thread) -> str:
    return f'{thread.key} ({thread.kind or "thread"}) changed at {thread.updated}: {thread.title}'


def hear_feed(clients: Callable[[Forge], Client], forges: Iterable[Forge]) -> tuple[str, ...]:
    """One read per declared repository; each changed thread to its tasks' queues; the repositories heard."""
    pr_tasks, mine, heard_repos = _pr_tasks(), own(), []
    for forge in sorted(set(forges), key=lambda f: f.identity):
        threads = read_feed(clients(forge))
        heard_repos.append(forge.identity)
        for thread in threads:
            if not is_own(thread, mine):
                _deliver_thread(thread, route(thread, thread.labels, pr_tasks))
    return tuple(heard_repos)


def _deliver_thread(thread: Thread, tasks: set[str]) -> None:
    """*thread* into the queue of each of *tasks*."""
    line = _say(thread)
    for slug in sorted(tasks):
        _keep(slug, line)


def _checkouts() -> list[Path]:
    """Every checkout the machine file declares under ``[repos]`` -- no list of its own."""
    return [Path(str(path)) for path in (section('repos') or {}).values()]


def _forges() -> list[Forge]:
    """The repositories to hear: the forge of each of :func:`_checkouts`."""
    forges = []
    for path in _checkouts():
        with contextlib.suppress(OSError, ValueError, subprocess.CalledProcessError):
            forges.append(forge_from_remote(path))
    return forges


def poll_once(
    *, clients: Callable[[Forge], Client], forges: Callable[[], Iterable[Forge]] | None = None, now: float | None = None
) -> tuple[str, ...]:
    """ONE tick: one read per declared repository, then each session's OPEN PR statuses (no listing carries one).

    The beat records the hosts whose feed was read and the PR keys whose statuses were read.
    """
    started = time.time() if now is None else now
    hosts = hear_feed(clients, (forges or _forges)())
    covers: list[str] = []
    for session in sessions():
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
    beat = {
        'pid': os.getpid(), 'created': creation_stamp(os.getpid()), 'at': started, 'covers': sorted(covers),
        'hosts': sorted(hosts),
    }  # fmt: skip
    _beat().parent.mkdir(parents=True, exist_ok=True)
    _beat().write_text(json.dumps(beat), encoding='utf-8')
    return tuple(covers)


def heard(session: str, *, now: float | None = None) -> bool:
    """Whether a live watcher's beat is younger than :data:`FRESH_S` and covers every open PR of *session*."""
    beat = read_json(_beat())
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
    every_s: float | None = None,
    sleep: Callable[[float], None] = time.sleep,
    yielding: Callable[[], str] = env_superseded,
) -> int:
    """Hold the machine lock and poll until the venv is wanted (:data:`YIELDED`); 1 when another watcher runs."""
    period = tick_s() if every_s is None else every_s
    duty_every = branchpolicy.prune_duty_s()
    with held() as mine:
        if not mine:
            return 1
        while not yielding():
            poll_once(clients=clients)
            branchpolicy.duty_once(clients=clients, now=time.time(), every_s=duty_every, checkouts=_checkouts())
            with contextlib.suppress(OSError, ValueError):  # the wave audit is news, never a reason to stop hearing
                forgewaves.refresh(endpoint_send)
            sleep(period)
        return YIELDED


def ensure(root: Path) -> bool:
    """Detach a watcher from *root* unless one runs; whether one was started."""
    if running():
        return False
    detach_argv(root, ['-m', 'dev_lab.dev.forgefeed', 'run'])
    return True


def _payload(stdin: TextIO) -> dict:
    try:
        found = json.load(stdin)
    except ValueError:
        return {}
    return found if isinstance(found, dict) else {}


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None) -> int:
    """``run`` the hearer, ``start`` it, the ``session-start`` / ``inbox`` hook, or a task's kept events."""
    args = list(sys.argv[1:] if argv is None else argv)
    match args[:1]:
        case ['run']:
            return run(clients=clients_at(Path.cwd()))
        case ['start']:
            emit('forgefeed: started' if ensure(Path.cwd()) else 'forgefeed: already running')
            return 0
        case ['session-start']:
            with contextlib.suppress(OSError):
                ensure(Path(_payload(stdin or sys.stdin).get('cwd') or Path.cwd()))
            return 0
        case ['inbox']:
            payload = _payload(stdin or sys.stdin)
            session = str(payload.get('session_id') or '')
            lines = take_unread(session)
            if native_session.valid(session):
                lines += forgewaves.news(session)
            with contextlib.suppress(OSError, ValueError, LookupError):
                task = taskledger.task_of(Path(payload.get('cwd') or Path.cwd()))
                if task is not None:
                    lines += take_task_unread(session, taskledger.slug_of(task))
            if lines:
                said = f"{RULE}: news on this session's task:\n" + '\n'.join(lines)
                emit(
                    json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': said}})
                )
            return 0
        case ['task-pending', slug]:
            for line in task_pending(slug):
                emit(line)
            return 0
        case _:
            emit(
                'usage: python -m dev_lab.dev.forgefeed run | start | session-start | inbox | task-pending <slug>',
                err=True,
            )
            return 2


if __name__ == '__main__':
    raise SystemExit(main())
