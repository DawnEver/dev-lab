"""A CAPPED REVIEW WARNS AND MERGES (user ruling 2026-11-05): a PR whose review reached its round cap is not held.

"A review at its cap must not block the merge; warn that it merges unreviewed, and merge." -- the round cap
(:mod:`dev_lab.dev.reviewbudget`) stops the REVIEW, never the merge. Only the review condition is waived: tests,
security, conflicts, the audit, draft and every other merge condition still hold
(:func:`dev_lab.dev.forgemerge.decide`).

THE WAIVER IS READ FROM WHAT THE FORGE RECORDS, NEVER FROM A STATUS. A ``tests/review`` description saying
"capped" is a string any token could post; the waiver is decided from the PR's TRUSTED comments
(:func:`~dev_lab.dev.forgereview_rounds.trusted_bodies`): the newest review ledger's round reached the cap the base
declares (``max_rounds``), or a trusted raise set (:func:`~dev_lab.dev.reviewbudget.raised_of`). The dollar cap is not
waived here: it needs the month's spend, which the merging host may not read -- it stays a named wait.

THE WAIVER IS VISIBLE AND RECORDED (DECLARATION-LIES). ``tests/review`` is never posted ``success`` for it; the merge
commit carries :data:`UNREVIEWED` naming the cap and the open findings, and the merge decision says the same.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dev_lab.dev.forgereview_declared import forge_review
from dev_lab.dev.forgereview_rounds import ledger_of, trusted_bodies
from dev_lab.dev.reviewbudget import raised_of

if TYPE_CHECKING:
    from collections.abc import Iterable

    from dev_lab.dev.forgework import Client

__all__ = ['UNREVIEWED', 'capped_waiver', 'waiver_of']

#: The merge-commit line (and decision note) of a merge whose review was capped, never passed.
UNREVIEWED: Final = 'Unreviewed'


def waiver_of(bodies: Iterable[str], *, max_rounds: int) -> str | None:
    """``Unreviewed: ...`` when the trusted comment *bodies* show the round cap reached, else ``None``.

    The cap is *max_rounds*, or a trusted raise's rounds; the open findings are the newest ledger's.
    """
    bodies = list(bodies)
    ledger = ledger_of(bodies)
    if ledger is None:
        return None
    raised = raised_of(bodies)
    cap = raised.rounds if raised is not None and raised.rounds is not None else max_rounds
    if ledger.round < cap:
        return None
    found = ', '.join(one.id for one in ledger.open) or 'none'
    return f'{UNREVIEWED}: review capped at {cap} rounds; open findings: {found}'


def capped_waiver(client: Client, number: int, *, base: str) -> str | None:
    """:func:`waiver_of` PR *number* as the forge holds it, under the review *base* declares (trusted)."""
    review = forge_review(client, base)
    return waiver_of(trusted_bodies(client, number, review.reviewers), max_rounds=review.max_rounds)
