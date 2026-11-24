"""A BACKGROUND SHELL LIVES LONGER ONLY BY THE USER'S GRANT: ``python -m dev_lab.dev.shelllife --admit`` < line.

User ruling 2026-11-15: the default lifetime is fifty minutes (:data:`DEFAULT_LIFETIME_S`); a shell that must run
longer asks the USER. No agent-chosen bound counts: a longer life is a consent credential of the family's one
consent store (:mod:`dev_lab.ops.consent`, action ``shell.lifetime``) naming the command's digest and the minutes.
The line carries its credential's id::

    DEV_LAB_LIFETIME_GRANT=<credential id> timeout <minutes>m <command>

Two readers, one judgment:

* :func:`admission` -- the ``BACKGROUND-SHELL-IS-BOUNDED`` row (:mod:`dev_lab.dev._deny_background_row`) asks it
  through ``--admit`` for every background Bash line: a line must START with ``timeout <n>``; above the default it
  needs a grant that verifies, names ``sha256(<command>)`` and covers ``<n>``. A refusal names the request to write
  and the door to grant it with, never a bare no;
* :func:`granted_bound` -- the sweep (:mod:`dev_lab.dev.shellreaper`) honors a longer bound ONLY through it,
  verified at the shell's launch, so an agent-written ``timeout 6h`` without a grant is stopped at fifty minutes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from collections.abc import Callable
from typing import Final

from lab_commons.log import emit

from dev_lab.dev._deny_background_row import BACKGROUND_BOUNDED, DEFAULT_LIFETIME_S
from dev_lab.dev.consentguard import state_dir
from dev_lab.dev.disclosure import details_for
from dev_lab.ops.consent.client import public_key
from dev_lab.ops.consent.credential import ConsentRefused, verify

__all__ = ['ACTION', 'GRANT_VAR', 'admission', 'granted_bound', 'main', 'subject_of']

#: The consent registry row a longer lifetime is granted under (:data:`dev_lab.ops.consent.actions.ACTIONS`).
ACTION: Final = 'shell.lifetime'
#: The variable a granted line carries its credential's id in.
GRANT_VAR: Final = 'DEV_LAB_LIFETIME_GRANT'
_RULE: Final = str(BACKGROUND_BOUNDED['id'])
_UNIT_S: Final = {'': 1.0, 's': 1.0, 'm': 60.0, 'h': 3600.0, 'd': 86400.0}
#: ``[GRANT=<id>] [VAR=x ...] timeout [-opts] <n>[smhd] <command>`` -- the whole admissible shape.
_LINE: Final = re.compile(
    r'^\s*(?:(?:[A-Za-z_]\w*)=\S*\s+)*?timeout\s+(?:-\S+\s+)*(?P<n>\d+(?:\.\d+)?)(?P<unit>[smhd]?)\s+(?P<rest>\S[\s\S]*)$'
)
_GRANT: Final = re.compile(rf'(?:^|[\s\'"]){GRANT_VAR}=(?P<id>[0-9A-Fa-f-]{{8,64}})(?=[\s\'"]|$)')

#: ``(credential id, when) -> (subject, granted seconds)``, or None: the credential verified and unexpired then.
Grants = Callable[[str, float], tuple[str, float] | None]


def subject_of(command: str) -> str:
    """The digest a grant names: SHA-256 of the command after its ``timeout`` prefix, stripped."""
    return hashlib.sha256(command.strip().encode('utf-8')).hexdigest()


def _credential(grant_id: str, when: float) -> tuple[str, float] | None:
    """``(subject, granted seconds)`` of the ``shell.lifetime`` credential *grant_id* valid at *when*; else None."""
    path = state_dir() / f'{grant_id}.json'
    try:
        found = verify(json.loads(path.read_text(encoding='utf-8')), public_key(), now=when)
    except (ConsentRefused, ValueError, OSError):
        return None
    minutes = found.params.get('minutes')
    if found.action != ACTION or not isinstance(minutes, int) or isinstance(minutes, bool):
        return None
    return found.subject, minutes * 60.0


def granted_bound(command_line: str, launched: float, grants: Grants = _credential) -> float:
    """The lifetime of a shell running *command_line*: its verified grant's minutes, else the default."""
    named = _GRANT.search(command_line)
    found = grants(named['id'], launched) if named else None
    return max(found[1], DEFAULT_LIFETIME_S) if found else DEFAULT_LIFETIME_S


def _refusal(why: str, exit_text: str) -> str:
    return f'{_RULE}: {why}\n{exit_text}\n{details_for(_RULE)}'


def admission(line: str, now: float, grants: Grants = _credential) -> str | None:
    """The refusal of background *line*, or ``None`` when it is admitted (bounded, and granted above the default)."""
    shape = _LINE.match(line)
    default = f'{DEFAULT_LIFETIME_S / 60:.0f}m'
    if shape is None:
        return _refusal(
            'a background shell has no lifetime of its own, and this line starts with none.',
            f'Start the line with its bound: timeout {default} <command>; a compound line goes whole: '
            f"timeout {default} bash -c '<line>'. Longer only by the user's grant (a longer bound's refusal names it).",
        )
    asked = float(shape['n']) * _UNIT_S[shape['unit']]
    if asked <= DEFAULT_LIFETIME_S:
        return None
    rest = shape['rest']
    digest = subject_of(rest)
    named = _GRANT.search(line)
    found = grants(named['id'], now) if named else None
    if found is not None and found[0] == digest and found[1] >= asked:
        return None
    minutes = int(-(-asked // 60))
    request = json.dumps({'action': ACTION, 'subject': digest, 'params': {'minutes': minutes}})
    why = f'{asked / 60:.0f} min is above the {default} default, and only the USER grants a longer life' + (
        ' -- the grant named does not verify, names another command, or is shorter.' if named else '.'
    )
    return _refusal(
        why,
        f'Ask the user: write {request} to output/logs/<yy>/<mm>/<dd>/consent/<name>.json, ask them for the code, run '
        '`<python> -m dev_lab.ops.consent grant <that file> --code <the code they gave>`, then re-issue as '
        f'{GRANT_VAR}=<the granted credential id> timeout {minutes}m <command>. Or keep it within timeout {default}.',
    )


def main(argv: list[str] | None = None) -> int:
    """``--admit``: judge the background line on stdin; exit 0 admitted, 1 with the refusal on stdout."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.shelllife', description=main.__doc__)
    parser.add_argument('--admit', action='store_true', required=True)
    parser.parse_args(argv)
    refused = admission(sys.stdin.read(), time.time())
    if refused:
        emit(refused)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
