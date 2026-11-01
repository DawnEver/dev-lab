"""Is the host PRESSED -- the D54 measurement (:mod:`dev_lab.supervise.pressure`) as a supervision component.

Supervision's own policy and :class:`~dev_lab.supervise.alert.Notifier` deliver each anomaly to the humans
(``[alerts]``); the reading is ALSO written to the host's alarm state (:mod:`dev_lab.supervise.hostalarms`),
so the agent hook on this host reads what supervision measured. Reports; never deletes.
"""

from __future__ import annotations

import socket
import time

from dev_lab.supervise.component import CheckContext, Component
from dev_lab.supervise.components.resources import psutil_module
from dev_lab.supervise.hostalarms import AGENTS, record, render
from dev_lab.supervise.pressure import Declared, measure
from dev_lab.supervise.verdict import Anomaly, CheckResult, Severity

__all__ = ['HostPressure']


class HostPressure(Component):
    """Disk, PSI, cgroup ``memory.events`` deltas, or a windowed psutil reading, against named thresholds.

    Config (the keys of the machine file's ``[pressure]``)::

        [components.host_pressure]
        enabled = true
        paths = ["/", "/home/runner"]
        services = ["gitea-runner.service"]
        owner = "integrator"
        psi_memory_some_avg60 = 10

    """

    name = 'host_pressure'
    description = 'Disk, memory and CPU pressure, told to the agent that can clean up and to the humans'

    def check(self, ctx: CheckContext) -> CheckResult:
        """Measure, record the host state, and convict each finding."""
        result = CheckResult()
        measured = measure(Declared.of(ctx.config), ctx.state.get('memo', {}), now=time.time(), psutil=psutil_module)
        ctx.state['memo'] = measured.memo
        owner = str(ctx.config.get('owner', AGENTS))
        state = record(measured, host=socket.gethostname(), owner=owner)
        result.metrics.update({k: v for k, v in measured.readings.items() if v is not None})
        for kind, alarm in state['alarms'].items():
            result.anomalies.append(
                Anomaly(
                    kind=f'pressure_{kind}',
                    severity=Severity.CRITICAL if alarm['severity'] == 'critical' else Severity.WARNING,
                    message=render(alarm, host=state['host'], owner=owner),
                    signature=f'pressure:{kind}',
                )
            )
        return result
