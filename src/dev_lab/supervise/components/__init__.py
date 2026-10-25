"""The components this build ships, and the roster a target adds to.

A ROSTER, NOT A DIRECTORY WALK. The predecessor found its components by walking a directory and
instantiating every ``Component`` subclass it found, so what ran depended on which files happened to
be present -- and a file left behind by a branch switch silently joined the supervision. Here the
list below IS the shipped set, and a target's own module states its contributions in a
``COMPONENTS`` list of its own.

Grouped by family rather than one file per probe: ``health`` asks whether something answers and
whether its answer is what it should be, ``resources`` asks whether the box is running out of
anything, ``progress`` asks whether a long job is still moving, and ``deploy`` asks whether a
release is safe to activate. Four questions, four files.
"""

from __future__ import annotations

from dev_lab.supervise.component import Component
from dev_lab.supervise.components.deploy import Deploy
from dev_lab.supervise.components.health import Heartbeat, HttpHealth, ShellProbe
from dev_lab.supervise.components.progress import ProgressTracker
from dev_lab.supervise.components.resources import DiskUsage, LogScanner, ProcessMonitor

__all__ = [
    'COMPONENTS',
    'Deploy',
    'DiskUsage',
    'Heartbeat',
    'HttpHealth',
    'LogScanner',
    'ProcessMonitor',
    'ProgressTracker',
    'ShellProbe',
]

#: What this build ships, as INSTANCES. A target may declare its own component under one of these
#: names to replace it, which the registry does explicitly rather than by a silent last-writer-wins.
COMPONENTS: list[Component] = [
    HttpHealth(),
    ShellProbe(),
    Heartbeat(),
    DiskUsage(),
    ProcessMonitor(),
    LogScanner(),
    ProgressTracker(),
    Deploy(),
]
