"""REVIEW CLAIMS: an author argues a blocking finding is not a defect; an INDEPENDENT reviewer rules, never the author.

User ruling 2026-10-31: humans take no part in daily maintenance, and an author never clears a review's block on its
own work. A head whose review holds an open ``HIGH`` or security finding is ``failure`` on
:data:`~dev_lab.dev.platformparts.REVIEW_CONTEXT`, and the auto-merge waits on it. The finding closes when a later
round's judge finds it fixed or a false positive, or when a CLAIM against it is UPHELD by an independent adjudicator
(:mod:`dev_lab.dev.forgereview_judge`) -- never by the claim itself, and never by a raw status post.

* :func:`blocked` -- the open PR heads into integration whose review is ``failure``; the forge prompts the
  integrator with each (:func:`alarms`), naming the blocking ids and the claim door.
* ``python -m dev_lab.dev.forge review dispose <number> <finding-id> --why "<claim>"`` (:func:`dispose`) records
  the claim as ONE keyed comment naming the claimant, and changes NO status. ``<number>`` is the PR, or a PR-less
  head's ledger issue.
* ``python -m dev_lab.dev.forge review adjudicate <number>`` (:func:`adjudicate_thread`) -- run by the forge (the
  serve tick, or the workflow job a claim's comment triggers) -- judges every pending claim with the same judge a
  round uses, posts each ruling, and re-posts the head's verdict. It refuses a session that authored the head, and a
  claim the adjudicating session made itself.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dev_lab.dev.forgealarm import INTEGRATION, Alarm
from dev_lab.dev.forgemerge import ready
from dev_lab.dev.forgepulls import Marker, comment_upsert, pr_list
from dev_lab.dev.forgereview_declared import Review, judge_for
from dev_lab.dev.forgereview_judge import AdjudicationRefused, Identity, adjudicate, claim, upheld
from dev_lab.dev.forgereview_rounds import DISPOSE_DOOR, blocking, ledger_of, trusted_bodies, verdict
from dev_lab.dev.forgereview_scope import landed_base
from dev_lab.dev.forgestatus import status_list
from dev_lab.dev.labsession import sessions
from dev_lab.dev.platformparts import REVIEW_CONTEXT
from dev_lab.dev.reviewbudget import Raised, raise_line
from dev_lab.dev.reviewgate import post_review

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client, PullRequest

__all__ = ['adjudicate_thread', 'alarms', 'blocked', 'dispose', 'line', 'merge_ready_after', 'raise_cap']


def blocked(client: Client, base: str) -> tuple[tuple[PullRequest, tuple[str, ...]], ...]:
    """The open, non-draft PRs into *base* whose head's review is ``failure``, each with its blocking ids."""
    out = []
    for pull in pr_list(client):
        if pull.base != base or pull.draft or not pull.head_sha:
            continue
        latest = next((one for one in status_list(client, pull.head_sha) if one.context == REVIEW_CONTEXT), None)
        if latest is None or latest.state != 'failure':
            continue
        bodies = trusted_bodies(client, pull.number)
        ledger = ledger_of(bodies)
        ids = () if ledger is None else tuple(one.id for one in blocking(ledger, upheld(bodies)))
        out.append((pull, ids))
    return tuple(out)


def line(pull: PullRequest, ids: tuple[str, ...]) -> str:
    """The prompt line for a review-blocked *pull*: its blocking ids and the claim door."""
    door = DISPOSE_DOOR.format(pr=pull.number, id='<id>')
    return f'#{pull.number} {pull.head_sha[:12]}: review blocks the merge on {", ".join(ids) or "?"} -- fix, or {door}'


def alarms(client: Client, base: str, repo: str) -> list[Alarm]:
    """One ``integration`` prompt per review-blocked head, keyed by its sha, naming the ids and the door."""
    return [
        Alarm(
            INTEGRATION,
            repo,
            f'review blocks {pull.head_sha[:12]} (#{pull.number})',
            f'{line(pull, ids)}. The author fixes it (the next round re-judges it), or claims it is not a defect; '
            'an independent reviewer adjudicates the claim. No human and no author clears a block.',
        )
        for pull, ids in blocked(client, base)
    ]


def dispose(client: Client, number: int, finding_id: str, why: str, *, by: Identity) -> str:
    """Record *by*'s claim against *finding_id* on thread *number*; no status moves. The line said."""
    ledger = ledger_of(trusted_bodies(client, number))
    if ledger is None:
        msg = f'#{number} carries no review round: there is no finding to claim against'
        raise AdjudicationRefused(msg)
    return claim(client, number, finding_id, why, by=by, open_ids=[one.id for one in ledger.open])


def raise_cap(client: Client, number: int, raised: Raised, *, by: Identity) -> str:
    """Record the integrator's raise of PR *number*'s review caps, with its reason; the line said.

    The record names its raiser's login (*by*), and is read only from a comment the forge records as that login's
    (:func:`~dev_lab.dev.forgereview_rounds.trusted_bodies`); the month's remainder still bounds the raised cap.
    """
    if raised.usd is None and raised.rounds is None:
        msg = 'a raise names --usd, --rounds or both'
        raise ValueError(msg)
    if not raised.why.strip():
        msg = 'a raise records its reason: --why "<reason>"'
        raise ValueError(msg)
    text = (
        f'Review cap of #{number} raised by {by.text()}: '
        f'{"" if raised.usd is None else f"{raised.usd:.2f} USD "}'
        f'{"" if raised.rounds is None else f"{raised.rounds} rounds"}'
        f' -- {raised.why}\n\n{raise_line(replace(raised, by=by.login))}'
    )
    comment_upsert(client, number, kind=Marker.REVIEW_CAP, text=text)
    return f'#{number}: review cap raised ({raised.why})'


def adjudicate_thread(
    root: Path, client: Client, review: Review, number: int, *, base: str, adjudicator: Identity,
    run: Callable[[Sequence[str], Path], str], runtimes: Mapping[str, Mapping[str, Any]], dry_run: bool = False,
) -> list[str]:  # fmt: skip
    """Adjudicate every pending claim on thread *number* and re-post its head's verdict; the lines said."""
    bodies = trusted_bodies(client, number)
    ledger = ledger_of(bodies)
    if ledger is None:
        return [f'#{number}: no review round, nothing to adjudicate']
    since = landed_base(root, base, ledger.head)
    judged = judge_for(root, review, f'{since}..{ledger.head}', run, runtimes)
    authors = sessions(root, since, ledger.head)
    said = adjudicate(client, number, ledger.open, bodies, judged=judged, adjudicator=adjudicator, authors=authors,
                      dry_run=dry_run)  # fmt: skip
    if dry_run:
        return said
    state, why = verdict(ledger, upheld(trusted_bodies(client, number)), number)
    post_review(client, ledger.head, state=state, description=f'adjudicated: {why}'[:240])
    return [*said, f'#{number} {ledger.head[:12]}: tests/review {state}', *merge_ready_after(root, client, number)]


def merge_ready_after(root: Path, client: Client, number: int) -> list[str]:
    """Re-post PR *number*'s merge decision after a door moved its review outside a workflow run; the lines said.

    The decision is :func:`dev_lab.dev.forgemerge.ready`'s, the ONE source; a ledger issue is no PR, so nothing.
    #7 (2026-10-31): a ruling moved tests/review and merge-ready stayed stale until someone re-ran it by hand.
    """
    if all(pull.number != number for pull in pr_list(client, state='all')):
        return []
    return [ready(root, client, number)]
