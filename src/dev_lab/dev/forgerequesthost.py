"""How a serving host treats a request: whose it runs, the reminder it posts, and the result it settles.

Split from :mod:`dev_lab.dev.forgerequest` (the module-size band): what that module declares, this one does on
a ``forge serve`` host -- trust (:func:`untrusted`), the one unadmitted comment (:func:`remind`), and the exit
code turned into a status and an issue comment (:func:`result`, :func:`settle`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.compute.model import REQUEST
from lab_commons.config import section

from dev_lab.dev.forge import _GIT
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgelabels import add_label
from dev_lab.dev.producer import Owner, ProducerExit, release_reason

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence
    from pathlib import Path

    from lab_commons.compute.model import Ranked

    from dev_lab.dev.forgework import Client

__all__ = [
    'DONE_LABEL',
    'REQUESTS_TABLE',
    'TAIL_LINES',
    'UNADMITTED',
    'remind',
    'request_authors',
    'result',
    'settle',
    'untrusted',
]

#: How many log lines the result comment quotes.
TAIL_LINES: Final = 40


#: The machine-file table naming whose requests this host runs off the trunks: ``authors = ["<login>", ...]``.
REQUESTS_TABLE: Final = 'requests'


def request_authors() -> frozenset[str]:
    """The logins this host runs a request for at ANY served sha (its machine file's ``[requests] authors``)."""
    table = section(REQUESTS_TABLE)
    authors = table.get('authors', [])
    if set(table) - {'authors'} or not isinstance(authors, list) or not all(isinstance(a, str) for a in authors):
        msg = f'[{REQUESTS_TABLE}] takes only authors = ["<forge login>", ...]'
        raise ValueError(msg)
    return frozenset(authors)


def untrusted(root: Path, sha: str, author: str, *, trunks: Sequence[str], authors: Collection[str]) -> str:
    """Why this host does not run *author*'s request at *sha*, ``''`` when it does.

    A request runs its sha's code on another person's box: only code reviewed onto one of *trunks* (origin's
    integration branch or trunk) runs for anyone; code anywhere else runs only for an author this host's
    machine file allows (:func:`request_authors`).
    """
    if author and author in authors:
        return ''
    for ref in trunks:
        done = _door.run(
            [_GIT, '-C', str(root), 'merge-base', '--is-ancestor', sha, f'refs/remotes/origin/{ref}'],
            capture_output=True,
            check=False,
        )
        if done.returncode == 0:
            return ''
    who = author or 'its unresolved author'
    on = ' nor '.join(trunks)
    return f"{sha[:12]} is on neither {on}, and {who} is not in this host's [{REQUESTS_TABLE}] authors"


#: The mark of the one comment a request waiting past ``request_unadmitted_hours`` gets.
UNADMITTED: Final = '**unadmitted**'


def remind(client: Client, queue: Sequence[Ranked], *, hours: float, host: str) -> list[str]:
    """Comment ONCE on each request of *queue* blocked past *hours*, naming why *host* did not admit it.

    The requester otherwise learns nothing but by polling ``forge queue``. The issue's comments are read
    first: one carrying :data:`UNADMITTED` means it was told. A forge call that fails is said, never raised.
    """
    said = []
    for item in queue:
        one = item.candidate
        if one.kind != REQUEST or not item.blocked or item.wait_h < hours:
            continue
        path = f'{client.repo}/issues/{one.number}/comments'
        try:
            if any(UNADMITTED in str(raw.get('body') or '') for raw in client.call('GET', path) or ()):
                continue
            client.issue_comment(
                one.number,
                f'{UNADMITTED} for {item.wait_h:.0f} h: no host has claimed this request. {host}: {item.blocked}',
            )
        except ForgeCallFailed as failed:
            said.append(f'could not tell issue/{one.number} it waits: {failed}')
        else:
            said.append(f'told issue/{one.number} it waited {item.wait_h:.0f} h unadmitted')
    return said


def result(code: int, host: str, *, outage: Owner | None, detail: str = '') -> tuple[str, str]:
    """The ``(state, description)`` a request's producer exiting *code* on *host* settles it with; *detail* ends it."""
    if code == ProducerExit.PASS:
        return 'success', f'request done: exit 0 on {host}{detail}'
    if code == ProducerExit.FAIL:
        return 'failure', f'request failed: exit 1 on {host}{detail}'
    return 'error', release_reason(code, outage=outage, detail=detail)


#: The label a request whose producer exited 0 gets: done, awaiting its requester's sign-off.
DONE_LABEL: Final = 'request:done'


def settle(
    client: Client,
    number: int,
    state: str,
    description: str,
    *,
    log: str,
    host: str,
    record: tuple[str, Sequence[tuple[str, str]]],
) -> None:
    """Comment the outcome, where its record is kept, each file's sha256 and the log's tail on issue *number*.

    A success is labelled :data:`DONE_LABEL` and LEFT OPEN: exit 0 says the producer finished, not that the
    requester accepts what it made -- the requester signs off by closing it.
    """
    tail = '\n'.join(log.rstrip().splitlines()[-TAIL_LINES:])
    kept, files = record
    sums = ''.join(f'- `{digest}`  {name}\n' for name, digest in files) or '- (no file)\n'
    where = f'record: `{kept}` on {host}' if kept else f'record: none declared on {host}'
    body = f'**{state}** -- {description}\n\n{where}\n\nsha256:\n\n{sums}\nlog tail:\n\n```\n{tail}\n```'
    client.issue_comment(number, body)
    if state == 'success':
        add_label(client, number, DONE_LABEL)
