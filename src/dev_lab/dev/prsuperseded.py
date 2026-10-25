"""SUPERSEDED-PRS-CLOSE: ``python -m dev_lab.dev.forge pr close-superseded <n>... --by <pr|sha|ref>``.

A pull request whose content was salvaged elsewhere stays open. This door closes it with one evidence
comment, ``superseded by #<pr>: <one line>`` or ``superseded by <sha>: <one line>``. The carrier is an open
PR (a number) or any commit (a sha or ref, resolved locally or as ``origin/<ref>``): a salvage need not have
a PR of its own. The branch is NEVER deleted here: remote ref deletion is a human decision expressed as data
(``prune_merged``, :mod:`dev_lab.dev.branchset`), and the forge's prune of merged branches
(:mod:`dev_lab.dev.branchprune`) is the one deleter. Refused, touching nothing:

* a PR carrier is not open, or its head is already merged into its base (:func:`dev_lab.dev.prlanded.landing`)
  -- a landed replacement is ``close-landed``'s case, and a closed one supersedes nothing;
* a commit carrier does not resolve;
* a named PR is not open, or is the carrier itself;
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

from dev_lab.dev.checkout import git_out
from dev_lab.dev.forge import fetch_origin
from dev_lab.dev.forgepulls import ListingIncomplete
from dev_lab.dev.forgework import ForgeCallFailed, client_for
from dev_lab.dev.labsession import ENV
from dev_lab.dev.prlanded import landing

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = ['EVENT', 'close_superseded', 'main']

#: The ``event`` of the one structured line each close writes.
EVENT: Final = 'dev_lab.forge.pr-close-superseded'


def carrier_number(by: str | int) -> int | None:
    """The PR number *by* names, or ``None`` when it names a commit (a sha or ref)."""
    text = str(by).strip().removeprefix('#')
    return int(text) if text.isdigit() else None


def resolve_commit(root: Path, ref: str) -> str:
    """The full sha *ref* names, locally or as ``origin/<ref>`` (``''`` when neither resolves)."""
    for name in (ref, f'refs/remotes/origin/{ref}'):
        sha = (git_out(root, 'rev-parse', '--verify', '--quiet', f'{name}^{{commit}}') or '').strip()
        if sha:
            return sha
    return ''


def close_superseded(
    root: Path,
    client: Client,
    numbers: Sequence[int],
    *,
    by: int | str,
    line: str,
    session: str,
    fetch: Callable[[Path], None],
    say: Callable[[str], None],
) -> int:
    """Close each of *numbers* as superseded by *by* (a PR or a commit); 1 when anything was refused."""
    fetch(root)
    refused = []
    if not line.strip() or '\n' in line:
        refused.append('refused -- the reason is one non-empty line')
    number = carrier_number(by)
    if number is not None:
        carrier = f'#{number}'
        replacement = client.pr_view(number)
        if replacement.state != 'open':
            refused.append(f'{carrier}: refused -- the replacement is {replacement.state}, not open')
        elif landing(root, replacement):
            refused.append(f'{carrier}: refused -- the replacement is already merged into {replacement.base}')
    else:
        sha = resolve_commit(root, str(by))
        carrier = sha[:12]
        if not sha:
            refused.append(f'{by}: refused -- not a PR number and no commit resolves it')
    pulls = [client.pr_view(n) for n in dict.fromkeys(numbers)]  # once each, in the order given
    refused += [f'#{pr.number}: refused -- it is {pr.state}' for pr in pulls if pr.state != 'open']
    refused += [f'#{number}: refused -- a PR does not supersede itself' for pr in pulls if pr.number == number]
    if refused:
        for why in refused:
            say(why)
        return 1
    for pr in pulls:
        # CLOSE FIRST: a comment saying "superseded" on a PR left open is the half-done state to avoid. Each PR
        # is finished (closed, commented) before the next is touched, and the first failure stops.
        try:
            client.call('PATCH', f'{client.repo}/pulls/{pr.number}', {'state': 'closed'})
            client.issue_comment(pr.number, f'superseded by {carrier}: {line.strip()}')
        except ForgeCallFailed as why:
            say(f'#{pr.number}: stopped -- {why}; the PRs after it were not touched')
            return 1
        record = {'event': EVENT, 'pr': pr.number, 'by': carrier, 'head': pr.head, 'session': session or None}
        say(json.dumps(record))
    return 0


def main(argv: Sequence[str] | None = None, *, cwd: Path | None = None) -> int:
    """``python -m dev_lab.dev.forge pr close-superseded <n>... --by <pr|sha|ref> [--why <line>]``."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge pr close-superseded', description=main.__doc__)
    parser.add_argument('numbers', nargs='+', type=int)
    parser.add_argument('--by', required=True, help='the carrier: an open PR number, or a commit sha / ref')
    parser.add_argument('--why', default='', help='the one line (default: the PR title or commit subject)')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd() if cwd is None else cwd
    try:
        client = client_for(root)
        number = carrier_number(args.by)
        if args.why:
            line = args.why
        elif number is not None:
            line = client.pr_view(number).title
        else:
            subject = git_out(root, 'log', '-1', '--format=%s', resolve_commit(root, args.by) or args.by)
            line = (subject or '').strip()
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
