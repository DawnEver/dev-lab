"""SSHHOLD PROBE: is this machine's KEY admitted, asked with no code -- before a code is read for a key + code host.

Measured 2026-11-22: ``sshhold open <user@host>`` to a host wanting a public key AND a second factor spent the
user's code on ``Permission denied (publickey)``: the key had never been placed on the account, and the code was
read first. ssh tells the two apart without any code. A BatchMode login (no prompt can be answered) to such a host
ends ``Permission denied (keyboard-interactive)`` when the key WAS accepted and the code is what is missing
(:data:`WANTS_CODE`, the distinction a plan's preflight already reads), and ``Permission denied (publickey)`` when
the key itself was refused (:func:`key_refused`).

:func:`probe` runs that one attempt, verbose, through the SAME ssh words and binary the open will use (its route,
declared host key, PATH's ssh). It PROVES what the code needs -- ssh's ``Authenticated using "publickey" with
partial success`` for the destination itself -- and refuses anything short of it (measured 2026-11-24: an empty
``Permission denied ()`` passed the old refused-key-only check and three codes were read on no evidence).
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Sequence
from typing import Final

import lab_commons.launch as _door

from dev_lab.dev.sshholdwire import HoldRefused, resolved

__all__ = ['KEYS_DOOR', 'KEY_ONLY_DOOR', 'WANTS_CODE', 'key_refused', 'probe']

#: An ssh login the host refused for want of a code: the key (when one is needed) was accepted.
WANTS_CODE: Final = re.compile(r'Permission denied \((?:[\w-]+,)*(?:keyboard-interactive|password)')
_DENIED: Final = re.compile(r'Permission denied \(([\w,-]+)\)')
_DENIED_ANY: Final = re.compile(r'Permission denied \([\w,-]*\)')
#: ssh -v's proof that the key was accepted and a further method is wanted (OpenSSH 8.9+ names the method).
_PARTIAL: Final = re.compile(r'Authenticated (?:using "publickey" )?with partial success')
#: The identity file ssh offered -- the path alone, never the key type or fingerprint after it.
_OFFERED: Final = re.compile(r'Offering public key: (.+?) [A-Z0-9-]+ SHA256:')
_PROBE_S: Final = 60.0

#: Where an account's login keys are managed -- the door of a refused key.
KEYS_DOOR: Final = (
    "the account's login keys are derived from the hosts config: add this machine's [dev] client_keys there, then "
    '`python -m dev_lab.dev.hpcaccount keys <user@host> --hosts <hosts-config>/hosts` from a machine that already '
    'reaches the account; on a cluster whose keys are managed in its portal, add the key in the portal'
)

#: The doors of a key-only account (measured 2026-11-23: an open there asked a code and died reading it).
KEY_ONLY_DOOR: Final = (
    'reach it through the hpcaccount doors, which ride the rate-limited key ssh: read it with '
    '`python -m dev_lab.dev.hpcaccount look --account <user> <what>`'
)

#: Runs one argv captured (``subprocess.run``'s shape).
type Run = Callable[..., subprocess.CompletedProcess[str]]


def key_refused(said: str) -> str:
    """The denial line of ssh when it refused the KEY (``publickey`` offered, no code method left); else ``''``."""
    found = _DENIED.search(said)
    if found is None or WANTS_CODE.search(said) or 'publickey' not in found.group(1).split(','):
        return ''
    return found.group(0)


def _own_part(dest: str, said: str) -> str:
    """``ssh -v`` about *dest* itself: after its last ``Authenticating to <host>:`` (a bastion's comes before)."""
    marker = f'Authenticating to {dest.rpartition("@")[2]}:'
    return said[said.rindex(marker) :] if marker in said else ''


def _cause(said: str) -> str:
    """Ssh's denial line, else its last non-debug line, else ``'no denial line'``."""
    if found := _DENIED_ANY.search(said):
        return found.group(0)
    plain = [line.strip() for line in said.splitlines() if line.strip() and not line.startswith('debug')]
    return plain[-1] if plain else 'no denial line'


def probe(dest: str, ssh: Sequence[str], *, run: Run | None = None) -> str:
    """PROVE, with no code read, that *dest* accepted this machine's key and wants only the code; say the proof.

    *ssh* are the open's own words. One ``ssh -v`` BatchMode attempt (no prompt can be answered, so no code is
    spent); the proof is ``Authenticated using "publickey" with partial success`` for *dest* itself.

    Raises:
        HoldRefused: a key-only host, or no proof -- naming ssh's cause, the identity it offered and the doors.

    """
    argv = [*ssh, '-v', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', dest, 'true']
    retry = f'`python -m dev_lab.dev.sshhold probe {dest}`'
    try:
        done = (run or _door.run)(
            resolved(argv), capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=_PROBE_S,
            check=False, stdin=subprocess.DEVNULL,
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired) as exc:
        msg = (
            f'{dest}: the no-code probe could not run ssh ({type(exc).__name__}), so publickey partial success '
            f'is unproven; no code was read -- fix ssh, then {retry} (on Cirrus the key is registered in SAFE)'
        )
        raise HoldRefused(msg) from exc
    if done.returncode == 0:
        msg = (f'{dest} logged in with the key alone: a KEY-ONLY host needs no code and no held session; no code was '
               f'read -- {KEY_ONLY_DOOR}')  # fmt: skip
        raise HoldRefused(msg)
    said = f'{done.stdout}{done.stderr}'
    own = _own_part(dest, said)
    identities = list(dict.fromkeys(_OFFERED.findall(own or said)))
    if _PARTIAL.search(own):
        return f'{dest}: publickey partial success proven with {", ".join(identities) or "an agent key"}; code next'
    offered = ', '.join(identities) or 'no identity (no key file and no agent key)'
    msg = (f'{dest}: publickey partial success is unproven (ssh, with no code: {_cause(said)}); ssh offered '
           f"{offered}; no code was read and none is used -- register that identity's .pub on the account (on "
           f'Cirrus: SAFE, safe.epcc.ed.ac.uk > Login accounts > the account > Add credential); elsewhere '
           f'{KEYS_DOOR}; then {retry}')  # fmt: skip
    raise HoldRefused(msg)
