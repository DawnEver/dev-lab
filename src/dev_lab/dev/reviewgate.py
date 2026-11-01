"""REVIEW-IS-REQUIRED: the ONE predicate of whether a head is reviewed -- for the merge and for Break-Glass alike.

User ruling 2026-10-31, "every PR must get a review". A head is reviewed when, and only when, its latest
:data:`~dev_lab.dev.forgecontexts.REVIEW_CONTEXT` is ``success`` and no
:data:`~dev_lab.dev.forgecontexts.HOLD_CONTEXT` is pending. Every other state -- absent, a claim still reviewing,
a takeover pending, an ``error``, a ``failure`` -- is not a review, and :func:`review_missing` names it. Nothing is
advisory: ai-lab #3 and dev-lab #5 were auto-merged with ``tests/review=error`` when an error was.

THE SUCCESS IS VERIFIED AT READ TIME FROM WHAT THE FORGE RECORDS (D11, #11 round 3, F-e4d5c529db40): it counts only
when the forge's own review JOB posted it (:func:`forge_posted`). A status a developer's or an agent's token posted
never satisfies it, whatever environment the poster claimed: every identity the local side asserts is forgeable by a
same-user agent, the forge's record of who wrote is not.

- GitHub records the job token's post as its Actions bot (:data:`~dev_lab.dev._forgebackends.ACTIONS_BOT`).
- Gitea stores it with ``creator_id = -2`` (its Actions user) but its status converter loads the creator with
  ``GetUserByID``, which finds no row for a system user, so the API answers ``"creator": null`` -- exactly as it
  does for a DELETED user's status (``services/convert/status.go``; measured on 1.27.1, 2026-11-01). A null creator
  alone is therefore ambiguous (F-4708098a59c5), and on Gitea the success must ALSO name, as its ``target_url``,
  an Actions run of this repository that the forge's API lists at this very head (:func:`job_run_url` is how the
  job names its own run). A deleted user's status carries no such run; a live user's token is never null.

The remedy for a head whose review could not run is :data:`RERUN`: the forge's own review, run again.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlsplit

from dev_lab.dev._forgebackends import ACTIONS_BOT, GITEA, GITHUB
from dev_lab.dev.forgecontexts import HOLD_CONTEXT, REVIEW_CONTEXT
from dev_lab.dev.forgestatus import status_post

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from dev_lab.dev.forgestatus import CommitStatus
    from dev_lab.dev.forgework import Client

__all__ = ['RERUN', 'forge_posted', 'github_posted', 'job_run_url', 'post_review', 'review_missing']

#: The remedy for a head with no forge-posted review: the forge reviews it again, never a session.
RERUN: Final = "re-run the forge's review of the head (the PR's review job)"

#: How many of the repository's runs at a head are read: a head is re-run a handful of times, never this many.
_RUNS_READ: Final = 50


def github_posted(status: CommitStatus) -> bool:
    """Whether GitHub recorded *status* as its Actions job's: the only creator a job token is given there."""
    return status.creator == ACTIONS_BOT


def _run_path(url: str, owner: str, repo: str) -> str:
    """``/<owner>/<repo>/actions/runs/<n>`` named in *url* (absolute or relative), lower-cased; ``''`` when none."""
    found = re.search(
        rf'/{re.escape(owner)}/{re.escape(repo)}/actions/runs/\d+(?=/|$)', urlsplit(url).path, re.IGNORECASE
    )
    return found.group(0).lower() if found else ''


def forge_posted(client: Client, head: str) -> Callable[[CommitStatus], bool]:
    """The test of whether a status on *head* was posted by *client*'s forge's own review job (module docstring).

    On Gitea the runs at *head* are read once, on the first null-creator status asked about.
    """
    if client.backend is GITHUB:
        return github_posted
    owner, repo = client.forge.owner, client.forge.repo
    runs: list[str] = []

    def at_head() -> list[str]:
        if not runs:
            listed: Any = client.call('GET', f'{client.repo}/actions/runs?head_sha={head}&limit={_RUNS_READ}')
            found = [
                _run_path(run.get('html_url') or '', owner, repo)
                for run in (listed or {}).get('workflow_runs') or ()
                if run.get('head_sha') == head
            ]
            runs.extend(one for one in found if one)
            runs.append('')  # read: an empty answer is not asked twice
        return runs

    def posted(status: CommitStatus) -> bool:
        if status.creator != '':
            return False
        named = _run_path(status.url, owner, repo)
        return bool(named) and named in at_head()

    return posted


def job_run_url(client: Client, env: Mapping[str, str] | None = None) -> str:
    """The web URL of the Actions run this process is a job of, on *client*'s Gitea forge; ``''`` anywhere else.

    Read from the forge (``GET .../actions/runs/{GITHUB_RUN_ID}``), never assembled: a run's web path is its index
    on some Gitea releases and its id on others, and the forge's own ``html_url`` is what :func:`forge_posted`
    compares against.
    """
    env = os.environ if env is None else env
    run_id = env.get('GITHUB_RUN_ID', '')
    if client.backend is not GITEA or env.get('GITEA_ACTIONS') != 'true' or not run_id.isdigit():
        return ''
    return str(client.call('GET', f'{client.repo}/actions/runs/{run_id}').get('html_url') or '')


def post_review(client: Client, head: str, *, state: str, description: str, target_url: str = '') -> None:
    """Post *head*'s :data:`REVIEW_CONTEXT` -- the ONE door every review verdict is posted through.

    Inside Gitea's review job the status names the job's own run (:func:`job_run_url`), which is what
    :func:`forge_posted` verifies; anywhere else it links *target_url* (the round's comment, a carried verdict).
    """
    status_post(client, head, context=REVIEW_CONTEXT, state=state, description=description,
                target_url=job_run_url(client) or target_url)  # fmt: skip


def review_missing(statuses: Sequence[CommitStatus], posted: Callable[[CommitStatus], bool]) -> str | None:
    """Why the head *statuses* (newest first) describe is not reviewed, or ``None`` when it is.

    A ``success`` counts only when *posted* (:func:`forge_posted`) says the forge's review job posted it.
    """
    latest: dict[str, CommitStatus] = {}
    for one in statuses:
        latest.setdefault(one.context, one)
    review, hold = latest.get(REVIEW_CONTEXT), latest.get(HOLD_CONTEXT)
    if review is None:
        return f'{REVIEW_CONTEXT} is not posted: {RERUN}'
    if review.state != 'success':
        return f'{REVIEW_CONTEXT} is {review.state}: {review.description}'
    if not posted(review):
        return (
            f'{REVIEW_CONTEXT} success was posted by {review.creator or "a null creator"} '
            f"(target {review.url or 'none'}), not by the forge's review job at this head: "
            f"only the forge's own review counts -- {RERUN}"
        )
    if hold is not None and hold.state != 'success':
        return f'{HOLD_CONTEXT} is {hold.state}: {hold.description}'
    return None
