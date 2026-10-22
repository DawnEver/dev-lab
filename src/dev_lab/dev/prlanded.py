"""LANDED-PRS-CLOSE: an open PR whose head is already on its base is closed, and its branch pruned.

User ruling 2026-10-22: a PR whose head reached its base some other way (a Break-Glass merge, a containment
merge) stays open, and its open PR then holds its branch against every delete. Closing it is a MECHANISM.

THE ONE CRITERION is ``git merge-base --is-ancestor <head sha> origin/<base>``, read from fetched refs; no
heuristic. A contained PR gets ONE comment (a hidden marker keyed by the head sha), is closed, and its
branch goes through branchprune's lossless door (:func:`dev_lab.dev.branchprune.delete`) when the repo's
branch set allows it: an ephemeral namespace, or ``prune_merged`` for an undeclared branch. A PR whose head
is not contained is never touched. A closed PR is not listed again, so a second pass does nothing.

Every ``forge serve`` tick runs it over every open PR (:func:`serve_close_landed`); a person or agent runs
``python -m dev_lab.dev.forge pr close-landed [<n>...]`` (:func:`main`), which refuses a named PR whose
head is not contained. Each close writes one :data:`EVENT` line.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Final

from dev_lab.dev import branchprune
from dev_lab.dev.branchset import BranchSetNotDeclared, declared_branchset
from dev_lab.dev.checkout import git_out
from dev_lab.dev.forge import fetch_origin
from dev_lab.dev.forgealarm import PRUNED, Alarm, sound
from dev_lab.dev.forgepulls import ListingIncomplete, Marker, comment_upsert, pr_list
from dev_lab.dev.forgework import ForgeCallFailed, client_for
from dev_lab.dev.labsession import ENV
from lab_commons.log import emit

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client, PullRequest

__all__ = ['EVENT', 'close_landed', 'landing', 'main', 'serve_close_landed']

#: The ``event`` of the one structured line each close writes.
EVENT: Final = 'lab_commons.forge.pr-close-landed'
_ORIGIN: Final = 'refs/remotes/origin/'


def _head_sha(root: Path, pr: PullRequest) -> str:
    return pr.head_sha or (git_out(root, 'rev-parse', '--verify', '--quiet', f'{_ORIGIN}{pr.head}') or '').strip()


def landing(root: Path, pr: PullRequest) -> str:
    """The commit on origin's base that carries *pr*'s head (``''`` when the head is not contained)."""
    sha, base = _head_sha(root, pr), f'{_ORIGIN}{pr.base}'
    if not sha or git_out(root, 'merge-base', '--is-ancestor', sha, base) is None:
        return ''
    path = git_out(root, 'rev-list', '--first-parent', '--ancestry-path', '--reverse', f'{sha}..{base}') or ''
    return (path.split() or [sha])[0]


def _prunable(root: Path, branch: str) -> bool:
    branchset = declared_branchset(root)
    return branchset.is_ephemeral(branch) or (branchset.prune_merged and branch not in branchset.declared)


def close_landed(
    root: Path,
    client: Client,
    numbers: Sequence[int] = (),
    *,
    session: str,
    fetch: Callable[[Path], None],
    say: Callable[[str], None],
    alarm: Callable[[Alarm], object] = sound,
) -> int:
    """Close every open PR (or those *numbers*) whose head is on its base; 1 when a named PR was refused."""
    fetch(root)
    opened = pr_list(client)
    wanted = [pr for pr in opened if not numbers or pr.number in numbers]
    refused = [f'#{n}: refused -- not an open PR' for n in numbers if n not in {pr.number for pr in opened}]
    for pr in wanted:
        merged_by = landing(root, pr)
        if not merged_by:
            if numbers:
                refused.append(f'#{pr.number}: refused -- head {_head_sha(root, pr)[:12]} is not on {pr.base}')
            continue
        head = _head_sha(root, pr)
        text = f'landed: head {head[:12]} is on {pr.base} (merged by {merged_by[:12]})'
        comment_upsert(client, pr.number, kind=Marker.LANDED, key=head, text=text)
        client.call('PATCH', f'{client.repo}/pulls/{pr.number}', {'state': 'closed'})
        record = {'event': EVENT, 'pr': pr.number, 'head': pr.head, 'sha': head, 'base': pr.base}
        say(json.dumps(record | {'merged_by': merged_by, 'session': session or None}))
        if _prunable(root, pr.head):
            branchprune.delete(root, [pr.head], client=client, session=session, fetch=fetch, say=say, alarm=alarm)
    for line in refused:
        say(line)
    return 1 if refused else 0


def serve_close_landed(
    root: Path, client: Client, *, say: Callable[[str], None], alarm: Callable[[Alarm], object]
) -> None:
    """The serve tick's step on any host: :func:`close_landed` over every open PR; a failure only alarms."""
    try:
        close_landed(root, client, session='forge-serve', fetch=lambda _r: None, say=say, alarm=alarm)
    except (BranchSetNotDeclared, ForgeCallFailed, ListingIncomplete, OSError, ValueError) as failed:
        alarm(Alarm(PRUNED, client.forge.repo, 'closing landed pull requests failed', str(failed)))


def main(argv: Sequence[str] | None = None, *, cwd: Path | None = None) -> int:
    """``python -m dev_lab.dev.forge pr close-landed [<n>...]``: close landed PRs (no number: every one)."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge pr close-landed', description=main.__doc__)
    parser.add_argument('numbers', nargs='*', type=int)
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd() if cwd is None else cwd
    try:
        return close_landed(
            root, client_for(root), tuple(args.numbers), session=os.environ.get(ENV, ''), fetch=fetch_origin, say=emit
        )
    except (BranchSetNotDeclared, ForgeCallFailed, ListingIncomplete, OSError, ValueError) as failed:
        emit(f'[forge] pr close-landed: {failed}', err=True)
        return 2
