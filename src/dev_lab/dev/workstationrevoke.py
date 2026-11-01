"""WORKSTATION STRIKES AND REVOCATION -- what a contradicted spot check leaves in the run-records store (D50-1).

A spot check (:mod:`dev_lab.dev.workstationverdict`) that contradicts a workstation's record is a STRIKE against
that box, never at once a revocation: one flaky test must not bar an honest box. :data:`STRIKES_TO_REVOKE`
strikes revoke it -- it may post no part any more, and no record it ever posted is cited
(:func:`dev_lab.dev.verdictstore.lookup`).

ONE FILE PER STRIKE (``workstation-strike-<box>-<uuid>.json``, the strike's text as a JSON string): a strike is
only ever ADDED, never read-modified-written, so two producers striking one box at once both count -- no lock is
needed because nothing is overwritten. A strike file that is not a JSON string is IGNORED with a named warning:
one bad file never revokes, or locks out, the fleet.

THE REMEDY for a revoked box is a human decision, taken by whoever holds the forge credential once the cause is
understood: ``python -m dev_lab.dev.workstationrevoke clear <box>`` deletes its strikes by name (:func:`clear`),
a malformed one too, and exits 1 when it removed nothing.
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

__all__ = ['STRIKES_TO_REVOKE', 'box_of', 'clear', 'clear_remedy', 'main', 'revoked', 'strike']

#: How many contradicted spot checks revoke a box.
STRIKES_TO_REVOKE: Final = 2

_PREFIX: Final = 'workstation-strike-'
_SUFFIX: Final = '.json'
_KEPT: Final = re.compile(r'[A-Za-z0-9.]')
_STRIKE: Final = re.compile(rf'^{_PREFIX}(?P<box>[A-Za-z0-9._]+)-[0-9a-f]{{32}}{re.escape(_SUFFIX)}$')


def clear_remedy(host: str) -> str:
    """What a revoked *host*'s refusal names as the remedy, its real name in the command."""
    return f'python -m dev_lab.dev.workstationrevoke clear {host}, once the contradiction is understood'


def box_of(host: str) -> str:
    """*host* as spelled in a strike file's name; INJECTIVE, so ``a-b`` and ``a_b`` stay two boxes.

    Every byte outside ``[A-Za-z0-9.]`` -- ``_`` included -- becomes ``_<hex>``.
    """
    return ''.join(c if _KEPT.fullmatch(c) else ''.join(f'_{b:02x}' for b in c.encode()) for c in host)


def _strike_names(client: Client) -> list[tuple[str, str]]:
    """``(box, attachment name)`` of every file NAMED as a strike, read by name alone."""
    return [(named['box'], item.name) for item in listing(client) if (named := _STRIKE.match(item.name))]


def _strikes(client: Client) -> list[str]:
    """The box of every well-formed strike; a malformed one is IGNORED with a named warning, never fatal."""
    found = []
    for item in listing(client):
        if (named := _STRIKE.match(item.name)) is None:
            continue
        try:
            text = json.loads(client.download(item.url).decode('utf-8'))
        except ValueError:
            text = None
        if not isinstance(text, str):
            emit(f'[workstationrevoke] warning: {item.name} is not a strike text -- ignored, not counted', err=True)
            continue
        found.append(named['box'])
    return found


def revoked(client: Client) -> frozenset[str]:
    """Every revoked box (:func:`box_of` spelling). An unreadable store raises ``OSError``."""
    counts = Counter(_strikes(client))
    return frozenset(box for box, count in counts.items() if count >= STRIKES_TO_REVOKE)


def strike(client: Client, host: str, why: str) -> str:
    """Add one strike naming *why* against *host* -- a NEW file, nothing read first; the line saying so."""
    box = box_of(host)
    replace_named(client, f'{_PREFIX}{box}-{uuid.uuid4().hex}{_SUFFIX}', json.dumps(why).encode('utf-8'))
    count = _strikes(client).count(box)
    state = f'REVOKED -- remedy: {clear_remedy(host)}' if count >= STRIKES_TO_REVOKE else 'not yet revoked'
    return f'[workstationrevoke] strike {count}/{STRIKES_TO_REVOKE} against {host}: {why} -- {state}'


def clear(client: Client, host: str) -> int:
    """Delete every file named as a strike against *host*, by name alone (a malformed one too); how many went."""
    box = box_of(host)
    return sum(remove_named(client, name) for one, name in _strike_names(client) if one == box)


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
    removed = clear(client_for(args.root), args.box)
    emit(f'[workstationrevoke] cleared {removed} strike(s) against {args.box}', err=not removed)
    return 0 if removed else 1


if __name__ == '__main__':
    raise SystemExit(main())
