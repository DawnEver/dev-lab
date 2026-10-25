"""Reaching a service's process through whatever manages it.

The deploy engine asks this package four questions and never asks what the answers come from, which
is what keeps a deployment's algebra -- validate, activate, verify, roll back -- the same on a host
with systemd and on one without.

ONE IMPLEMENTATION TODAY, SYSTEMD, and that is deliberate rather than unfinished. The seam's job is
to keep ``systemctl`` out of the deploy engine, and a seam is proven by the engine running against
something else -- which a test double does, in the suite, on every change. A second production
manager for a host nothing deploys to yet would be an abstraction for a need that does not exist;
adding one later is four methods and no change to any caller.
"""

from __future__ import annotations

from dev_lab.supervise.process.base import ProcessManager, Ran
from dev_lab.supervise.process.systemd import SystemdProcessManager, subprocess_runner

__all__ = [
    'MANAGERS',
    'ProcessManager',
    'Ran',
    'SystemdProcessManager',
    'manager_for',
    'subprocess_runner',
]

#: Every manager this build can build, by the name a config uses. An explicit table rather than a
#: registry with lookup by string: the kit carries no reflection, so a name that is not here is a
#: refusal rather than an import that might work.
MANAGERS: dict[str, type[SystemdProcessManager]] = {'systemd': SystemdProcessManager}


def manager_for(name: str) -> ProcessManager:
    """Return the process manager a config named.

    Args:
        name: the manager's name, e.g. ``systemd``.

    Returns:
        A manager for that name.

    Raises:
        ValueError: nothing here answers to that name, and the message lists what does -- a
            supervisor that silently picked a default would manage the wrong thing quietly.

    """
    factory = MANAGERS.get(name)
    if factory is None:
        known = ', '.join(sorted(MANAGERS))
        msg = f'no process manager named {name!r}; this build knows: {known}'
        raise ValueError(msg)
    return factory()
