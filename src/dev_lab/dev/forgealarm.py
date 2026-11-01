"""A FAILURE NOBODY WATCHES MUST REACH A HUMAN -- the alarms ``forge serve`` raises from an unattended host.

A cron tick on a cluster login node logs into a file nobody reads. Five failures there are SILENT
unless raised: the forge refusing the stored credential (``auth``: a 401/403 that ``GET /user``
confirms even after git's refresh of an expired OAuth token, or none stored), a claim whose lease cannot be
renewed (``lease``: the forge refused the post, another owner
holds the claim now, or Slurm holds orphaned jobs), a cluster run that cannot advance (``run``), and
an account IDLE while work it could serve is pending (``idle``: nothing claimed, nothing in flight),
and a traffic jam: a candidate waiting past its class's bound (``starved``,
:mod:`dev_lab.dev.forgeschedule`), keyed by the candidate so each repeats on its own. One more is not
a failure but a PROMPT: on any host, an integration-queue row was written to its forge issue -- a lane
went READY, the integration tip became promotable, or a red needs routing (``integration``,
:mod:`dev_lab.dev.integrator`), keyed by the row so each new one is delivered at once. Two more are
origin's branch hygiene (:mod:`dev_lab.dev.branchprune`), raised by whichever host prunes: the merged
branches it deleted, or a prune that failed (``pruned``), and unmerged branches idle past the grace
(``stale-branch``), which are never deleted; and an account whose storage is still near its quota after
the retention pass (``storage``), and jobs on a cluster account that carry no session tag
(``untagged``), and a served repo's declared tool that no longer runs on its account (``needs``),
and a fleet gone dark -- every host of a platform stale, or a tick serving nothing
(``fleet``, :mod:`dev_lab.dev.forgefleet`), and a host PRESSED for disk, memory or CPU (``pressure``,
:mod:`dev_lab.dev.hostalarm`, ruling D54), keyed by which pressure so each repeats on its own.
And one is a fact about a UNIT, not a host: the same commit and context gave
two different results (``nondeterminism``, :func:`dev_lab.dev.forgeoutbox.flush`) -- the first stands.

EVERY ALARM IS ONE STRUCTURED LINE ON STDERR, ALWAYS: ``{"event": "lab_commons.forge.alarm", ...}``
(:data:`EVENT`). That line is the contract with a consumer that routes it (cc-config's Telegram/system
notify reads the tick's output); it carries no token, only the kind, the repo, a subject and a body.
WHERE THE FAMILY'S OWN CHANNELS ARE CONFIGURED THEY ARE USED TOO: the machine file's ``[alerts]``
table (:mod:`lab_commons.config`) drives :class:`dev_lab.supervise.alert.Notifier` -- Telegram,
email, webhook -- exactly as supervision does. No table, or none enabled, delivers nothing beyond the
line, and says so on the line (``"delivered": []``).
AND EVERY ALARM A TICK RAISES RIDES ON THAT HOST'S CARD (:mod:`dev_lab.dev.forgehosts`), which
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

from lab_commons.compute.durable import durable_text, read_table
from lab_commons.config import config_path, section
from lab_commons.log import emit

from dev_lab.dev import metrics
from dev_lab.supervise.alert import Notice, Notifier
from dev_lab.supervise.verdict import Severity

__all__ = [
    'AUTH',
    'EVENT',
    'FLEET',
    'IDLE',
    'INTEGRATION',
    'ISSUE_KINDS',
    'LEASE',
    'NEEDS',
    'NONDETERMINISM',
    'PRESSURE',
    'PRUNED',
    'RUN',
    'STALE_BRANCH',
    'STARVED',
    'STORAGE',
    'UNTAGGED',
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
#: A candidate waited past its class's bound (:mod:`dev_lab.dev.forgeschedule`).
STARVED: Final = 'starved'
#: An integration row this host created or changed on the forge (:mod:`dev_lab.dev.integrator`).
INTEGRATION: Final = 'integration'
#: The kinds kept as ONE forge issue per alarm, titled ``<kind>: <subject>``
#: (:func:`dev_lab.dev.forgeservesteps.raise_once` refuses any other) --
#: so ``forge tidy`` knows them as machine-kept.
ISSUE_KINDS: Final = (INTEGRATION, STARVED)
#: A host deleted merged idle origin branches, or failed to (:mod:`dev_lab.dev.branchprune`).
PRUNED: Final = 'pruned'
#: An UNMERGED origin branch sat idle past the declared grace; never deleted (:mod:`dev_lab.dev.branchprune`).
STALE_BRANCH: Final = 'stale-branch'
#: One unit gave two different results; the first stands (:func:`dev_lab.dev.forgeoutbox.flush`).
NONDETERMINISM: Final = 'nondeterminism'
#: Usage still at the quota pressure line after the retention pass (:mod:`dev_lab.dev.retention`).
STORAGE: Final = 'storage'
#: Jobs on a cluster account carry no session tag: they hold an unthrottled share (:mod:`lab_commons.hpc.allocation`).
UNTAGGED: Final = 'untagged'
#: A served repo's declared need no longer runs on its cluster account (:mod:`dev_lab.dev.hpchost.tick`).
NEEDS: Final = 'needs'
#: Every host of a platform is stale, or a tick serves nothing: once per episode (:mod:`dev_lab.dev.forgefleet`).
FLEET: Final = 'fleet'
#: A host pressed for disk, memory or CPU; *about* names which (:mod:`dev_lab.dev.hostalarm`, ruling D54).
PRESSURE: Final = 'pressure'


#: The alarms that are a prompt or a notice, not a failure: they are no host failure in the metrics log.
PROMPTS: Final = (INTEGRATION, STALE_BRANCH)


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
    return read_table(path)


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
    if due and alarm.kind not in PROMPTS:
        metrics.record(metrics.HOST_FAILURE, root=Path.cwd(), repo=alarm.repo, rule=alarm.kind, reason=alarm.kind)
    if due:
        notice = Notice(subject=alarm.subject, body=alarm.body, severity=Severity.CRITICAL)
        results = deliver(notice)
        delivered = tuple(d.channel for d in results if d.ok)
        if delivered or not results:  # taken, or nothing to retry: the line alone is the delivery
            durable_text(path, json.dumps({**last, key: now.isoformat()}))
    line = {'event': EVENT, 'kind': alarm.kind, 'repo': alarm.repo, 'subject': alarm.subject}
    emit(json.dumps({**line, 'body': alarm.body, 'delivered': list(delivered), 'repeat': not due}), err=True)
    return delivered


def main(argv: Sequence[str] | None = None) -> int:
    """``<kind> <repo> <subject> <body>``: sound one alarm from another process (the hpc deploy)."""
    try:
        kind, repo, subject, body = sys.argv[1:] if argv is None else argv
    except ValueError:
        emit('usage: python -m dev_lab.dev.forgealarm <kind> <repo> <subject> <body>', err=True)
        return 2
    sound(Alarm(kind, repo, subject, body))
    return 0


if __name__ == '__main__':
    sys.exit(main())
