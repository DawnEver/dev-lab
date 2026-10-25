"""The systemd notify protocol: one datagram, a few lines of text, no dependency.

WHAT IT IS FOR. A service manager can answer "is this process alive" by asking the OS, and that is
enough for a process that crashes -- it is gone, the manager sees it, and ``Restart=always`` brings
it back. It is NOT enough for a process that is alive and has stopped working. A wedged daemon holds
its pid, answers ``is-active`` with ``active``, and supervises nothing, and no amount of watching
the process will say so.

``WatchdogSec=`` is the manager's answer to that half: the service promises to check in, and failing
to check in is treated as a failure. The check-in is a datagram to the socket the manager left in
``$NOTIFY_SOCKET``.

THERE IS NO sd_notify BINDING HERE AND THERE WILL NOT BE ONE. The protocol is a text datagram; the
family's rule is that a runtime dependency has to earn itself, and a C library binding to write four
lines to a unix socket does not. This module is the whole of it.

NO MANAGER IS NOT A FAILURE. A foreground run, a container, a test -- all have no ``NOTIFY_SOCKET``,
and every function here answers False rather than raising. A caller that has to know the difference
between "told the manager" and "there was nobody to tell" gets it from the return value; a caller
that does not can ignore it. What must never happen is the third thing: reporting that a check-in
went when there was nowhere to send it.
"""

from __future__ import annotations

import os
import socket
from typing import Final

__all__ = ['NOTIFY_SOCKET', 'ready', 'watchdog']

#: Where the manager leaves the socket it will accept notifications on.
NOTIFY_SOCKET: Final = 'NOTIFY_SOCKET'

#: What an abstract socket's address starts with, as systemd spells it.
_ABSTRACT: Final = '@'


def _send(payload: str) -> bool:
    """Send one datagram to the manager's notify socket.

    Args:
        payload: the protocol line, without its trailing newline.

    Returns:
        True when a manager was told, False when there is nothing to tell.

    """
    address = os.environ.get(NOTIFY_SOCKET, '')
    if not address:
        return False
    # AN ABSTRACT SOCKET IS SPELLED WITH A LEADING `@` AND ADDRESSED WITH A LEADING NUL. systemd
    # writes `@/org/freedesktop/systemd1/notify` for one, and passing that string through unchanged
    # addresses a PATH that does not exist -- silently, because a datagram socket that cannot reach
    # its destination has nowhere to report that to.
    if address.startswith(_ABSTRACT):
        address = '\0' + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.sendto(payload.encode('utf-8'), address)
    except (OSError, AttributeError):
        # `AttributeError` IS NOT DEFENSIVE PADDING AND IS NOT A STAND-IN FOR A REAL FAILURE.
        # `socket.AF_UNIX` does not exist on every platform this kit is developed on -- measured on
        # this one, where the lookup raises before any socket is made. A development box has no
        # service manager either, so "there is nobody to tell" is the TRUE answer there, and the
        # alternative is that every local run of the daemon dies inside `ready()` for a reason that
        # has nothing to do with the deployment it was checking.
        return False
    return True


def ready() -> bool:
    """Tell the manager this process has finished starting.

    Only meaningful under ``Type=notify``, where the manager is waiting for exactly this before it
    considers the service started. Harmless everywhere else.

    Returns:
        True when a manager was told.

    """
    return _send('READY=1')


def watchdog() -> bool:
    """Tell the manager the loop is still running.

    Called once per cycle, which is why the unit's ``WatchdogSec=`` must be a multiple of the cycle
    interval: a timeout shorter than one cycle reports a healthy daemon as a wedged one.

    Returns:
        True when a manager was told.

    """
    return _send('WATCHDOG=1')
