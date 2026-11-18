"""TASK-HEARS-ITS-FORGE-EVENTS, the machine hearer: ONE process per machine hears the forge for every bound task.

How a task hears the forge (docs-src/dev/forgefeed.md):

* SUBSCRIPTION IS A LABEL. An issue or PR carrying the label ``task:<slug>`` belongs to task ``<slug>``; a PR a
  session of the task opened or pushed (:mod:`dev_lab.dev.sessionprs`) belongs to it too. Nothing else subscribes.
* ONE FEED READ PER FORGE PER TICK. :func:`read_feed` asks each forge host's notification feed once for the threads
  changed since a persisted cursor (``/notifications?all=true&since=<cursor>``, the same on GitHub and Gitea) --
  never a request per issue or per PR. Only a CHANGED thread costs one more read: its labels.
* ROUTED TO THE TASK'S SESSIONS. Each changed thread goes to every task it belongs to, then to every session bound to
  that task on this machine (:func:`dev_lab.dev.taskbinding.binding`), into that session's INBOX; a task with no bound
  session keeps its events (:func:`task_pending`) for the next session that binds it. A thread whose latest comment
  this machine posted (:func:`record_own`, called by the one comment door) is not news.
* COMMIT STATUSES ARE NOT IN ANY FEED: neither forge notifies a status change, so a session's OPEN PRs keep their
  status read (:func:`dev_lab.dev.sessionpoll.poll_session`) -- the only per-PR read left.
* A FEED THE TOKEN MAY NOT READ is refused by name (:data:`SCOPE_REMEDY`) into every bound session's inbox, once.

``python -m dev_lab.dev.forgefeed run | start | session-start | inbox | task-pending <slug>``; hooks always exit 0.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Final, TextIO

from lab_commons import home as _home
from lab_commons.liveness import creation_stamp, still_the_same_process
from lab_commons.log import emit

from dev_lab.dev import native_session, sessionprs, taskbinding
from dev_lab.dev.backgroundrun import detach_argv
from dev_lab.dev.forge import Forge, forge_from_remote
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgewatch import SESSION_EVERY_S, YIELDED, clients_at, env_superseded
from dev_lab.dev.sessionpoll import poll_session

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

    from dev_lab.dev.forgework import Client

__all__ = [
    'FRESH_S',
    'LABEL',
    'POLL_S',
    'RULE',
    'SCOPE_REMEDY',
    'YIELDED',
    'Thread',
    'bound_sessions',
    'cursor',
    'deliver',
    'ensure',
    'hear_feed',
    'heard',
    'held',
    'main',
    'poll_once',
    'read_feed',
    'record_own',
    'route',
    'run',
    'running',
    'sessions',
    'take_task_pending',
    'take_unread',
    'task_pending',
]

#: The watcher's poll period: the session watch's (two reads per open PR per poll).
POLL_S: Final = SESSION_EVERY_S
#: A beat older than this is a watcher that stopped polling: two polls missed.
FRESH_S: Final = 2 * POLL_S
#: The directory, under the machine home, holding the hearer's lock, beat, cursors and task queues.
WATCHER: Final = 'forgefeed'
#: The rule this hearer serves.
RULE: Final = 'TASK-HEARS-ITS-FORGE-EVENTS'
#: The label prefix that subscribes a thread to a task: ``task:<slug>``.
LABEL: Final = 'task:'
#: Said when a forge refuses the notification feed: the scope the token lacks, by forge.
SCOPE_REMEDY: Final = (
    'the forge token may not read the notification feed (HTTP 403): add the scope `read:notification` (Gitea) or '
    '`notifications` (GitHub classic token; a fine-grained token cannot read it) to the stored token, then '
    '`python -m dev_lab.dev.forgefeed start`'
)
_FORBIDDEN: Final = 403


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


@dataclasses.dataclass(frozen=True)
class Thread:
    """One changed notification thread: the repository, the issue or PR number, when it changed, its latest comment."""

    forge: Forge
    number: int
    kind: str
    title: str
    updated: str
    comment: int | None

    @property
    def key(self) -> str:
        """``<host>/<owner>/<repo>#<number>``: the same key :mod:`dev_lab.dev.sessionprs` gives a PR."""
        return f'{self.forge.identity}#{self.number}'


