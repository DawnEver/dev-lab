"""REVIEW DISPOSITION: the integrator closes a blocking finding it will not have fixed, with a reason, through a door.

User ruling 2026-10-26. A head whose review holds an open ``HIGH`` or security finding is ``failure`` on
:data:`~dev_lab.dev.platformparts.REVIEW_CONTEXT`, and the auto-merge waits on it
(:mod:`dev_lab.dev.forgereview_rounds`). The finding closes when a later round finds its anchor line gone, or when
the INTEGRATOR disposes of it here -- never by a raw status post (``REVIEW-HOLD-VIA-TAKEOVER`` refuses one).

* :func:`blocked` -- the open PR heads into integration whose review is ``failure``; the forge prompts the
  integrator with each (:func:`alarms`, one ``integration`` issue per head, and ``forge notices --integrator``),
  naming the blocking ids and this door. A human is asked only when the integrator and the author disagree.
* ``python -m dev_lab.dev.forge review dispose <pr> <finding-id> --why "<reason>"`` (:func:`dispose`) records
  the disposition as ONE keyed comment (``Marker.DISPOSITION``) and re-posts the reviewed head's verdict. Refused
  without a reason, and for an id the PR's newest review round does not hold open.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dev_lab.dev.forgealarm import INTEGRATION, Alarm
from dev_lab.dev.forgepulls import Marker, comment_upsert, pr_list
from dev_lab.dev.forgereview_rounds import (
    DISPOSE_DOOR,
    blocking,
    disposed,
    disposition_text,
    ledger_of,
    trusted_bodies,
    verdict,
)
from dev_lab.dev.forgestatus import status_list, status_post
from dev_lab.dev.platformparts import REVIEW_CONTEXT

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client, PullRequest

__all__ = ['DisposeRefused', 'alarms', 'blocked', 'dispose', 'line']

_MIN_WHY: Final = 10  # characters: a reason, not a shrug


class DisposeRefused(ValueError):
    """The door will not dispose of this finding, and says why."""


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
        ids = () if ledger is None else tuple(one.id for one in blocking(ledger, disposed(bodies)))
        out.append((pull, ids))
    return tuple(out)


def line(pull: PullRequest, ids: tuple[str, ...]) -> str:
    """The prompt line for a review-blocked *pull*: its blocking ids and the door."""
    door = DISPOSE_DOOR.format(pr=pull.number, id='<id>')
    return f'#{pull.number} {pull.head_sha[:12]}: review blocks the merge on {", ".join(ids) or "?"} -- fix, or {door}'


def alarms(client: Client, base: str, repo: str) -> list[Alarm]:
    """One ``integration`` prompt per review-blocked head, keyed by its sha, naming the ids and the door."""
    return [
        Alarm(
            INTEGRATION,
            repo,
            f'review blocks {pull.head_sha[:12]} (#{pull.number})',
            f'{line(pull, ids)}. The integrator judges each blocking finding: the author fixes it (the next round '
            'confirms), or the integrator disposes of it with a reason; a human is asked only when the integrator '
            'and the author disagree.',
        )
        for pull, ids in blocked(client, base)
    ]


def dispose(client: Client, number: int, finding_id: str, why: str, *, host: str) -> str:
    """Record the integrator's disposition of *finding_id* on PR *number* and re-post its verdict; the line said."""
    if len(why.strip()) < _MIN_WHY:
        msg = f'a disposition needs its reason: --why "<at least {_MIN_WHY} characters>"'
        raise DisposeRefused(msg)
    bodies = trusted_bodies(client, number)
    ledger = ledger_of(bodies)
    if ledger is None:
        msg = f'#{number} carries no review round: there is no finding to dispose of'
        raise DisposeRefused(msg)
    if all(one.id != finding_id for one in ledger.open):
        held = ', '.join(one.id for one in ledger.open) or 'none'
        msg = f'{finding_id} is not open in #{number} review round {ledger.round} (open: {held})'
        raise DisposeRefused(msg)
    _, comment = comment_upsert(
        client, number, kind=Marker.DISPOSITION, key=finding_id, text=disposition_text(finding_id, host, why)
    )
    gone = disposed([*bodies, comment.body if comment else ''])
    state, said = verdict(ledger, gone, number)
    status_post(client, ledger.head, context=REVIEW_CONTEXT, state=state, description=said,
                target_url=comment.url if comment else '')  # fmt: skip
    return f'#{number} {ledger.head[:12]}: {finding_id} disposed by {host}; tests/review {state}'
