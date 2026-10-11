"""A FAILURE NOBODY WATCHES MUST REACH A HUMAN -- the alarms ``forge serve`` raises from an unattended host.

A cron tick on a cluster login node logs into a file nobody reads. Four failures there are SILENT
unless raised: the forge refusing the stored credential (``auth``: a 401/403, an expired token, or none
stored), a claim whose lease cannot be renewed (``lease``: the forge refused the post, another owner
holds the claim now, or Slurm holds orphaned jobs), a cluster run that cannot advance (``run``), and
an account IDLE while work it could serve is pending (``idle``: nothing claimed, nothing in flight).

EVERY ALARM IS ONE STRUCTURED LINE ON STDERR, ALWAYS: ``{"event": "lab_commons.forge.alarm", ...}``
(:data:`EVENT`). That line is the contract with a consumer that routes it (cc-config's Telegram/system
notify reads the tick's output); it carries no token, only the kind, the repo, a subject and a body.
WHERE THE FAMILY'S OWN CHANNELS ARE CONFIGURED THEY ARE USED TOO: the machine file's ``[alerts]``
table (:mod:`lab_commons.config`) drives :class:`lab_commons.supervise.alert.Notifier` -- Telegram,
email, webhook -- exactly as supervision does. No table, or none enabled, delivers nothing beyond the
line, and says so on the line (``"delivered": []``).

A CRON TICK EVERY FIVE MINUTES MUST NOT PAGE EVERY FIVE MINUTES. A delivery of one ``(kind, repo)``
is repeated at most once per :data:`REPEAT` (state: ``forge-alarms.json`` beside the machine file);
the structured line is written every time, because it is the log, and says ``"repeat": true`` inside
that window so a consumer routes only the first. A channel that failed is retried on the next tick.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from lab_commons.config import config_path, section
from lab_commons.log import emit
from lab_commons.supervise.alert import Notice, Notifier
from lab_commons.supervise.verdict import Severity

__all__ = ['AUTH', 'EVENT', 'IDLE', 'LEASE', 'REPEAT', 'RUN', 'Alarm', 'sound']

#: The ``event`` field of every alarm line -- what a consumer routes on.
EVENT: Final = 'lab_commons.forge.alarm'

#: The kinds (module docstring).
AUTH: Final = 'auth'
LEASE: Final = 'lease'
IDLE: Final = 'idle'
RUN: Final = 'run'

#: How long one ``(kind, repo)`` delivery waits before it is delivered again.
REPEAT: Final = timedelta(hours=6)


@dataclass(frozen=True)
class Alarm:
    """One silent failure, named: its kind, the repo it concerns, a one-line subject and the remedy."""

    kind: str
    repo: str
    subject: str
    body: str


def _state() -> Path:
    return config_path().parent / 'forge-alarms.json'


def _last(path: Path) -> dict[str, str]:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def sound(
    alarm: Alarm,
    *,
    alerts: Mapping[str, Any] | None = None,
    send: Callable[[Notice], list[Any]] | None = None,
    now: datetime | None = None,
) -> tuple[str, ...]:
    """Write the alarm's line; deliver it through the configured channels unless delivered within :data:`REPEAT`.

    *alerts* is the ``[alerts]`` table (default: the machine file's); *send* replaces the notifier.
    Returns the channels that took it.
    """
    now = now or datetime.now(UTC)
    table = section('alerts') if alerts is None else alerts
    deliver = send or Notifier({'alerts': table}).send
    key = f'{alarm.kind}:{alarm.repo}'
    path = _state()
    last = _last(path)
    due = key not in last or now - datetime.fromisoformat(last[key]) >= REPEAT
    delivered: tuple[str, ...] = ()
    if due:
        notice = Notice(subject=alarm.subject, body=alarm.body, severity=Severity.CRITICAL)
        results = deliver(notice)
        delivered = tuple(d.channel for d in results if d.ok)
        if delivered or not results:  # taken, or nothing to retry: the line alone is the delivery
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({**last, key: now.isoformat()}), encoding='utf-8')
    line = {'event': EVENT, 'kind': alarm.kind, 'repo': alarm.repo, 'subject': alarm.subject}
    emit(json.dumps({**line, 'body': alarm.body, 'delivered': list(delivered), 'repeat': not due}), err=True)
    return delivered
