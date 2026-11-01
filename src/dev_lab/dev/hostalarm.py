"""A PRESSED HOST TELLS ITS AGENTS, ABOVE ALL, AND ITS HUMANS (user ruling D54, 2026-11-01).

The host's alarm state (:mod:`dev_lab.supervise.hostalarms`, measured by :mod:`dev_lab.supervise.pressure`)
reaches three readers, all through :func:`~dev_lab.supervise.hostalarms.lines` -- one formatter:

* THE AGENT (``hook``): a Claude Code ``PostToolUse`` (shell tools) and ``UserPromptSubmit`` hook
  (:data:`dev_lab.dev.agent_guard.WIRING`) injects each alarm as additional context -- ONE reminder per alarm
  per session per :data:`REMIND_EVERY`, so an agent on a pressed host hears it and is not drowned by it;
* the COMMIT (``check``): the ``host-pressure`` post-commit row prints the same lines -- a secondary channel;
* THE HUMANS (:func:`step`, each ``forge serve`` tick): the host is measured and each alarm is sounded as a
  ``pressure`` alarm (:mod:`dev_lab.dev.forgealarm`) -- the structured line, the host card ``forge queue``
  prints, and the existing :class:`~dev_lab.supervise.alert.Notifier` over the machine file's ``[alerts]``.

OWNERSHIP (``[pressure] owner``): a workstation's alarms are for its agents; the Gitea host declares
``integrator``, and its alarms name the integrator, who reads them on the host card. An account's QUOTA stays
the ``storage`` alarm (:mod:`dev_lab.dev.retention`): this measures disks, never a quota. Nothing is deleted.
"""

from __future__ import annotations

import json
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
from dev_lab.supervise.components.resources import psutil_module
from dev_lab.supervise.pressure import Declared, Measured, measure

__all__ = ['REMINDED_NAME', 'REMIND_EVERY', 'due', 'hook', 'main', 'step']

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
    kept = {k: v for k, v in reminded.items() if now - datetime.fromisoformat(v) < REMIND_EVERY}
    kinds = {kind for kind in state.get('alarms', {}) if f'{session}|{kind}' not in kept}
    return kinds, {**kept, **{f'{session}|{kind}': now.isoformat() for kind in kinds}}


def hook(stdin: TextIO, *, now: datetime | None = None, state_path: Path | None = None) -> int:
    """The agent hook: the alarms this session is due, as additional context; silent otherwise; always 0."""
    try:
        payload = json.load(stdin)
    except ValueError:
        payload = {}
    payload = payload if isinstance(payload, dict) else {}
    path = state_path or hostalarms.state_path()
    state = hostalarms.read(path)
    if not state.get('alarms'):
        return 0
    remembered = path.with_name(REMINDED_NAME)
    kinds, reminded = due(state, str(payload.get('session_id', '')), read_table(remembered), now or datetime.now(UTC))
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
    declared = Declared.of({'paths': [str(root)], **table})
    previous = hostalarms.read().get('memo', {})
    owner = str(table.get('owner', hostalarms.AGENTS))
    state = hostalarms.record(
        measuring(declared, previous, now=time.time(), psutil=psutil_module), host=who, owner=owner
    )
    for kind, one in sorted(state['alarms'].items()):
        subject = f'{who} is pressed: {one["measurement"]}' + (
            ' (integrator)' if owner == hostalarms.INTEGRATOR else ''
        )
        alarm(Alarm(PRESSURE, repo, subject, hostalarms.render(one, host=who, owner=owner), about=kind))
    return state


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None) -> int:
    """``hook`` (the agent hook; the default), ``check`` (post-commit: the lines; 0), ``measure`` (read now)."""
    args = list(sys.argv[1:] if argv is None else argv)
    arm = args[0] if args else 'hook'
    if arm == 'hook':
        return hook(stdin or sys.stdin)
    if arm == 'check':
        for line in hostalarms.lines(hostalarms.read()):
            emit(line)
        return 0
    if arm == 'measure':
        state = step(Path.cwd(), '', who=socket.gethostname(), alarm=lambda _one: None)
        for line in hostalarms.lines(state) or ['host-pressure: not pressed']:
            emit(line)
        return 0
    emit('usage: python -m dev_lab.dev.hostalarm [hook|check|measure]', err=True)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