def _tail_int(url: object) -> int | None:
    try:
        return int(str(url).rstrip('/').rsplit('/', 1)[1])
    except (IndexError, ValueError):
        return None


def _thread(host: str, raw: dict) -> Thread | None:
    subject, repo = raw.get('subject') or {}, raw.get('repository') or {}
    owner, _, name = str(repo.get('full_name') or '').partition('/')
    number = _tail_int(subject.get('url') or subject.get('html_url'))
    if not owner or not name or number is None:
        return None
    return Thread(
        Forge(host, owner, name), number, str(subject.get('type') or ''), str(subject.get('title') or ''),
        str(raw.get('updated_at') or ''), _tail_int(subject.get('latest_comment_url')),
    )  # fmt: skip


def _cursor_path(host: str) -> Path:
    return _dir() / 'cursor' / f'{host}.json'


def cursor(host: str) -> str:
    """The feed cursor of *host*: the newest ``updated_at`` already heard, ``''`` before the first read."""
    return str(_read(_cursor_path(host)).get('since') or '')


def read_feed(client: Client) -> list[Thread]:
    """ONE request: *client*'s host's threads changed since its cursor; the cursor moves to the newest one seen.

    Raises:
        PermissionError: the token may not read the feed (:data:`SCOPE_REMEDY`).

    """
    host = client.forge.host
    since = cursor(host)
    query = '?all=true' + (f'&since={since}' if since else '')
    try:
        found = client.call('GET', f'{client.backend.api_root}/notifications{query}')
    except ForgeCallFailed as failed:
        attempt = failed.report.attempts[-1] if failed.report.attempts else None
        if attempt is not None and attempt.returncode == _FORBIDDEN:
            msg = f'{host}: {SCOPE_REMEDY}'
            raise PermissionError(msg) from failed
        raise
    threads = [t for raw in (found if isinstance(found, list) else []) if (t := _thread(host, raw)) is not None]
    newest = max([since, *(t.updated for t in threads)])
    if newest != since:
        _cursor_path(host).parent.mkdir(parents=True, exist_ok=True)
        _cursor_path(host).write_text(json.dumps({'since': newest}), encoding='utf-8')
    return threads


def _labels(client: Client, number: int) -> tuple[str, ...]:
    found = client.call('GET', f'{client.repo}/issues/{number}/labels')
    return tuple(str(one.get('name') or '') for one in (found if isinstance(found, list) else []))


def _own_path() -> Path:
    return _dir() / 'own-comments.txt'


def record_own(comment_id: int) -> None:
    """Remember a comment this machine posted, so its own words never come back as news (the comment door calls it)."""
    _own_path().parent.mkdir(parents=True, exist_ok=True)
    with _own_path().open('a', encoding='utf-8') as out:
        out.write(f'{comment_id}\n')


def _own() -> frozenset[int]:
    try:
        return frozenset(int(x) for x in _own_path().read_text(encoding='utf-8').split())
    except (OSError, ValueError):
        return frozenset()


def bound_sessions() -> dict[str, tuple[str, ...]]:
    """Task slug -> the sessions bound to it on this machine (the one binding store, :mod:`taskbinding`)."""
    found: dict[str, list[str]] = {}
    store = taskbinding.binding_path('x').parent
    for path in sorted(store.glob('*.json')) if store.is_dir() else ():
        with contextlib.suppress(OSError, ValueError, taskbinding.UnmigratedBindingError):
            bound = taskbinding.binding(path.stem, start=store)
            if bound is not None:
                found.setdefault(taskbinding.slug_of(bound.task), []).append(path.stem)
    return {slug: tuple(names) for slug, names in found.items()}


def _pr_tasks(sessions_of: dict[str, tuple[str, ...]]) -> dict[str, set[str]]:
    """PR key -> the tasks whose sessions opened or pushed it."""
    tasks: dict[str, set[str]] = {}
    for slug, names in sessions_of.items():
        for session in names:
            for row in sessionprs.open_rows(session):
                tasks.setdefault(row.key, set()).add(slug)
    return tasks


