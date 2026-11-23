"""SSHHOLD PROBE: is this machine's KEY admitted, asked with no code -- before a code is read for a key + code host.

Measured 2026-11-22: ``sshhold open <user@host>`` to a host wanting a public key AND a second factor spent the
user's code on ``Permission denied (publickey)``: the key had never been placed on the account, and the code was
read first. ssh tells the two apart without any code. A BatchMode login (no prompt can be answered) to such a host
ends ``Permission denied (keyboard-interactive)`` when the key WAS accepted and the code is what is missing
(:data:`WANTS_CODE`, the distinction a plan's preflight already reads), and ``Permission denied (publickey)`` when
the key itself was refused (:func:`key_refused`).

:func:`probe` runs that one attempt through the SAME ssh words the open will use (its route and declared host key).
Only a refused key refuses; anything else it cannot judge (a network fault, a host that admits the login outright)
is left to the open, as before.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Sequence
from typing import Final

import lab_commons.launch as _door

from dev_lab.dev.sshholdwire import HoldRefused

__all__ = ['KEYS_DOOR', 'WANTS_CODE', 'key_refused', 'probe']

#: An ssh login the host refused for want of a code: the key (when one is needed) was accepted.
WANTS_CODE: Final = re.compile(r'Permission denied \((?:[\w-]+,)*(?:keyboard-interactive|password)')
_DENIED: Final = re.compile(r'Permission denied \(([\w,-]+)\)')
_SSH_FAILED: Final = 255
_PROBE_S: Final = 60.0

#: Where an account's login keys are managed -- the door of a refused key.
KEYS_DOOR: Final = (
    "the account's login keys are derived from the hosts config: add this machine's [dev] client_keys there, then "
    '`python -m dev_lab.dev.hpcaccount keys <user@host> --hosts <hosts-config>/hosts` from a machine that already '
    'reaches the account; on a cluster whose keys are managed in its portal, add the key in the portal'
)

#: Runs one argv captured (``subprocess.run``'s shape).
type Run = Callable[..., subprocess.CompletedProcess[str]]


def key_refused(said: str) -> str:
    """The denial line of ssh when it refused the KEY (``publickey`` offered, no code method left); else ``''``."""
    found = _DENIED.search(said)
    if found is None or WANTS_CODE.search(said) or 'publickey' not in found.group(1).split(','):
        return ''
    return found.group(0)


def probe(dest: str, ssh: Sequence[str], *, run: Run | None = None) -> None:
    """Refuse, with no code read, a *dest* that does not admit this machine's key; *ssh* are the open's own words.

    Raises:
        HoldRefused: ssh refused the public key -- naming ssh's line and :data:`KEYS_DOOR`.

    """
    argv = [*ssh, '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', dest, 'true']
    try:
        done = (run or _door.run)(
            argv, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=_PROBE_S, check=False,
            stdin=subprocess.DEVNULL,
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired):
        return  # not judged here: the open says what ssh says
    denied = key_refused(f'{done.stdout}{done.stderr}') if done.returncode == _SSH_FAILED else ''
    if denied:
        msg = (f"{dest} does not admit this machine's public key (ssh, with no code: {denied}); no code was read "
               f'and none is used -- {KEYS_DOOR}; then open again')  # fmt: skip
        raise HoldRefused(msg)
