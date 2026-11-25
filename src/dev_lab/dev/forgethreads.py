"""THE THREADS A TASK HEARS: one ``issues?since=`` read per repository, its cursor, and this machine's own comments.

Split from :mod:`dev_lab.dev.forgefeed` (module-size band) so the one comment door
(:class:`dev_lab.dev.forgework.Client`) can record its own comments without importing the hearer.
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import json
import time
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons import home as _home
from lab_commons.config import section
from lab_commons.quantity import Renamed, parse, refuse_renamed

if TYPE_CHECKING:
    from dev_lab.dev.forge import Forge
    from dev_lab.dev.forgework import Client

__all__ = [
    'LABEL',
    'OWN_WINDOW_S',
    'PAGE',
    'Thread',
    'cursor',
    'declared_seconds',
    'feed_dir',
    'is_own',
    'own',
    'read_feed',
    'read_json',
    'record_own',
    'route',
]

#: The label prefix that subscribes a thread to a task: ``task:<slug>``.
LABEL: Final = 'task:'
#: Issues per page; a shorter page is the last.
PAGE: Final = 50


def feed_dir() -> Path:
    """The hearer's directory under the machine home: lock, beat, cursors, task queues, own comments."""
    return _home.home() / 'forgefeed'


def read_json(path: Path) -> dict:
    """*path*'s JSON object, or ``{}`` when it is missing, unreadable or not an object."""
    try:
        found = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


@dataclasses.dataclass(frozen=True)
class Thread:
    """One changed issue or PR: its repository, number, kind, title, when it last changed, and its labels."""

    forge: Forge
    number: int
    kind: str
    title: str
    updated: str
    labels: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        """``<host>/<owner>/<repo>#<number>``: the same key :mod:`dev_lab.dev.sessionprs` gives a PR."""
        return f'{self.forge.identity}#{self.number}'


def _thread(forge: Forge, raw: dict) -> Thread | None:
    """One issue or PR of *forge* from its ``issues`` listing row, labels inline."""
    number = raw.get('number')
    if not isinstance(number, int):
        return None
    kind = 'pull' if raw.get('pull_request') else 'issue'
    labels = tuple(str(one.get('name') or '') for one in raw.get('labels') or () if isinstance(one, dict))
    return Thread(forge, number, kind, str(raw.get('title') or ''), str(raw.get('updated_at') or ''), labels)


def _cursor_path(forge: Forge) -> Path:
    return feed_dir() / 'cursor' / forge.host / forge.owner / f'{forge.repo}.json'


def cursor(forge: Forge) -> str:
    """The cursor of *forge*'s repository: the newest ``updated_at`` already heard, ``''`` before the first read."""
    return str(read_json(_cursor_path(forge)).get('since') or '')


def _etag(forge: Forge) -> str:
    return str(read_json(_cursor_path(forge)).get('etag') or '')


def read_feed(client: Client) -> list[Thread]:
    """ONE read (more only while pages are full): *client*'s repository's issues and PRs updated since its cursor.

    The cursor moves to the newest ``updated_at`` seen; a thread exactly at the cursor is not heard twice.
    """
    forge = client.forge
    since, etag = cursor(forge), _etag(forge)
    threads: list[Thread] = []
    page, new_etag = 1, etag
    while True:
        query = f'?state=all&limit={PAGE}&per_page={PAGE}&page={page}' + (f'&since={since}' if since else '')
        status, header, found = client.call_conditional(
            'GET', f'{client.repo}/issues{query}', etag if page == 1 else ''
        )
        if status == HTTPStatus.NOT_MODIFIED:
            return []
        if page == 1 and header:
            new_etag = header
        rows = found if isinstance(found, list) else []
        threads += [t for raw in rows if (t := _thread(forge, raw)) is not None and t.updated != since]
        if len(rows) < PAGE:
            break
        page += 1
    newest = max([since, *(t.updated for t in threads)])
    if newest != since or new_etag != etag:
        _cursor_path(forge).parent.mkdir(parents=True, exist_ok=True)
        _cursor_path(forge).write_text(json.dumps({'since': newest, 'etag': new_etag}), encoding='utf-8')
    return threads


#: A thread changed within this many seconds of this machine's own comment on it is that comment, not news.
OWN_WINDOW_S: Final = 5.0


def _own_path() -> Path:
    return feed_dir() / 'own-comments.jsonl'


def record_own(key: str, at: float | None = None) -> None:
    """Remember that this machine commented on thread *key* at *at* (the one comment door calls it)."""
    _own_path().parent.mkdir(parents=True, exist_ok=True)
    with _own_path().open('a', encoding='utf-8') as out:
        out.write(json.dumps({'key': key, 'at': time.time() if at is None else at}) + '\n')


def own() -> dict[str, list[float]]:
    """Thread key -> the times this machine commented on it (:func:`record_own`)."""
    found: dict[str, list[float]] = {}
    try:
        lines = _own_path().read_text(encoding='utf-8').splitlines()
    except OSError:
        return found
    for raw in lines:
        with contextlib.suppress(ValueError, KeyError, TypeError):
            row = json.loads(raw)
            found.setdefault(str(row['key']), []).append(float(row['at']))
    return found


def is_own(thread: Thread, own: dict[str, list[float]]) -> bool:
    """Whether *thread*'s newest change is this machine's own comment: within :data:`OWN_WINDOW_S` of one."""
    stamps = own.get(thread.key)
    if not stamps or not thread.updated:
        return False
    try:
        changed = dt.datetime.fromisoformat(thread.updated).timestamp()
    except ValueError:
        return False
    return any(abs(changed - at) <= OWN_WINDOW_S for at in stamps)


def route(thread: Thread, labels: tuple[str, ...], pr_tasks: dict[str, set[str]]) -> set[str]:
    """The tasks *thread* belongs to: its ``task:<slug>`` labels and the tasks whose sessions opened it."""
    named = {label[len(LABEL) :] for label in labels if label.startswith(LABEL) and len(label) > len(LABEL)}
    return named | pr_tasks.get(thread.key, set())


#: ``[forgefeed]`` keys retired by the 2026-11-25 ruling (the value carries its unit), refused with their new line.
FEED_RENAMED: Final = {'tick_s': Renamed('tick', 's'), 'prune_duty_s': Renamed('prune_duty', 's')}


def declared_seconds(table_name: str, key: str, default: float, table: object = None) -> float:
    """``[<table_name>] <key>`` of the machine file (or *table*): a positive duration, in seconds, else *default*.

    Read through :func:`lab_commons.quantity.parse` (``tick = "2 min"``); a retired ``<key>_s`` is refused with its
    new line (:data:`FEED_RENAMED`).

    Raises:
        ValueError: the declared value is not a positive duration, or is a retired key (named, with its key).

    """
    if table is None:
        table = section(table_name)
    held = table if isinstance(table, dict) else {}
    refuse_renamed(f'[{table_name}]', held, FEED_RENAMED)
    if key not in held:
        return float(default)
    return parse(f'[{table_name}] {key}', held[key], 'duration', positive=True)
