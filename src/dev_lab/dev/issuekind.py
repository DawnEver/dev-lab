"""AN ISSUE IS A NEED: every issue carries one kind -- ``need``, ``defect`` or ``decision`` (user ruling 2026-11-14).

The tracker is where a human finds what is ASKED of someone. A routine notice (a break-glass merge, a sync
reminder, a review backlog, a starved part) is an EVENT, not a need: it is an alarm on the host card
(:mod:`dev_lab.dev.forgehosts`, printed by ``forge queue``), derived anew each tick, so a cleared condition
leaves it by itself. Two copies of that fact -- the card and an issue -- was the noise this module ends.

``forge issue create --kind <kind>`` (:func:`create`) labels the issue ``kind:<kind>``; any other kind is
refused by the parser, naming the three. ``python -m dev_lab.dev.issuekind retire-notices [--apply]``
(:func:`main`) is the ONE migration of the issues written before the ruling: each open issue titled as a
retired alarm kind (:data:`RETIRED_PREFIXES`) is closed with one comment naming where the event lives now.
Without ``--apply`` it prints the plan and writes nothing.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Final

from dev_lab.dev.forgelabels import add_label, ensure_labels

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client, Issue

__all__ = ['KINDS', 'RETIRED_PREFIXES', 'create', 'main', 'retire_notices']

#: The three kinds an issue may be; the label is ``kind:<kind>``.
KINDS: Final = ('need', 'defect', 'decision')
#: Titles of the alarms that were once kept as issues; their events now ride the host card.
RETIRED_PREFIXES: Final = ('integration: ', 'starved: ')
#: The comment a retired notice is closed with.
MOVED: Final = (
    'Closed by the one-time migration (user ruling 2026-11-14): routine notices are no longer issues. '
    'This event is an alarm on the host card -- `python -m dev_lab.dev.forge queue` -- re-derived each tick.'
)


def create(client: Client, title: str, body: str, kind: str) -> Issue:
    """Open issue *title* labelled ``kind:<kind>``; a *kind* outside :data:`KINDS` is refused before any write."""
    if kind not in KINDS:
        msg = f'an issue is one of {KINDS} (forge issue create --kind <kind>); got {kind!r}'
        raise ValueError(msg)
    label = f'kind:{kind}'
    ensure_labels(client, [label])
    issue = client.issue_create(title, body)
    add_label(client, issue.number, label)
    return issue


def retire_notices(client: Client, *, apply: bool) -> list[Issue]:
    """The open issues titled as a retired alarm kind; with *apply*, each is commented and closed."""
    found = [one for one in client.issue_list(state='open', limit=1000) if one.title.startswith(RETIRED_PREFIXES)]
    if apply:
        for one in found:
            client.issue_comment(one.number, MOVED)
            client.issue_close(one.number)
    return found


def main(argv: Sequence[str] | None = None) -> int:
    """``retire-notices [--apply] [--root R]``: the one migration; prints each issue and what was done."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.issuekind')
    verbs = parser.add_subparsers(dest='verb', required=True)
    retire = verbs.add_parser('retire-notices', help='close the open issues the retired alarm kinds wrote')
    retire.add_argument('--apply', action='store_true', help='comment and close; without it nothing is written')
    retire.add_argument('--root', type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    from dev_lab.dev.forgework import client_for  # noqa: PLC0415 -- the forge client only for the verb that writes

    client = client_for(args.root)
    found = retire_notices(client, apply=args.apply)
    tail = '' if args.apply else ' -- dry run: pass --apply to close them'
    lines = [f'{"closed" if args.apply else "would close"} #{one.number} {one.title}' for one in found]
    sys.stdout.write('\n'.join([*lines, f'{len(found)} retired notice issue(s){tail}', '']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
