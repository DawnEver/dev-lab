"""WORKSTATION STRIKES AND REVOCATION -- what a contradicted spot check leaves in the run-records store (D50-1).

A spot check (:mod:`dev_lab.dev.workstationverdict`) that contradicts a workstation's record is a STRIKE against
that box, never at once a revocation: one flaky test must not bar an honest box. :data:`STRIKES_TO_REVOKE`
strikes revoke it -- it may post no part any more, and no record it ever posted is cited
(:func:`dev_lab.dev.verdictstore.lookup`).

ONE FILE PER BOX (``workstation-strikes-<box>.json``, a JSON list of the strikes' texts), so two boxes struck at
once never overwrite each other's strikes. A file that does not read as a list of strings RAISES ``ValueError``:
every reader fails closed on it.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Final

from dev_lab.dev.forgerecords import listing, replace_named

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = ['STRIKES_TO_REVOKE', 'revoked', 'strike', 'strikes_name']

#: How many contradicted spot checks revoke a box.
STRIKES_TO_REVOKE: Final = 2

_PREFIX: Final = 'workstation-strikes-'
_SUFFIX: Final = '.json'
_UNSAFE: Final = re.compile(r'[^A-Za-z0-9_.-]')


def strikes_name(host: str) -> str:
    """The store file holding *host*'s strikes."""
    return f'{_PREFIX}{_UNSAFE.sub("_", host)}{_SUFFIX}'


def _strikes(client: Client) -> dict[str, list[str]]:
    """``{file name: its strikes}`` for every box with a strike; a malformed file raises ``ValueError``."""
    found: dict[str, list[str]] = {}
    for item in listing(client):
        if item.name.startswith(_PREFIX) and item.name.endswith(_SUFFIX):
            value = json.loads(client.download(item.url).decode('utf-8'))
            if not isinstance(value, list) or not all(isinstance(one, str) for one in value):
                msg = f'{item.name} is not a list of strike texts'
                raise ValueError(msg)
            found[item.name] = value
    return found


def revoked(client: Client) -> frozenset[str]:
    """The store file names of every revoked box (:func:`strikes_name`). Unreadable: ``OSError``/``ValueError``."""
    return frozenset(name for name, struck in _strikes(client).items() if len(struck) >= STRIKES_TO_REVOKE)


def strike(client: Client, host: str, why: str) -> str:
    """Add a strike naming *why* against *host*; the line saying so, and whether it is now revoked."""
    name = strikes_name(host)
    struck = [*_strikes(client).get(name, []), why]
    replace_named(client, name, json.dumps(struck).encode('utf-8'))
    state = 'REVOKED' if len(struck) >= STRIKES_TO_REVOKE else 'not yet revoked'
    return f'[workstationrevoke] strike {len(struck)}/{STRIKES_TO_REVOKE} against {host}: {why} -- {state}'
