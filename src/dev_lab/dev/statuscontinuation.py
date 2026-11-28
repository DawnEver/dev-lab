"""A STATUS DESCRIPTION LONGER THAN ITS FORGE STORES CONTINUES, never cut.

THE DEFECT (user, 2026-11-27): GitHub cut a document-lab part's ``hands=`` list at 140 characters and every
reader read the all-green part as undetermined. Each backend declares its limit
(:attr:`~dev_lab.dev._forgebackends.Backend.description_limit`). Past it, ``forgestatus.status_post`` posts the
rest as continuation statuses ``<context>#1..k`` FIRST, then the head, which ends `` >>k:<digest8>``
(:func:`continued`); ``status_list`` and ``status_history`` join them back into one ``CommitStatus``
(:func:`joined`), so no reader sees a continuation. A head whose continuations are missing or do not match its
digest is left as posted, and :func:`incomplete` names why -- as it names a description a forge cut.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
from typing import TYPE_CHECKING, Final

from dev_lab.dev._forgebackends import GITEA, GITHUB

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from dev_lab.dev.forgestatus import CommitStatus

__all__ = ['CONTINUATION', 'DESCRIPTION_LIMIT', 'FORGE_CUT', 'continued', 'incomplete', 'joined']

#: The tightest description limit a backend declares (GitHub's): a description EXACTLY this long is what a cut leaves.
FORGE_CUT: Final = min(limit for limit in (GITEA.description_limit, GITHUB.description_limit) if limit)

#: The longest description ONE status says whole on every forge: one short of :data:`FORGE_CUT`, so a whole text is
#: never mistaken for a cut one. A free text cut to it never continues; a longer one continues (:func:`continued`).
DESCRIPTION_LIMIT: Final = FORGE_CUT - 1

#: A continuation status's context is its head's ``<context>#<n>``, n from 1.
CONTINUATION: Final = '#'

#: The head of a continued description ends `` >>k:<digest8>``: k continuations, the whole text's sha256 prefix.
_CONTINUED: Final = re.compile(r' >>(?P<count>[1-9]\d*):(?P<digest>[0-9a-f]{8})$')


def continued(description: str, limit: int | None) -> tuple[str, tuple[str, ...]]:
    """``(head, continuations)`` *description* posts as under *limit*, every piece at most *limit* long.

    No piece is ever EXACTLY :data:`FORGE_CUT` long, on any backend: that length is what a forge's cut leaves, so
    :func:`incomplete` refuses it. Within :data:`DESCRIPTION_LIMIT` (or, with no *limit*, any length but that one)
    a text is its own head; otherwise the head is its first characters and the :data:`_CONTINUED` marker, and the
    rest is cut into continuations of at most one short of *limit* (or of :data:`FORGE_CUT`) characters each.
    """
    if limit is None and len(description) != FORGE_CUT:
        return description, ()
    limit = (FORGE_CUT if limit is None else min(limit, FORGE_CUT)) - 1
    if len(description) <= limit:
        return description, ()
    digest = _digest(description)
    count = 1
    while True:  # the marker's width depends on the count it states
        marker = f' >>{count}:{digest}'
        kept = limit - len(marker)
        rest = description[kept:]
        chunks = tuple(rest[start : start + limit] for start in range(0, len(rest), limit))
        if len(chunks) == count:
            return description[:kept] + marker, chunks
        count = len(chunks)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:8]


def joined(items: Sequence[CommitStatus]) -> list[CommitStatus]:
    """Every head of *items* (oldest first) with its continuations joined back; continuations themselves dropped.

    A head takes, per continuation number, the latest one posted no later than itself; one missing or not
    matching the head's digest leaves the head as posted (:func:`incomplete` names it).
    """
    rest: dict[tuple[str, int], list[CommitStatus]] = {}
    heads: list[CommitStatus] = []
    for status in items:
        base, mark, number = status.context.rpartition(CONTINUATION)
        if mark and number.isdigit():
            rest.setdefault((base, int(number)), []).append(status)
        else:
            heads.append(status)
    return [_whole(head, rest) for head in heads]


def _whole(head: CommitStatus, rest: Mapping[tuple[str, int], Sequence[CommitStatus]]) -> CommitStatus:
    found = _CONTINUED.search(head.description)
    if found is None:
        return head
    pieces = [head.description[: found.start()]]
    for number in range(1, int(found['count']) + 1):
        before = [one for one in rest.get((head.context, number), ()) if one.id <= head.id]
        if not before:
            return head
        pieces.append(before[-1].description)
    whole = ''.join(pieces)
    return dataclasses.replace(head, description=whole) if _digest(whole) == found['digest'] else head


def incomplete(description: str) -> str:
    """Why *description* is not the whole text its poster wrote, ``''`` when nothing says it is not.

    A continued head left unjoined names its missing or mismatched continuations; a description exactly
    :data:`FORGE_CUT` long is what a forge's cut leaves (a poster never posts a piece of that length).
    """
    if (found := _CONTINUED.search(description)) is not None:
        return (
            f'its {found["count"]} continuation status(es) {CONTINUATION}1.. are missing or do not match '
            f'digest {found["digest"]}'
        )
    if len(description) == FORGE_CUT:
        return f"cut at {FORGE_CUT} characters, the forge's description limit"
    return ''
