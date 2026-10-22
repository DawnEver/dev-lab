"""THE OUTBOX JOURNAL -- every outward forge write is on disk, fsynced, BEFORE it is attempted.

THE HAZARD (design D19, 2026-10-16). A host may crash at any point, and the forge may be down for hours.
A write that lived only in a process -- a status, a comment, an attachment, a label, an issue -- is lost
with that process, and nobody knows it was ever meant. So the forge door (:class:`dev_lab.dev.forgework.Client`)
records each write first (:meth:`Journal.record`), attempts it, and acknowledges it (:meth:`Journal.ack`) once the forge
answered; a write that failed stays journaled, and every tick replays it
(:func:`dev_lab.dev.forgeoutbox.replay`) until the forge acknowledges it. Forge down = the journal grows.

KEYED, SO A REPLAY NEVER DOUBLE-POSTS. A :class:`Write`'s key is the hash of what it sends, or the caller's
SUPERSEDING key (one status per commit and context: the newer write replaces the older one queued under it).
A create carries a :class:`Probe` -- the list it lands in and the fields that identify it -- and both a
retry inside one call and a replay a tick later look first: an object by this token's LOGIN (another author's
identical text is theirs), equal on those fields, created since the write was journaled (an identical object
from before it is a deliberate repeat) IS the write -- it landed and its answer was lost -- so it is
acknowledged, never sent again. ``PATCH``/``PUT``/``DELETE`` are idempotent as sent; a ``POST`` without a probe is one
the forge itself keys (a label by name, a release by tag), so a duplicate is refused there, not stored twice.

A WRITE OUTLIVES ITS MEANING AT :attr:`Write.until`. A lease is worth only its synchronous answer -- a claim
replayed later would assert a lease nobody is running -- so a claim is journaled with ``until`` = now and is
never replayed; every other write is replayed for :data:`RETAIN_S`, then dropped by name.

ONE FILE PER WRITE, written to a temporary name, fsynced, renamed over the entry, and the directory fsynced
(POSIX), so a crash at any instant leaves either the whole entry or the previous one -- never half.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final

from lab_commons.compute.durable import durable_write

from dev_lab.dev.worktreeplace import main_checkout

__all__ = [
    'LOOKBACK', 'OUTBOX_REL', 'RETAIN_S', 'WRITES', 'Durable', 'Journal', 'Probe', 'Write', 'journal_for',
    'outbox_dir', 'since', 'write_key',
]  # fmt: skip

#: The outbox, relative to the MAIN checkout's root: every lane of one repository shares it.
OUTBOX_REL: Final = 'output/forge/outbox'

#: The journal of writes, inside the outbox.
WRITES: Final = 'writes'

#: How long a write that is not a lease is replayed before it is dropped (seven days).
RETAIN_S: Final = 7 * 24 * 3600.0

#: How many of the newest objects a probe reads back: a lost create is, by construction, among the latest.
LOOKBACK: Final = 20

#: The fields a forge names an object's author in: an issue or comment, a status, an attachment.
_AUTHORS: Final = ('user', 'creator', 'uploader')

#: Clock skew allowed between this host and the forge when a probe asks "created after it was journaled".
_SKEW_S: Final = 120.0


def since(now: datetime) -> str:
    """A list's ``since=`` for a probe: a few minutes before *now*, in the ISO-8601 UTC spelling both forges take."""
    return (now - timedelta(seconds=5 * 60)).strftime('%Y-%m-%dT%H:%M:%SZ')


def write_key(method: str, host: str, path: str, body: bytes) -> str:
    """The content key of a write: the hash of everything it sends."""
    digest = hashlib.sha256()
    for part in (method.encode(), host.encode(), path.encode(), body):
        digest.update(len(part).to_bytes(8, 'big'))
        digest.update(part)
    return digest.hexdigest()


