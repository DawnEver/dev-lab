"""AN ISSUE IS A NEED: every issue carries one kind -- ``need``, ``defect`` or ``decision`` (user ruling 2026-11-14).

The tracker is where a human finds what is ASKED of someone. A routine notice (a break-glass merge, a sync
reminder, a review backlog, a starved part) is an EVENT, not a need: it is an alarm on the host card
(:mod:`dev_lab.dev.forgehosts`, printed by ``forge queue``), derived anew each tick, so a cleared condition
leaves it by itself. Two copies of that fact -- the card and an issue -- was the noise this module ends.

``forge issue create --kind <kind>`` (:func:`create`) labels the issue ``kind:<kind>``; any other kind is
refused by the parser, naming the three. ``python -m dev_lab.dev.issuekind retire-notices [--apply]``
(:func:`main`) is the ONE migration of the issues written before the ruling: each open issue titled as a
retired alarm kind (:data:`RETIRED_PREFIXES`) is closed with one comment naming where the event lives now, and
each open request a host already settled (labeled :data:`~dev_lab.dev.forgerequesthost.DONE_LABEL`, user ruling
2026-11-19: a settled request closes) with :data:`SETTLED`. An unsettled request is a live need and stays open.
Without ``--apply`` it prints the plan and writes nothing.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons.log import emit

from dev_lab.dev.forgeclient import client_for
from dev_lab.dev.forgelabels import add_label, ensure_labels
from dev_lab.dev.forgerequesthost import DONE_LABEL
from dev_lab.dev.forgeschedule import labeled_issues

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client, Issue

__all__ = ['KINDS', 'MOVED', 'RETIRED_PREFIXES', 'SETTLED', 'create', 'main', 'retire_notices']

#: The three kinds an issue may be; the label is ``kind:<kind>``.
KINDS: Final = ('need', 'defect', 'decision')
#: Titles of the alarms that were once kept as issues; their events now ride the host card.
RETIRED_PREFIXES: Final = ('integration: ', 'starved: ')
#: The comment a retired notice is closed with.
MOVED: Final = (
    'Closed by the one-time migration (user ruling 2026-11-14): routine notices are no longer issues. '
    'This event is an alarm on the host card -- `python -m dev_lab.dev.forge queue` -- re-derived each tick.'
)


#: The comment a settled request still open is closed with.
SETTLED: Final = (
    'Closed by the one-time migration (user ruling 2026-11-19): a request a host settled closes; its result is above '
    "and on the sha's status. What is still pending is in `python -m dev_lab.dev.forge queue`."
)


def create(client: Client, title: str, body: str, kind: str, labels: Sequence[str] = ()) -> Issue:
    """Open issue *title* labeled ``kind:<kind>`` and each of *labels*, a missing one created first.

    A *kind* outside :data:`KINDS` is refused before any write.
    """
    if kind not in KINDS:
        msg = f'an issue is one of {KINDS} (forge issue create --kind <kind>); got {kind!r}'
        raise ValueError(msg)
    wanted = list(dict.fromkeys([f'kind:{kind}', *labels]))
    ensure_labels(client, wanted)
    issue = client.issue_create(title, body)
    for label in wanted:
        add_label(client, issue.number, label)
    return issue


def retire_notices(client: Client, *, apply: bool) -> list[Issue]:
    """The open issues titled as a retired alarm kind; with *apply*, each is commented and closed."""
    listed = client.issue_list(state='open', limit=1000)
    notices = [one for one in listed if one.title.startswith(RETIRED_PREFIXES)]
    settled_numbers = {int(raw['number']) for raw in labeled_issues(client, DONE_LABEL)}
    settled = [one for one in listed if one.number in settled_numbers and one not in notices]
    if apply:
        for one, comment in [*((n, MOVED) for n in notices), *((n, SETTLED) for n in settled)]:
            client.issue_comment(one.number, comment)
            client.issue_close(one.number)
    return [*notices, *settled]


def main(argv: Sequence[str] | None = None) -> int:
    """``retire-notices [--apply] [--root R]``: the one migration; prints each issue and what was done."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.issuekind')
    verbs = parser.add_subparsers(dest='verb', required=True)
    retire = verbs.add_parser('retire-notices', help='close retired-alarm issues and settled requests')
    retire.add_argument('--apply', action='store_true', help='comment and close; without it nothing is written')
    retire.add_argument('--root', type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    client = client_for(args.root)
    found = retire_notices(client, apply=args.apply)
    tail = '' if args.apply else ' -- dry run: pass --apply to close them'
    lines = [f'{"closed" if args.apply else "would close"} #{one.number} {one.title}' for one in found]
    emit('\n'.join([*lines, f'{len(found)} retired notice or settled request issue(s){tail}']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
