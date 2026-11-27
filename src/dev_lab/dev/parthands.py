"""THE HANDS A PART'S DESCRIPTION COULD NOT HOLD, read back from the run record its status links (dev-lab#1083).

A part's status description is capped at the forge's 140 characters (:mod:`dev_lab.dev.partfacts`), so with enough
parts its ``hands`` list is cut and ends ``+N``. The parts it could not name are still in the run record the status
links as its target (``handed``, one entry per id): the single source. :func:`part_statuses` and
:func:`part_history` are how a reader that decides which parts a commit needs FETCHES its statuses -- every reading
after them (:func:`dev_lab.dev.platformparts.derived`, ``standing``, the merge waits) is pure and sees the whole list.
A record that cannot be read leaves the cut in place, and the composition names it: never a smaller set of parts.
"""

from __future__ import annotations

import dataclasses
from collections import Counter
from typing import TYPE_CHECKING, cast

from dev_lab.dev.forgestatus import linked_record, status_history, status_list
from dev_lab.dev.partfacts import parsed

if TYPE_CHECKING:
    from collections.abc import Sequence

    from dev_lab.dev.forgestatus import CommitStatus
    from dev_lab.dev.forgework import Client

__all__ = ['complete_hands', 'part_history', 'part_statuses']

#: Record url -> the parts its ``handed`` map names, counted; a record never changes, so each is read once.
_HANDS_READ: dict[str, dict[str, int] | None] = {}


def _record_hands(client: Client, status: CommitStatus) -> dict[str, int] | None:
    """The parts the run record *status* links hands ids to, counted; ``None`` when the record cannot be read."""
    if status.url not in _HANDS_READ:
        record = linked_record(client, status)
        handed = record.get('handed') if record is not None else None
        owners = cast('dict[str, object]', handed) if isinstance(handed, dict) else None
        _HANDS_READ[status.url] = dict(Counter(str(owner) for owner in owners.values())) if owners is not None else None
    return _HANDS_READ[status.url]


def complete_hands(client: Client, statuses: Sequence[CommitStatus]) -> tuple[CommitStatus, ...]:
    """*statuses*, each part whose description CUT its ``hands`` (``+N``) said in full from the record it links.

    The completed description is the same :meth:`~dev_lab.dev.partfacts.Part.description`, uncut: held in memory,
    never posted. A record that cannot be read leaves the cut in place (module docstring).
    """
    out: list[CommitStatus] = []
    for status in statuses:
        part = parsed(status)
        full = _record_hands(client, status) if part is not None and part.hands_more else None
        if part is not None and full is not None:
            whole = dataclasses.replace(part, hands=full, hands_more=0).description(limit=None)
            status = dataclasses.replace(status, description=whole)  # noqa: PLW2901 -- the completed one replaces it
        out.append(status)
    return tuple(out)


def part_statuses(client: Client, sha: str) -> tuple[CommitStatus, ...]:
    """*sha*'s latest statuses as a reader of its parts needs them: :func:`complete_hands` of ``status_list``."""
    return complete_hands(client, status_list(client, sha))


def part_history(client: Client, sha: str) -> tuple[CommitStatus, ...]:
    """*sha*'s whole status history as a reader of its parts needs it: :func:`complete_hands` of ``status_history``."""
    return complete_hands(client, status_history(client, sha))
