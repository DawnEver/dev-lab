"""A PRESSED HOST TELLS ITS AGENTS, ABOVE ALL, AND ITS HUMANS (user ruling D54, 2026-11-01).

The host's alarm state (:mod:`dev_lab.supervise.hostalarms`, measured by :mod:`dev_lab.supervise.pressure`)
reaches three readers, all through :func:`~dev_lab.supervise.hostalarms.lines` -- one formatter:

* THE AGENT (``hook``): a Claude Code ``PostToolUse`` (shell tools) and ``UserPromptSubmit`` hook
  (:data:`dev_lab.dev.agent_guard.WIRING`) injects each alarm as additional context -- ONE reminder per alarm
  per session per :data:`REMIND_EVERY`, so an agent on a pressed host hears it and is not drowned by it;
* the COMMIT (``check``): the ``host-pressure`` post-commit row prints the same lines -- a secondary channel;
* THE HUMANS (:func:`step`, each ``forge serve`` tick): the host is measured and each alarm is sounded as a
  ``pressure`` alarm (:mod:`dev_lab.dev.forgealarm`) -- the structured line, the host card ``forge queue``
  prints, and the existing :class:`~dev_lab.supervise.alert.Notifier` over the machine file's ``[alerts]``;
* THE CHANNEL TEST (``test``, user ruling D55): one INFO notice, rendered by the same formatter, through the real
  Notifier (the machine file's ``[alerts]``, or ``--supervise-config PATH``'s for supervision's channels); it
  prints only each channel's result and message id, never a reply body or a credential.

OWNERSHIP (``[pressure] owner``): a workstation's alarms are for its agents; the Gitea host declares
``integrator``, and its alarms name the integrator, who reads them on the host card. An account's QUOTA stays
the ``storage`` alarm (:mod:`dev_lab.dev.retention`): this measures disks, never a quota. Nothing is deleted.
"""

from __future__ import annotations

import getpass
import json
import re
import socket
import sys
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final, TextIO

from lab_commons.compute.durable import durable_text, read_table
from lab_commons.config import section
from lab_commons.log import emit

from dev_lab.dev.forgealarm import PRESSURE, Alarm
from dev_lab.supervise import hostalarms
from dev_lab.supervise.alert import Delivery, Notice, Notifier
from dev_lab.supervise.components.resources import psutil_module
from dev_lab.supervise.config import load_config
from dev_lab.supervise.pressure import Declared, Measured, measure
from dev_lab.supervise.verdict import Severity

__all__ = ['CHANNELS', 'REMINDED_NAME', 'REMIND_EVERY', 'TEST_AGAIN', 'channel_test', 'due', 'hook', 'main', 'step']

#: The channels :class:`~dev_lab.supervise.alert.Notifier` delivers through, as ``[alerts]`` names them.
CHANNELS: Final = ('email', 'telegram', 'webhook')

#: One reminder per alarm per agent session within this window (D54).
REMIND_EVERY: Final = timedelta(minutes=30)

#: When each session was last reminded of each alarm, beside the state.
REMINDED_NAME: Final = 'host-alarms-reminded.json'


def due(
    state: Mapping[str, Any], session: str, reminded: Mapping[str, str], now: datetime
) -> tuple[set[str], dict[str, str]]:
    """The alarm kinds *session* is due a reminder of, and the reminded table after reminding them.

    A reminder older than the window is dropped, so the table never outgrows the alarms of the last half hour.
    """
    kept = {k: v for k, v in reminded.items() if _fresh(v, now)}
    kinds = {kind for kind in state.get('alarms', {}) if f'{session}|{kind}' not in kept}
    return kinds, {**kept, **{f'{session}|{kind}': now.isoformat() for kind in kinds}}


def _fresh(stamp: object, now: datetime) -> bool:
    """Whether *stamp* is a reminder inside the window; an unreadable or naive one is not (it is dropped)."""
    try:
        return now - datetime.fromisoformat(str(stamp)) < REMIND_EVERY
    except (TypeError, ValueError):
        return False


def hook(stdin: TextIO, *, now: datetime | None = None, state_path: Path | None = None) -> int:
    """The agent hook: the alarms this session is due, as additional context; silent otherwise; always 0."""
    try:
        payload = json.load(stdin)
    except ValueError:
        payload = {}
    payload = payload if isinstance(payload, dict) else {}
    path = state_path or hostalarms.state_path()
    now = now or datetime.now(UTC)
    state = hostalarms.read(path)
    state = {**state, 'alarms': hostalarms.current(state, now)}  # a stopped writer's rows are stale: told to nobody
    if not state['alarms']:
        return 0
    remembered = path.with_name(REMINDED_NAME)
    kinds, reminded = due(state, str(payload.get('session_id', '')), read_table(remembered), now)
    if not kinds:
        return 0
    try:
        durable_text(remembered, json.dumps(reminded))
    except OSError:
        return 0  # a reminder that cannot be rate-limited is not given: never a storm
    event = str(payload.get('hook_event_name') or 'PostToolUse')
    said = '\n\n'.join(hostalarms.lines(state, kinds))
    emit(json.dumps({'hookSpecificOutput': {'hookEventName': event, 'additionalContext': said}}))
    return 0


