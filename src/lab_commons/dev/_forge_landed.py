"""Did a create whose response was LOST land anyway? The read :mod:`lab_commons.dev.forgework` makes first.

THE HAZARD. A POST can be APPLIED by the forge and its answer then dropped -- a reset connection, a
proxy timeout. The retry the bound allows then files the same issue, comment or PR a second time,
and a reader sees two objects one agent meant as one. So before a create is retried, the recent
objects are read back and one that IS the lost create is returned instead.

WHAT "IS" MEANS, and each clause is a way a twin would otherwise be mistaken for it: the same LOGIN
(the token's own -- another author's identical text is theirs), the same text fields (title and body
for an issue or PR, body for a comment, provenance line included, since that is what was sent), and
created inside :data:`WINDOW_S` of now (an identical object from yesterday is a deliberate repeat).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any, Final

__all__ = ['LOOKBACK', 'WINDOW_S', 'find_landed', 'since']

#: How recent a match must be to be the lost create rather than an earlier, deliberate one.
WINDOW_S: Final = 300.0

#: How many of the newest objects are read back: a lost create is, by construction, among the latest.
LOOKBACK: Final = 20


def since(now: datetime) -> str:
    """The window's start, in the ISO-8601 UTC spelling both forges accept as ``since=``."""
    return (now - timedelta(seconds=WINDOW_S)).strftime('%Y-%m-%dT%H:%M:%SZ')


def find_landed(
    listed: Iterable[Mapping[str, Any]], *, login: str, fields: Mapping[str, str], now: datetime
) -> Mapping[str, Any] | None:
    """The first object in *listed* by *login*, equal on *fields*, created within the window -- or ``None``."""
    for raw in listed:
        if (raw.get('user') or {}).get('login') != login:
            continue
        if any((raw.get(name) or '') != value for name, value in fields.items()):
            continue
        created = raw.get('created_at')
        if created and abs((now - datetime.fromisoformat(created)).total_seconds()) <= WINDOW_S:
            return raw
    return None
