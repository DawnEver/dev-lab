"""WHO MADE EACH SCRATCH ENTRY: the owner record a tool call leaves, its session's liveness, the entry's last touch.

Split out of :mod:`dev_lab.dev._scratch_clear` by size; :mod:`dev_lab.dev.scratch`'s docstring states the contract.

THE RECORD IS WRITTEN WHERE THE ENTRY IS MADE (2026-11-25: a snapshot diff at ``Stop`` named every entry new since
the session's start as the session's own, so a live agent's ``scratch/salvage1125`` was offered to another session's
``clear``). A tool call claims an entry it NAMES -- a write tool by its path, a shell command by spelling
``<scratch>/<name>`` -- when no session owns it and it was born within :data:`CLAIM_WINDOW_S`. The first claim wins
(an exclusive create), so a record is never overwritten by a racing session. An entry nobody named stays OWNERLESS:
never one session's, only the integrator's once it is quiet.

Machine-local state, one directory per checkout: ``<state>/scratch-owners/roots/<key>/<entry>.json`` holds
``{"session", "at", "kept"}``; ``<state>/scratch-owners/sessions/<id>.json`` holds when a hook last heard the session.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from lab_commons import home as _home

from dev_lab.dev.native_session import valid

__all__ = [
    'CLAIM_WINDOW_S',
    'LIVE_S',
    'OWNER_DIR',
    'RECENT_S',
    'Owner',
    'beat',
    'born',
    'claim',
    'heard',
    'live',
    'named',
    'owners',
    'record',
    'release',
    'touched',
]

#: The directory, under the machine-local state, holding every checkout's owner records and every session's beat.
OWNER_DIR: Final = 'scratch-owners'
#: A session no hook heard from for this long is no longer live: its entries fall to the integrator.
LIVE_S: Final = 3600.0
#: An entry touched this recently is in use: only its owner clears it without the user's approval.
RECENT_S: Final = 1800.0
#: A command claims an entry it names only when the entry was born this recently: the longest foreground tool call
#: (ten minutes), so naming an old ownerless entry (``cat scratch/old.txt``) never adopts it.
CLAIM_WINDOW_S: Final = 600.0


@dataclass(frozen=True, slots=True)
class Owner:
    """The session that made one scratch entry, when it claimed it, and whether it keeps the entry on purpose."""

    session: str
    at: float
    kept: bool = False


def _state() -> Path:
    return _home.part('state') / OWNER_DIR


def _records(root: Path) -> Path:
    """*root*'s record directory, keyed by its normalized resolved path so every spelling of a checkout agrees."""
    key = hashlib.sha256(os.path.normcase(str(root.resolve())).encode()).hexdigest()[:16]
    return _state() / 'roots' / key


def _beat_file(session: str) -> Path | None:
    return _state() / 'sessions' / f'{session}.json' if valid(session) else None


def beat(session: str, *, now: float | None = None) -> None:
    """Record that a hook heard *session* now: the liveness :func:`live` reads."""
    path = _beat_file(session)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'seen': time.time() if now is None else now}), encoding='utf-8')


def heard(session: str) -> float | None:
    """When a hook last heard *session*; ``None`` when never (or the record is unreadable)."""
    path = _beat_file(session)
    try:
        seen = json.loads(path.read_text(encoding='utf-8'))['seen'] if path else None
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return float(seen) if isinstance(seen, int | float) else None


def live(session: str, *, now: float | None = None) -> bool:
    """Whether a hook heard *session* within :data:`LIVE_S`."""
    seen = heard(session)
    return seen is not None and (time.time() if now is None else now) - seen < LIVE_S


def owners(root: Path) -> dict[str, Owner]:
    """``{entry name: Owner}`` of every readable record under *root*'s scratch."""
    found: dict[str, Owner] = {}
    folder = _records(root)
    for path in folder.glob('*.json') if folder.is_dir() else ():
        with contextlib.suppress(OSError, ValueError, KeyError, TypeError):
            raw = json.loads(path.read_text(encoding='utf-8'))
            if valid(raw['session']):
                found[path.stem] = Owner(raw['session'], float(raw['at']), bool(raw.get('kept', False)))
    return found


def _write(path: Path, owner: Owner, mode: str) -> None:
    with path.open(mode, encoding='utf-8') as out:
        out.write(json.dumps({'session': owner.session, 'at': owner.at, 'kept': owner.kept}))


def claim(root: Path, name: str, session: str, *, born_at: float | None = None, now: float | None = None) -> bool:
    """Make *session* the owner of entry *name* unless a session already is; whether *session* owns it now.

    *born_at* is when the entry was born, ``None`` while it is still absent. A record claimed more than
    :data:`CLAIM_WINDOW_S` before that (before now, for an absent entry) was a former entry's of the same name --
    deleted, or a write that never landed -- so it is replaced rather than inherited.
    """
    if not valid(session):
        return False
    stamp = time.time() if now is None else now
    folder = _records(root)
    folder.mkdir(parents=True, exist_ok=True)
    try:
        _write(folder / f'{name}.json', Owner(session, stamp), 'x')
    except FileExistsError:
        held = owners(root).get(name)
        if held is None or held.session == session:
            return held is not None
        if held.at >= (stamp if born_at is None else born_at) - CLAIM_WINDOW_S:
            return False
        record(root, name, Owner(session, stamp))
    return True


def record(root: Path, name: str, owner: Owner) -> None:
    """Write *owner* as entry *name*'s record, replacing any: ``--keep`` adopting a kept entry."""
    folder = _records(root)
    folder.mkdir(parents=True, exist_ok=True)
    _write(folder / f'{name}.json', owner, 'w')


def release(root: Path, names: list[str]) -> None:
    """Drop the records of *names*: their entries are gone."""
    for name in names:
        (_records(root) / f'{name}.json').unlink(missing_ok=True)


def born(path: Path) -> float:
    """When *path* was created where the platform says so, else when it last changed; never following a link."""
    stat = path.lstat()
    return getattr(stat, 'st_birthtime', stat.st_mtime)


def touched(path: Path) -> float:
    """The newest modification time at or under *path*, never following a link."""
    newest = path.lstat().st_mtime
    stack = [path] if path.is_dir() and not (path.is_symlink() or path.is_junction()) else []
    while stack:
        for child in stack.pop().iterdir():
            with contextlib.suppress(OSError):
                newest = max(newest, child.lstat().st_mtime)
                if child.is_dir() and not (child.is_symlink() or child.is_junction()):
                    stack.append(child)
    return newest


def named(command: str, scratch: str) -> set[str]:
    """The top-level entry names *command* spells as ``<scratch>/<name>`` (either slash, any absolute prefix)."""
    parts = r'[/\\]+'.join(re.escape(part) for part in scratch.strip('/').split('/'))
    pattern = rf'(?<![\w.-]){parts}[/\\]+([^\s\'"`/\\;|&<>()*?$,]+)'
    return {name for name in re.findall(pattern, command) if name not in {'.', '..'}}