def route(thread: Thread, labels: tuple[str, ...], pr_tasks: dict[str, set[str]]) -> set[str]:
    """The tasks *thread* belongs to: its ``task:<slug>`` labels and the tasks whose sessions opened it."""
    named = {label[len(LABEL) :] for label in labels if label.startswith(LABEL) and len(label) > len(LABEL)}
    return named | pr_tasks.get(thread.key, set())


def _queue(slug: str) -> Path:
    return _dir() / 'tasks' / f'{slug}.jsonl'


def task_pending(slug: str) -> list[str]:
    """Events kept for task *slug* while no session was bound to it; read, not consumed (``task status``)."""
    try:
        raws = _queue(slug).read_text(encoding='utf-8').splitlines()
    except OSError:
        return []
    found = []
    for raw in raws:
        with contextlib.suppress(ValueError, KeyError, TypeError):
            found.append(str(json.loads(raw)['line']))
    return found


def take_task_pending(slug: str) -> list[str]:
    """Task *slug*'s kept events, consumed: the first session bound to it hears them."""
    found = task_pending(slug)
    _queue(slug).unlink(missing_ok=True)
    return found


def _keep(slug: str, line: str) -> None:
    _queue(slug).parent.mkdir(parents=True, exist_ok=True)
    with _queue(slug).open('a', encoding='utf-8') as out:
        out.write(json.dumps({'at': time.time(), 'line': line}) + '\n')


def _say(thread: Thread) -> str:
    return f'{thread.key} ({thread.kind or "thread"}) changed at {thread.updated}: {thread.title}'


def hear_feed(clients: Callable[[Forge], Client], forges: Iterable[Forge]) -> tuple[str, ...]:
    """One feed read per forge HOST among *forges*; each changed thread to its tasks' sessions; the hosts heard."""
    by_host: dict[str, Forge] = {}
    for forge in forges:
        by_host.setdefault(forge.host, forge)
    sessions_of = bound_sessions()
    pr_tasks, own, heard_hosts = _pr_tasks(sessions_of), _own(), []
    for host, forge in sorted(by_host.items()):
        try:
            threads = read_feed(clients(forge))
        except PermissionError as refused:
            for names in sessions_of.values():
                for session in names:
                    deliver(session, f'{RULE}: {refused}')
            continue
        heard_hosts.append(host)
        for thread in threads:
            if thread.comment is None or thread.comment not in own:
                _deliver_thread(
                    thread, route(thread, _labels(clients(thread.forge), thread.number), pr_tasks), sessions_of
                )
    return tuple(heard_hosts)


def _deliver_thread(thread: Thread, tasks: set[str], sessions_of: dict[str, tuple[str, ...]]) -> None:
    """*thread* to every session bound to each of *tasks*; a task with none keeps it for the next binding."""
    line = _say(thread)
    for slug in sorted(tasks):
        for session in sessions_of.get(slug, ()):
            deliver(session, line)
        if not sessions_of.get(slug):
            _keep(slug, line)


def _forges() -> list[Forge]:
    """The forges to hear: every repository a bound session's PRs live in and each bound task's ledger checkout."""
    forges = []
    for names in bound_sessions().values():
        for session in names:
            forges += [row.forge for row in sessionprs.open_rows(session)]
            with contextlib.suppress(OSError, ValueError, subprocess.CalledProcessError):
                bound = taskbinding.binding(session)
                if bound is not None:
                    forges.append(forge_from_remote(taskbinding.checkout_root(bound.ledger)))
    return forges


def poll_once(
    *, clients: Callable[[Forge], Client], forges: Callable[[], Iterable[Forge]] = _forges, now: float | None = None
) -> tuple[str, ...]:
    """ONE tick: one feed read per forge host, then each session's OPEN PR statuses (no feed carries a status).

    The beat records the hosts whose feed was read and the PR keys whose statuses were read.
    """
    started = time.time() if now is None else now
    hosts = hear_feed(clients, forges())
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
    yielding: Callable[[], str] = env_superseded,
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
            session = str(_payload(stdin or sys.stdin).get('session_id') or '')
            lines = take_unread(session)
            with contextlib.suppress(OSError, ValueError, taskbinding.UnmigratedBindingError):
                bound = taskbinding.binding(session) if native_session.valid(session) else None
                if bound is not None:
                    lines += take_task_pending(taskbinding.slug_of(bound.task))
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