@dataclass(frozen=True)
class Probe:
    """Where a create lands and the fields that identify it: ``GET path`` lists it once it landed."""

    path: str
    fields: Mapping[str, str] = field(default_factory=dict)

    def landed(self, listed: Iterable[Mapping[str, Any]], *, after: float, login: str) -> Mapping[str, Any] | None:
        """The listed object by *login*, equal on every field, created no earlier than *after* (epoch s); else ``None``.

        An object naming no author or no ``created_at`` (an attachment on some forges) is judged on what it names.
        """
        for raw in listed:
            if any((raw.get(name) or '') != value for name, value in self.fields.items()):
                continue
            if any((raw.get(name) or {}).get('login') not in {None, login} for name in _AUTHORS):
                continue
            created = raw.get('created_at')
            if not created or datetime.fromisoformat(created).timestamp() >= after - _SKEW_S:
                return raw
        return None


@dataclass(frozen=True)
class Durable:
    """How the door journals a write: its superseding *key* (default: its content), its *probe*, its *until*."""

    key: str = ''
    probe: Probe | None = None
    until: float = 0.0


@dataclass(frozen=True)
class Write:
    """One outward write, exactly as the door sends it."""

    key: str
    method: str
    path: str
    content_type: str
    body: bytes
    host: str = ''
    probe: Probe | None = None
    queued_at: float = 0.0
    until: float = 0.0

    def to_json(self) -> dict[str, Any]:
        """The journal entry."""
        probe = None if self.probe is None else {'path': self.probe.path, 'fields': dict(self.probe.fields)}
        return {
            'key': self.key, 'method': self.method, 'path': self.path, 'content_type': self.content_type,
            'body': base64.b64encode(self.body).decode('ascii'), 'host': self.host, 'probe': probe,
            'queued_at': self.queued_at, 'until': self.until,
        }  # fmt: skip

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> Write:
        """The write a journal entry holds."""
        probe = raw.get('probe')
        return cls(
            raw['key'], raw['method'], raw['path'], raw['content_type'], base64.b64decode(raw['body']),
            raw.get('host') or '', None if probe is None else Probe(probe['path'], dict(probe['fields'])),
            float(raw['queued_at']), float(raw['until']),
        )  # fmt: skip


@dataclass(frozen=True)
class Journal:
    """The outbox's write journal: one fsynced JSON file per unacknowledged write."""

    directory: Path

    def record(self, write: Write) -> Write:
        """Journal *write* (stamped now, replayable for :data:`RETAIN_S` unless it says otherwise); returns it."""
        now = time.time()
        stamped = Write(
            write.key, write.method, write.path, write.content_type, write.body, write.host, write.probe,
            write.queued_at or now, write.until or now + RETAIN_S,
        )  # fmt: skip
        durable_write(self._entry(stamped.key), json.dumps(stamped.to_json()).encode('utf-8'))
        return stamped

    def ack(self, key: str) -> None:
        """The forge acknowledged the write under *key*: it leaves the journal."""
        self._entry(key).unlink(missing_ok=True)

    def pending(self) -> tuple[Write, ...]:
        """Every journaled write, oldest first; a torn entry is skipped, never replayed."""
        found = []
        for path in self.directory.glob('*.json') if self.directory.is_dir() else ():
            try:
                found.append(Write.from_json(json.loads(path.read_text(encoding='utf-8'))))
            except (ValueError, KeyError, TypeError):
                continue
        return tuple(sorted(found, key=lambda write: (write.queued_at, write.key)))

    def _entry(self, key: str) -> Path:
        return self.directory / f'{hashlib.sha256(key.encode()).hexdigest()[:32]}.json'


def outbox_dir(root: Path) -> Path:
    """The outbox of the repository *root* belongs to, in its MAIN checkout (shared by every lane)."""
    return main_checkout(root) / OUTBOX_REL


def journal_for(root: Path) -> Journal:
    """The write journal of *root*'s repository: what :func:`dev_lab.dev.forgework.client_for` records into."""
    return Journal(outbox_dir(root) / WRITES)
