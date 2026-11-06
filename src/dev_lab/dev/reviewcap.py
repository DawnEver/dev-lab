"""A REVIEW THAT DID NOT RUN NEVER HOLDS THE MERGE (user rulings 2026-11-05, 2026-11-06): it merges ``Unreviewed``.

The review is an independent acceptance check with advice (:mod:`dev_lab.dev.forgereview_advice`). When it cannot
give one -- the PR's dollar cap or the month is spent (:mod:`dev_lab.dev.reviewbudget`), the reviewer failed, every
reviewer was unsupported, exhausted or unauthorised, or the job holds no review key -- the reviewing host RECORDS why
on the PR (:func:`unreviewed_line`), and the merge waives the review condition alone: tests, the security status,
conflicts, the audit, draft and every other merge condition still hold (:func:`dev_lab.dev.forgemerge.decide`).

THE WAIVER IS READ FROM WHAT THE FORGE RECORDS, NEVER FROM A STATUS. A ``tests/review`` description is a string any
token could post; the waiver is decided from the PR's TRUSTED comments
(:func:`~dev_lab.dev.forgereview_advice.trusted_bodies`): the newest unreviewed record, unless a review record or a
cap raise came after it (the review ran since, or may).

THE WAIVER IS VISIBLE AND RECORDED (DECLARATION-LIES). ``tests/review`` is never posted ``success`` for it; the merge
commit carries :data:`UNREVIEWED` naming the cause, and the merge decision says the same.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Final

from dev_lab.dev.forgereview_advice import trusted_bodies
from dev_lab.dev.forgereview_declared import forge_review

if TYPE_CHECKING:
    from collections.abc import Iterable

    from dev_lab.dev.forgework import Client

__all__ = ['UNREVIEWED', 'unreviewed_line', 'unreviewed_waiver', 'waiver_of']

#: The merge-commit line (and decision note) of a merge whose review did not run, never passed.
UNREVIEWED: Final = 'Unreviewed'

_RECORD: Final = re.compile(r'<!-- review-capped (?P<json>\{.*?\}) -->', re.DOTALL)
_SUPERSEDING: Final = re.compile(r'<!-- review-(?:ledger|cap) \{')


def unreviewed_line(why: str) -> str:
    """The hidden line the reviewing host records why the review did not run by (``>`` escaped)."""
    return f'<!-- review-capped {json.dumps({"why": why}, ensure_ascii=False).replace(">", ">")} -->'


def waiver_of(bodies: Iterable[str]) -> str | None:
    """``Unreviewed: ...`` when the trusted comment *bodies* (oldest first) record a review that did not run."""
    cause = None
    for body in bodies:
        if _SUPERSEDING.search(body):
            cause = None
        for match in _RECORD.finditer(body):
            try:
                why = json.loads(match['json']).get('why')
            except (ValueError, AttributeError):
                continue
            cause = why if isinstance(why, str) else cause
    return None if cause is None else f'{UNREVIEWED}: {cause}'


def unreviewed_waiver(client: Client, number: int, *, base: str) -> str | None:
    """:func:`waiver_of` PR *number* as the forge holds it, under the review *base* declares (trusted).

    A declaration that cannot be read waives nothing: the review gate names it and the merge waits, never crashes.
    """
    try:
        review = forge_review(client, base)
    except ValueError:
        return None
    return waiver_of(trusted_bodies(client, number, review.reviewers))