def step(
    root: Path,
    repo: str,
    *,
    who: str,
    alarm: Callable[[Alarm], object],
    table: Mapping[str, Any] | None = None,
    measuring: Callable[..., Measured] = measure,
) -> dict[str, Any]:
    """One tick's reading: measure ``[pressure]`` (default: *root*'s disk), record the state, sound each alarm."""
    table = section('pressure') if table is None else table
    cadence = float(section('schedule').get('tick_minutes', 5)) * 60  # the tick reads at its own cadence
    declared = Declared.of({'paths': [str(root)], 'interval_s': cadence, **table})
    previous = hostalarms.memo(hostalarms.FORGE)
    owner = str(table.get('owner', hostalarms.AGENTS))
    measured = measuring(declared, previous, now=time.time(), psutil=psutil_module)
    state = hostalarms.record(measured, host=who, owner=owner, source=hostalarms.FORGE)
    # A LOCK MISS LOSES NOTHING: the findings are sounded from the reading itself, and the memo (the cgroup
    # baseline) did not advance, so the next tick sees the same delta again.
    mine = (
        hostalarms.rows(measured, source=hostalarms.FORGE, stamp=datetime.now(UTC).isoformat())
        if state is None
        else {k: v for k, v in state['alarms'].items() if v.get('source') == hostalarms.FORGE}
    )
    for kind, one in sorted(mine.items()):
        subject = f'{who} is pressed: {one["measurement"]}' + (
            ' (integrator)' if owner == hostalarms.INTEGRATOR else ''
        )
        alarm(Alarm(PRESSURE, repo, subject, hostalarms.render(one, host=who, owner=owner), about=kind))
    return state or {}


#: What a message id may look like (an int, a UUID): anything else is not printed.
_ID: Final = re.compile(r'[A-Za-z0-9-]{1,64}')

#: How the test notice is sent again -- printed in its own body.
TEST_AGAIN: Final = 'python -m dev_lab.dev.hostalarm test'


def _alerts(args: list[str]) -> Mapping[str, Any]:
    """The ``[alerts]`` table: the machine file's, or a supervise config's (``--supervise-config PATH``)."""
    if args[:1] == ['--supervise-config'] and len(args) > 1:
        return load_config(Path(args[1])).get('alerts', {})
    return section('alerts')


def channel_test(
    alerts: Mapping[str, Any],
    *,
    send: Callable[[Notice], list[Delivery]] | None = None,
    now: datetime | None = None,
    host: str | None = None,
    sender: str | None = None,
) -> int:
    """THE ALERT TEST DOOR (user ruling D55): ONE info notice through the real Notifier; per-channel results only.

    Prints ``<channel> ok|FAILED id=<message id>`` per channel -- the message id parsed out of the reply, never the
    reply itself (Telegram echoes the chat id) and never a credential. Exit 0 when every enabled channel took it.
    """
    here = host or socket.gethostname()
    channels = [name for name in CHANNELS if alerts.get(name, {}).get('enabled')]
    subject, body = hostalarms.test_notice(
        host=here,
        sender=sender or f'{getpass.getuser()}@{here} via {TEST_AGAIN}',
        channels=channels,
        again=TEST_AGAIN,
        now=now or datetime.now(UTC),
    )
    results = (send or Notifier({'alerts': alerts}).send)(Notice(subject, body, Severity.INFO))
    if not results:
        emit('host-alarm test: no channel is enabled in [alerts]; nothing was sent')
        return 1
    for one in results:
        emit(f'{one.channel} {"ok" if one.ok else "FAILED"} id={_message_id(one.detail) if one.ok else "-"}')
    return 0 if all(one.ok for one in results) else 1


def _message_id(detail: str) -> str:
    """The id a channel's reply names (Telegram ``result.message_id``, Resend ``id``), else ``-``."""
    try:
        reply = json.loads(detail)
    except ValueError:
        return '-'
    if not isinstance(reply, dict):
        return '-'
    result = reply.get('result')
    found = result.get('message_id') if isinstance(result, dict) else reply.get('id')
    return str(found) if isinstance(found, (int, str)) and _ID.fullmatch(str(found)) else '-'


def _measure_now(root: Path) -> int:
    """READ-ONLY: measure ``[pressure]`` now and print it; nothing is recorded, so no tick's baseline moves."""
    table = section('pressure')
    declared = Declared.of({'paths': [str(root)], **table})
    measured = measure(declared, hostalarms.memo(hostalarms.FORGE), now=time.time(), psutil=psutil_module)
    state = {
        'host': socket.gethostname(),
        'owner': str(table.get('owner', hostalarms.AGENTS)),
        'alarms': hostalarms.rows(measured, source='measure', stamp=datetime.now(UTC).isoformat()),
    }
    for line in hostalarms.lines(state) or ['host-pressure: not pressed']:
        emit(line)
    return 0


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None) -> int:
    """``hook`` (the agent hook; default), ``check`` (post-commit lines), ``measure`` (read now), ``test`` (D55)."""
    args = list(sys.argv[1:] if argv is None else argv)
    arm = args[0] if args else 'hook'
    if arm == 'hook':
        return hook(stdin or sys.stdin)
    if arm == 'check':
        for line in hostalarms.lines(hostalarms.read(), now=datetime.now(UTC)):
            emit(line)
        return 0
    if arm == 'measure':
        return _measure_now(Path.cwd())
    if arm == 'test':
        return channel_test(_alerts(args[1:]))
    emit('usage: python -m dev_lab.dev.hostalarm [hook|check|measure|test [--supervise-config PATH]]', err=True)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
