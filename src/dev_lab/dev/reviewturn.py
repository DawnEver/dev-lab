"""REVIEW IS THE LAST GATE: the merge decision asks for a head's review, and nothing else does.

User ruling 2026-11-05 ("a PR is reviewed only when it is about to be merged into integrate/main"). The review is
the one merge condition that costs a model call and a round against the PR's cap, so :func:`review_turn` -- run on
the decision of :mod:`dev_lab.dev.forgemerge` by ``forge merge ready`` and by the serve's integration tick -- says on
the head's ``tests/review`` whether it waits (another condition missing) or is due (only the review missing). The
review reads that before it runs (:func:`dev_lab.dev.forgereview.review_pull`).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Final

from dev_lab.dev.forgereview_claim import DESCRIPTION, DUE, WAITS
from dev_lab.dev.forgestatus import status_list
from dev_lab.dev.forgework import GITEA
from dev_lab.dev.platformparts import REVIEW_CONTEXT
from dev_lab.dev.reviewgate import post_review

if TYPE_CHECKING:
    from collections.abc import Mapping

    from dev_lab.dev.forgemerge import Decision
    from dev_lab.dev.forgework import Client

__all__ = ['REVIEW_DUE_SAID', 'REVIEW_LABEL', 'review_turn']

#: What the decision's line ends with when the head's review is due: a GitHub job reads it to start the review.
REVIEW_DUE_SAID: Final = '; review due'

#: The PR label whose ``labeled`` event starts a Gitea repo's review (``review.yml``) and bundle prepare: Gitea starts
#: no workflow for an event its Actions user raised, so the decision run by a serve (its own login) applies it.
REVIEW_LABEL: Final = 'review-due'

#: The label's colour when the decision creates it on a repo that lacks it.
_LABEL_COLOR: Final = '#0e8a16'


def review_turn(
    client: Client, number: int, head: str, decision: Decision, env: Mapping[str, str] | None = None
) -> str:
    """Say on *head*'s ``tests/review`` what *decision* means for its review; what the decision's line adds.

    THE ONE PLACE A REVIEW IS ASKED FOR (module docstring). Nothing, when the head is reviewed or its review status is
    the review's own (a claim, a batch, a cap, a verdict, a hold for a takeover): that stands. Else, posted only when
    it changes -- :data:`~dev_lab.dev.forgereview_claim.WAITS` naming every other missing condition, or, when none is
    missing, :data:`~dev_lab.dev.forgereview_claim.DUE` (the line ends :data:`REVIEW_DUE_SAID`). On Gitea DUE also
    applies :data:`REVIEW_LABEL` (:func:`_request`), and only outside an Actions job (*env*): Gitea starts no workflow
    for its Actions user's event, so a DUE posted there would start nothing and stop the serve from asking.
    """
    if decision.review is None:
        return ''
    latest = next((one for one in status_list(client, head) if one.context == REVIEW_CONTEXT), None)
    if latest is not None and not (latest.state == 'pending' and latest.description.startswith((WAITS, DUE))):
        return ''
    if decision.others:
        why = (WAITS + '; '.join(decision.others))[:DESCRIPTION]
        if latest is None or latest.description != why:
            post_review(client, head, state='pending', description=why)
        return '; review waits'
    if client.backend is GITEA and (os.environ if env is None else env).get('GITEA_ACTIONS') == 'true':
        return f'{REVIEW_DUE_SAID}: a serve asks for it (Gitea starts no workflow for its Actions user)'
    if latest is None or latest.description != DUE:
        post_review(client, head, state='pending', description=DUE)
        if client.backend is GITEA:
            _request(client, number)
    return REVIEW_DUE_SAID


def _request(client: Client, number: int) -> None:
    """Apply :data:`REVIEW_LABEL` to PR *number* afresh, so the forge raises the ``labeled`` event.

    The review and prepare workflows start on that event. A label a superseded head left is removed first; the label
    is created when the repository lacks it.
    """
    labels: Any = client.call('GET', f'{client.repo}/labels?limit=50')
    found = next((one for one in labels or () if isinstance(one, dict) and one.get('name') == REVIEW_LABEL), None)
    if found is None:
        found = client.call('POST', f'{client.repo}/labels', {'name': REVIEW_LABEL, 'color': _LABEL_COLOR})
    label = int(found['id'])
    held: Any = client.call('GET', f'{client.repo}/issues/{number}/labels')
    if any(isinstance(one, dict) and one.get('id') == label for one in held or ()):
        client.call('DELETE', f'{client.repo}/issues/{number}/labels/{label}')
    client.call('POST', f'{client.repo}/issues/{number}/labels', {'labels': [label]})
