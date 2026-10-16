"""A FAILURE NOBODY WATCHES MUST REACH A HUMAN -- the alarms ``forge serve`` raises from an unattended host.

A cron tick on a cluster login node logs into a file nobody reads. Five failures there are SILENT
unless raised: the forge refusing the stored credential (``auth``: a 401/403, an expired token, or none
stored), a claim whose lease cannot be renewed (``lease``: the forge refused the post, another owner
holds the claim now, or Slurm holds orphaned jobs), a cluster run that cannot advance (``run``), and
an account IDLE while work it could serve is pending (``idle``: nothing claimed, nothing in flight),
and a traffic jam: a candidate waiting past its class's bound (``starved``,
:mod:`lab_commons.dev.forgeschedule`), keyed by the candidate so each repeats on its own. One more is not
a failure but a PROMPT: on any host, an integration-queue row was written to its forge issue -- a lane
went READY, the integration tip became promotable, or a red needs routing (``integration``,
:mod:`lab_commons.dev.integrator`), keyed by the row so each new one is delivered at once. Two more are
origin's branch hygiene (:mod:`lab_commons.dev.branchprune`), raised by whichever host prunes: the merged
branches it deleted, or a prune that failed (``pruned``), and unmerged branches idle past the grace
(``stale-branch``), which are never deleted; and an account whose storage is still near its quota after
the retention pass (``storage``). And one is a fact about a UNIT, not a host: the same commit and context gave
two different results (``nondeterminism``, :func:`lab_commons.dev.forgeoutbox.flush`) -- the first stands.

EVERY ALARM IS ONE STRUCTURED LINE ON STDERR, ALWAYS: ``{"event": "lab_commons.forge.alarm", ...}``
(:data:`EVENT`). That line is the contract with a consumer that routes it (cc-config's Telegram/system
notify reads the tick's output); it carries no token, only the kind, the repo, a subject and a body.
WHERE THE FAMILY'S OWN CHANNELS ARE CONFIGURED THEY ARE USED TOO: the machine file's ``[alerts]``
table (:mod:`lab_commons.config`) drives :class:`lab_commons.supervise.alert.Notifier` -- Telegram,
email, webhook -- exactly as supervision does. No table, or none enabled, delivers nothing beyond the
line, and says so on the line (``"delivered": []``).
AND EVERY ALARM A TICK RAISES RIDES ON THAT HOST'S CARD (:mod:`lab_commons.dev.forgehosts`), which
``forge queue`` prints: the forge is the channel every machine reads, with or without ``[alerts]``.

A CRON TICK EVERY FIVE MINUTES MUST NOT PAGE EVERY FIVE MINUTES. A delivery of one ``(kind, repo)``
is repeated at most once per REPEAT WINDOW, which belongs to the person the alarms reach and so is
declared in the machine file's ``[alerts] repeat_hours`` (:func:`repeat_window`; absent: 6 h)
(state: ``forge-alarms.json`` beside the machine file);
the structured line is written every time, because it is the log, and says ``"repeat": true`` inside
that window so a consumer routes only the first. A channel that failed is retried on the next tick.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from lab_commons.config import config_path, section
from lab_commons.log import emit
from lab_commons.supervise.alert import Notice, Notifier
from lab_commons.supervise.verdict import Severity

__all__ = [
    'AUTH',
    'EVENT',
    'IDLE',
    'INTEGRATION',
    'ISSUE_KINDS',
    'LEASE',
    'NONDETERMINISM',
    'PRUNED',
    'RUN',
    'STALE_BRANCH',
    'STARVED',
    'STORAGE',
    'Alarm',
    'main',
    'repeat_window',
    'sound',
]  # fmt: skip

#: The ``event`` field of every alarm line -- what a consumer routes on.
EVENT: Final = 'lab_commons.forge.alarm'

#: The kinds (module docstring).
AUTH: Final = 'auth'
LEASE: Final = 'lease'
IDLE: Final = 'idle'
RUN: Final = 'run'
#: A candidate waited past its class's bound (:mod:`lab_commons.dev.forgeschedule`).
STARVED: Final = 'starved'
#: An integration row this host created or changed on the forge (:mod:`lab_commons.dev.integrator`).
INTEGRATION: Final = 'integration'
#: The kinds kept as ONE forge issue per alarm, titled ``<kind>: <subject>``
#: (:func:`lab_commons.dev.forgeserve.raise_once` refuses any other) -- so ``forge tidy`` knows them as machine-kept.
ISSUE_KINDS: Final = (INTEGRATION, STARVED)
#: A host deleted merged idle origin branches, or failed to (:mod:`lab_commons.dev.branchprune`).
PRUNED: Final = 'pruned'
#: An UNMERGED origin branch sat idle past the declared grace; never deleted (:mod:`lab_commons.dev.branchprune`).
STALE_BRANCH: Final = 'stale-branch'
#: One unit gave two different results; the first stands (:func:`lab_commons.dev.forgeoutbox.flush`).
NONDETERMINISM: Final = 'nondeterminism'
#: Usage still at the quota pressure line after the retention pass (:mod:`lab_commons.dev.retention`).
STORAGE: Final = 'storage'


def repeat_window(alerts: Mapping[str, Any]) -> timedelta:
    """How long one delivery waits before it is delivered again: ``[alerts] repeat_hours``, absent 6 h."""
    return timedelta(hours=float(alerts.get('repeat_hours', 6)))


@dataclass(frozen=True)
class Alarm:
    """One silent failure, named: its kind, the repo it concerns, a one-line subject and the remedy.

    *about* names WHICH thing of its kind (a starved candidate), so two of one kind repeat independently.
    """

    kind: str
    repo: str
    subject: str
    body: str
    about: str = ''


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
    """Write the alarm's line; deliver it through the configured channels unless delivered within the window.

    The window is :func:`repeat_window` of *alerts*.

    *alerts* is the ``[alerts]`` table (default: the machine file's); *send* replaces the notifier.
    Returns the channels that took it.
    """
    now = now or datetime.now(UTC)
    table = section('alerts') if alerts is None else alerts
    deliver = send or Notifier({'alerts': table}).send
    key = ':'.join(filter(None, (alarm.kind, alarm.repo, alarm.about)))
    path = _state()
    last = _last(path)
    due = key not in last or now - datetime.fromisoformat(last[key]) >= repeat_window(table)
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


def main(argv: Sequence[str] | None = None) -> int:
    """``<kind> <repo> <subject> <body>``: sound one alarm from a process that imports no dev code (the hpc deploy)."""
    try:
        kind, repo, subject, body = sys.argv[1:] if argv is None else argv
    except ValueError:
        emit('usage: python -m lab_commons.dev.forgealarm <kind> <repo> <subject> <body>', err=True)
        return 2
    sound(Alarm(kind, repo, subject, body))
    return 0


if __name__ == '__main__':
    sys.exit(main())
