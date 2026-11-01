"""ONE PER-HOST ALARM STATE -- what this host is pressed by now, read by every channel that tells someone (D54).

``host-alarms.json`` sits BESIDE THE MACHINE FILE, where this host's other state lives (``forge-alarms.json``,
:mod:`dev_lab.dev.forgealarm`). One writer per reading (:func:`record`, called by the forge tick and by the
supervision component), many readers: the agent hook, post-commit, the forge alarm, supervision's notifier.

Each alarm carries its kind, severity, first and last seen, the measurement and an ACTIONABLE remedy: the
biggest consumers and the cleanup doors (:data:`dev_lab.supervise.pressure.DOORS`). It also names its OWNER
(``[pressure] owner``): a workstation's alarms are for its agents, the Gitea host's for the integrator.
:func:`render` is THE formatter -- the hook and post-commit print its lines, the notifier sends them.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from lab_commons.compute.durable import durable_text, read_table
from lab_commons.config import config_path

from dev_lab.supervise.pressure import DOORS, Measured

__all__ = ['AGENTS', 'INTEGRATOR', 'STATE_NAME', 'lines', 'read', 'record', 'render', 'state_path']

#: The file's name, beside the machine file.
STATE_NAME: Final = 'host-alarms.json'

#: The owners an alarm may name (``[pressure] owner``): this host's agents, or the integrator (the Gitea host).
AGENTS: Final = 'agents'
INTEGRATOR: Final = 'integrator'


def state_path() -> Path:
    """The alarm state of this host, beside the machine file."""
    return config_path().parent / STATE_NAME


def read(path: Path | None = None) -> dict[str, Any]:
    """The state at *path* (default :func:`state_path`): ``{}`` when absent or unreadable."""
    return read_table(path or state_path())


def record(
    measured: Measured, *, host: str, owner: str = AGENTS, now: datetime | None = None, path: Path | None = None
) -> dict[str, Any]:
    """Write *measured* as the host's state: a held alarm keeps its first-seen, a cleared one leaves."""
    path = path or state_path()
    stamp = (now or datetime.now(UTC)).isoformat()
    before = read(path).get('alarms', {})
    alarms = {
        one.kind: {
            'kind': one.kind,
            'severity': one.severity,
            'first_seen': before.get(one.kind, {}).get('first_seen', stamp),
            'last_seen': stamp,
            'measurement': one.measurement,
            'consumers': list(one.consumers),
            'doors': list(DOORS),
        }
        for one in measured.findings
    }
    state = {'host': host, 'owner': owner, 'measured': stamp, 'alarms': alarms,
             'readings': measured.readings, 'memo': measured.memo}  # fmt: skip
    durable_text(path, json.dumps(state, indent=1, sort_keys=True))
    return state


def render(alarm: Mapping[str, Any], *, host: str, owner: str) -> str:
    """One alarm as the text every channel carries: what, since when, who acts, the consumers, the doors."""
    who = 'the integrator' if owner == INTEGRATOR else 'an agent on this host'
    since = f'since {alarm["first_seen"]}, last {alarm["last_seen"]}'
    severity = str(alarm['severity']).upper()
    body = [f'HOST-PRESSURE {severity} on {host} -- {alarm["measurement"]} ({since}); for {who} to clean up']
    if alarm.get('consumers'):
        body += ['biggest consumers:', *(f'  {c}' for c in alarm['consumers'])]
    body += ['cleanup doors:', *(f'  {d}' for d in alarm.get('doors', DOORS))]
    return '\n'.join(body)


def lines(state: Mapping[str, Any], kinds: set[str] | None = None) -> list[str]:
    """Every alarm of *state* (only *kinds* when given), rendered; ``[]`` when the host is not pressed."""
    host, owner = str(state.get('host', '?')), str(state.get('owner', AGENTS))
    alarms = state.get('alarms', {})
    return [render(alarms[k], host=host, owner=owner) for k in sorted(alarms) if kinds is None or k in kinds]
