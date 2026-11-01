"""WORKSTATION STRIKES AND REVOCATION -- what a contradicted spot check leaves in the run-records store (D50-1).

A spot check (:mod:`dev_lab.dev.workstationverdict`) that contradicts a workstation's record is a STRIKE against
that box, never at once a revocation: one flaky test must not bar an honest box. :data:`STRIKES_TO_REVOKE`
strikes revoke it -- it may post no part any more, and no record it ever posted is cited
(:func:`dev_lab.dev.verdictstore.lookup`).

ONE FILE PER STRIKE (``workstation-strike-<box>-<uuid>.json``, the strike's text as a JSON string): a strike is
only ever ADDED, never read-modified-written, so two producers striking one box at once both count -- no lock is
needed because nothing is overwritten. A strike file that is not a JSON string RAISES ``ValueError``: every reader
fails closed on it.

THE REMEDY for a revoked box is a human decision, taken by whoever holds the forge credential once the cause is
understood: ``python -m dev_lab.dev.workstationrevoke clear <box>`` deletes its strikes (:func:`clear`).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons.log import emit

from dev_lab.dev.forgerecords import listing, remove_named, replace_named
from dev_lab.dev.forgework import client_for

if TYPE_CHECKING:
    from collections.abc import Sequence

    from dev_lab.dev.forgework import Client

__all__ = ['CLEAR_REMEDY', 'STRIKES_TO_REVOKE', 'box_of', 'clear', 'main', 'revoked', 'strike']

#: How many contradicted spot checks revoke a box.
STRIKES_TO_REVOKE: Final = 2

#: What a revoked box's refusal names as the remedy.
CLEAR_REMEDY: Final = 'python -m dev_lab.dev.workstationrevoke clear <box>, once the contradiction is understood'

_PREFIX: Final = 'workstation-strike-'
_SUFFIX: Final = '.json'
_UNSAFE: Final = re.compile(r'[^A-Za-z0-9_.]')
_STRIKE: Final = re.compile(rf'^{_PREFIX}(?P<box>[A-Za-z0-9_.]+)-[0-9a-f]{{32}}{re.escape(_SUFFIX)}$')


def box_of(host: str) -> str:
    """*host* as it is spelled in a strike file's name."""
    return _UNSAFE.sub('_', host)


def _strikes(client: Client) -> list[tuple[str, str]]:
    """``(box, attachment name)`` of every strike; a malformed strike file raises ``ValueError``."""
    found = []
    for item in listing(client):
        if (named := _STRIKE.match(item.name)) is not None:
            if not isinstance(json.loads(client.download(item.url).decode('utf-8')), str):
                msg = f'{item.name} is not a strike text'
                raise ValueError(msg)
            found.append((named['box'], item.name))
    return found


def revoked(client: Client) -> frozenset[str]:
    """Every revoked box (:func:`box_of` spelling). Unreadable: ``OSError``; malformed: ``ValueError``."""
    counts = Counter(box for box, _ in _strikes(client))
    return frozenset(box for box, count in counts.items() if count >= STRIKES_TO_REVOKE)


def strike(client: Client, host: str, why: str) -> str:
    """Add one strike naming *why* against *host*; the line saying so, and whether it is now revoked."""
    box = box_of(host)
    replace_named(client, f'{_PREFIX}{box}-{uuid.uuid4().hex}{_SUFFIX}', json.dumps(why).encode('utf-8'))
    count = sum(1 for one, _ in _strikes(client) if one == box)
    state = f'REVOKED -- remedy: {CLEAR_REMEDY}' if count >= STRIKES_TO_REVOKE else 'not yet revoked'
    return f'[workstationrevoke] strike {count}/{STRIKES_TO_REVOKE} against {host}: {why} -- {state}'


def clear(client: Client, host: str) -> int:
    """Delete every strike against *host*; how many went."""
    box = box_of(host)
    return sum(remove_named(client, name) for one, name in _strikes(client) if one == box)


def main(argv: Sequence[str] | None = None) -> int:
    """``clear <box> [--root <checkout>]``: delete a box's strikes on the checkout's forge."""
    parser = argparse.ArgumentParser(
        prog='python -m dev_lab.dev.workstationrevoke', description=__doc__.splitlines()[0]
    )
    verbs = parser.add_subparsers(dest='verb', required=True)
    cleared = verbs.add_parser('clear', help="delete a box's strikes, lifting its revocation")
    cleared.add_argument('box')
    cleared.add_argument('--root', type=Path, default=Path.cwd(), help='the checkout whose forge holds the store')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    emit(f'[workstationrevoke] cleared {clear(client_for(args.root), args.box)} strike(s) against {args.box}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
