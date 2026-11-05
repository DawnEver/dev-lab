"""A CAPPED REVIEW WARNS AND MERGES (user ruling 2026-11-05): a PR whose review reached a cap is not held.

"The dollar cap no longer blocks either; the code lets everything through, security findings included" -- the caps
(:mod:`dev_lab.dev.reviewbudget`) stop the REVIEW, never the merge. Only the review condition is waived: tests,
the security status, conflicts, the audit, draft and every other merge condition still hold
(:func:`dev_lab.dev.forgemerge.decide`); open findings, security ones included, merge named.

THE WAIVER IS READ FROM WHAT THE FORGE RECORDS, NEVER FROM A STATUS. A ``tests/review`` description saying
"capped" is a string any token could post; the waiver is decided from the PR's TRUSTED comments
(:func:`~dev_lab.dev.forgereview_rounds.trusted_bodies`), either of:

* the ROUND cap -- the newest review ledger's round reached the cap the base declares (``max_rounds``), or a trusted
  raise's rounds (:func:`~dev_lab.dev.reviewbudget.raised_of`); readable on any host;
* the reviewing host's own CAP RECORD (:func:`capped_line`) -- the budget gate's refusal (``budget reached``, the
  month spent, a degraded round cap), which needs the month's spend the merging host may not read, so the host that
  computed it records it on the PR. A ledger or a raise after the record supersedes it (the review ran again, or
  may).

THE WAIVER IS VISIBLE AND RECORDED (DECLARATION-LIES). ``tests/review`` is never posted ``success`` for it; the merge
commit carries :data:`UNREVIEWED` naming the cap and the open findings, and the merge decision says the same.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Final

from dev_lab.dev.forgereview_declared import forge_review
from dev_lab.dev.forgereview_rounds import ledger_of, trusted_bodies
from dev_lab.dev.reviewbudget import raised_of

if TYPE_CHECKING:
    from collections.abc import Iterable

    from dev_lab.dev.forgework import Client

__all__ = ['UNREVIEWED', 'capped_line', 'capped_waiver', 'waiver_of']

#: The merge-commit line (and decision note) of a merge whose review was capped, never passed.
UNREVIEWED: Final = 'Unreviewed'

_RECORD: Final = re.compile(r'<!-- review-capped (?P<json>\{.*?\}) -->', re.DOTALL)
_SUPERSEDING: Final = re.compile(r'<!-- review-(?:ledger|cap) \{')


def capped_line(why: str) -> str:
    """The hidden line the reviewing host records a budget gate's refusal *why* by (``>`` escaped)."""
    return f'<!-- review-capped {json.dumps({"why": why}, ensure_ascii=False).replace(">", "\u003e")} -->'


def _recorded(bodies: Iterable[str]) -> str | None:
    """The newest cap record's cause in *bodies* (oldest first), unless a ledger or a raise came after it."""
    cause = None
    for body in bodies:
        if _SUPERSEDING.search(body):
            cause = None
        for match in _RECORD.finditer(body):
            try:
                why = json.loads(match['json']).get('why')
            except (ValueError, AttributeError):
                continue
            cause = why.split('; ', 1)[0] if isinstance(why, str) else cause
    return cause


def waiver_of(bodies: Iterable[str], *, max_rounds: int) -> str | None:
    """``Unreviewed: ...`` when the trusted comment *bodies* show a review cap reached, else ``None``.

    The round cap is *max_rounds*, or a trusted raise's rounds; else a cap record (:func:`capped_line`) names it. The
    open findings are the newest ledger's.
    """
    bodies = list(bodies)
    ledger = ledger_of(bodies)
    found = ', '.join(one.id for one in ledger.open) if ledger is not None else ''
    raised = raised_of(bodies)
    cap = raised.rounds if raised is not None and raised.rounds is not None else max_rounds
    if ledger is not None and ledger.round >= cap:
        cause = f'capped at {cap} rounds'
    elif (cause := _recorded(bodies)) is None:
        return None
    return f'{UNREVIEWED}: review {cause}; open findings: {found or "none"}'


def capped_waiver(client: Client, number: int, *, base: str) -> str | None:
    """:func:`waiver_of` PR *number* as the forge holds it, under the review *base* declares (trusted).

    A declaration that cannot be read waives nothing: the review gate names it and the merge waits, never crashes.
    """
    try:
        review = forge_review(client, base)
    except ValueError:
        return None
    return waiver_of(trusted_bodies(client, number, review.reviewers), max_rounds=review.max_rounds)
