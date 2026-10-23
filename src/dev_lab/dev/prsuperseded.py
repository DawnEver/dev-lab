"""SUPERSEDED-PRS-CLOSE: ``python -m dev_lab.dev.forge pr close-superseded <n>... --by <pr>``.

A pull request whose content was salvaged into ANOTHER pull request stays open and holds its branch. This
door closes it: one comment ``superseded by #<by>: <one line>``, the close, then its branch through
LOSSLESS-DELETE (:func:`dev_lab.dev.branchprune.delete`) -- which keeps the branch, naming the commits, when
any commit on it exists nowhere else. Refused, touching nothing:

* ``--by`` is not an open PR, or its head is already merged into its base (:func:`dev_lab.dev.prlanded.landing`)
  -- a landed replacement is ``close-landed``'s case, and a closed one supersedes nothing;
* a named PR is not open, or is ``--by`` itself;
* the line is empty or spans several lines.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons.log import emit

from dev_lab.dev import branchprune
from dev_lab.dev.forge import fetch_origin
from dev_lab.dev.forgealarm import Alarm, sound
from dev_lab.dev.forgepulls import ListingIncomplete
from dev_lab.dev.forgework import ForgeCallFailed, client_for
from dev_lab.dev.labsession import ENV
from dev_lab.dev.prlanded import landing

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = ['EVENT', 'close_superseded', 'main']

#: The ``event`` of the one structured line each close writes.
EVENT: Final = 'dev_lab.forge.pr-close-superseded'


def close_superseded(
    root: Path,
    client: Client,
    numbers: Sequence[int],
    *,
    by: int,
    line: str,
    session: str,
    fetch: Callable[[Path], None],
    say: Callable[[str], None],
    alarm: Callable[[Alarm], object] = sound,
) -> int:
    """Close each of *numbers* as superseded by *by*; 1 when anything was refused (nothing is touched then)."""
    fetch(root)
    replacement = client.pr_view(by)
    refused = []
    if not line.strip() or '\n' in line:
        refused.append('refused -- the reason is one non-empty line')
    if replacement.state != 'open':
        refused.append(f'#{by}: refused -- the replacement is {replacement.state}, not open')
    elif landing(root, replacement):
        refused.append(f'#{by}: refused -- the replacement is already merged into {replacement.base}')
    pulls = [client.pr_view(n) for n in numbers]
    refused += [f'#{pr.number}: refused -- it is {pr.state}' for pr in pulls if pr.state != 'open']
    refused += [f'#{by}: refused -- a PR does not supersede itself' for pr in pulls if pr.number == by]
    if refused:
        for why in refused:
            say(why)
        return 1
    failed = 0
    for pr in pulls:
        client.issue_comment(pr.number, f'superseded by #{by}: {line.strip()}')
        client.call('PATCH', f'{client.repo}/pulls/{pr.number}', {'state': 'closed'})
        say(json.dumps({'event': EVENT, 'pr': pr.number, 'by': by, 'head': pr.head, 'session': session or None}))
        failed |= branchprune.delete(root, [pr.head], client=client, session=session, fetch=fetch, say=say, alarm=alarm)
    return failed


def main(argv: Sequence[str] | None = None, *, cwd: Path | None = None) -> int:
    """``python -m dev_lab.dev.forge pr close-superseded <n>... --by <pr> [--why <line>]``."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge pr close-superseded', description=main.__doc__)
    parser.add_argument('numbers', nargs='+', type=int)
    parser.add_argument('--by', type=int, required=True)
    parser.add_argument('--why', default='', help='the one line (default: the replacement title)')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd() if cwd is None else cwd
    try:
        client = client_for(root)
        line = args.why or client.pr_view(args.by).title
        return close_superseded(
            root,
            client,
            tuple(args.numbers),
            by=args.by,
            line=line,
            session=os.environ.get(ENV, ''),
            fetch=fetch_origin,
            say=emit,
        )
    except (ForgeCallFailed, ListingIncomplete, OSError, ValueError) as failed:
        emit(f'[forge] pr close-superseded: {failed}', err=True)
        return 2
