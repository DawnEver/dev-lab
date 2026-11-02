"""Is the host PRESSED -- the D54 measurement (:mod:`dev_lab.supervise.pressure`) as a supervision component.

Supervision's own policy and :class:`~dev_lab.supervise.alert.Notifier` deliver each anomaly to the humans
(``[alerts]``); the reading is ALSO written to the host's alarm state (:mod:`dev_lab.supervise.hostalarms`),
so the agent hook on this host reads what supervision measured. Reports; never deletes.
"""

from __future__ import annotations

import socket
import time
from datetime import UTC, datetime

from dev_lab.supervise.component import CheckContext, Component
from dev_lab.supervise.components.resources import psutil_module
from dev_lab.supervise.hostalarms import AGENTS, SUPERVISE, memo, record, render, rows
from dev_lab.supervise.pressure import THRESHOLDS, Declared, measure
from dev_lab.supervise.verdict import Anomaly, CheckResult, Severity

__all__ = ['HostPressure']


class HostPressure(Component):
    """Disk, PSI, cgroup ``memory.events`` deltas, or a windowed psutil reading, against named thresholds.

    Config (the keys of the machine file's ``[pressure]``)::

        [components.host_pressure]
        enabled = true
        paths = ["/", "/srv/runner"]
        services = ["gitea-runner.service"]
        owner = "integrator"
        psi_memory_some_avg60 = 10

    """

    name = 'host_pressure'
    description = 'Disk, memory and CPU pressure, told to the agent that can clean up and to the humans'

    def check(self, ctx: CheckContext) -> CheckResult:
        """Measure, record the host state, and convict each finding -- from the READING, so a lock miss loses none.

        The baseline (the cgroup counters, the disk history) is the state file's SUPERVISE memo, one source: it
        advances only when :func:`record` wrote it, so a reading that missed the lock is seen again next cycle.
        """
        result = CheckResult()
        cadence = ctx.shared.get('cycle', {}).get('interval', THRESHOLDS['interval_s'])  # supervision's own
        declared = Declared.of({'interval_s': cadence, **ctx.config})
        measured = measure(declared, memo(SUPERVISE), now=time.time(), psutil=psutil_module)
        owner, host = str(ctx.config.get('owner', AGENTS)), socket.gethostname()
        state = record(measured, host=host, owner=owner, source=SUPERVISE)
        stamp = datetime.now(UTC).isoformat()
        mine = rows(measured, source=SUPERVISE, stamp=stamp) if state is None else state['alarms']
        result.metrics.update({k: v for k, v in measured.readings.items() if v is not None})
        for kind, alarm in mine.items():
            if alarm.get('source') != SUPERVISE:
                continue  # the forge tick's rows are sounded by the tick
            result.anomalies.append(
                Anomaly(
                    kind=f'pressure_{kind}',
                    severity=Severity.CRITICAL if alarm['severity'] == 'critical' else Severity.WARNING,
                    message=render(alarm, host=host, owner=owner),
                    signature=f'pressure:{kind}',
                )
            )
        return result
