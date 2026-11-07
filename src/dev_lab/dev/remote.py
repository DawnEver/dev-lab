"""THE ONE SSH TRANSPORT the remote doors share: how a command reaches a host, never what it runs or where.

User ruling 2026-11-07: ssh has two kinds of target, and each has its own honestly named door --
:mod:`dev_lab.dev.hpcaccount` (a cluster account: deploy, tick, cron) and :mod:`dev_lab.dev.opsserver` (a server
the integrator deploys: the ops door's fixed verbs). Both build their argv and start it here, so the ssh options,
the quoting and the detached launch exist once. A hand-written ssh WRITE to a remote host is refused by the deny
row ``REMOTE-WRITE-THROUGH-A-DOOR``, which names those two doors; read-only ssh stays open.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from collections.abc import Sequence
from typing import IO, Any, Final

import lab_commons.launch as _door

__all__ = ['CONNECT_TIMEOUT_S', 'detached', 'run', 'ssh_argv']

#: How long ssh waits for a host before it gives up.
CONNECT_TIMEOUT_S: Final = 20


def ssh_argv(target: str, command: str, *, batch: bool) -> list[str]:
    """The ssh argv running *command* (a POSIX shell line) as a login shell on *target* (``user@host``).

    *batch* true never prompts (a key-only account: a cluster); false allocates a terminal for an account whose
    login asks a second factor (a server's ops account: key AND a one-time code typed by the user).
    """
    mode = ['-o', 'BatchMode=yes'] if batch else ['-t']
    return ['ssh', *mode, '-o', f'ConnectTimeout={CONNECT_TIMEOUT_S}', target, f'bash -lc {shlex.quote(command)}']


def detached(argv: Sequence[str], log: IO[Any]) -> object:
    """Start *argv* detached from this session, everything it prints into *log*; returns the process."""
    # The door adds CREATE_NO_WINDOW; DETACHED_PROCESS would leave the windowless console the serve child inherits.
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
    return _door.popen(
        list(argv),
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=flags,
        start_new_session=os.name != 'nt',
    )


def run(argv: Sequence[str], *, timeout_s: float) -> int:
    """Run *argv* in the foreground, attached to this terminal (a second factor is typed there); its exit code."""
    return _door.run(list(argv), check=False, timeout=timeout_s).returncode
