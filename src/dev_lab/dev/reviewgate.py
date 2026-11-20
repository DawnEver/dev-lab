"""The ONE predicate of whether a head is reviewed: a REPORT, never a merge condition.

The review is ADVISORY on both forges (user rulings 2026-11-11/12; it replaced the 2026-10-31 "every PR must get a
review" gate): it runs and posts, and the merge decision (:mod:`dev_lab.dev.forgemerge`) reports this
predicate's answer, never wait on it. A head is reviewed when, and only when, its latest
:data:`~dev_lab.dev.forgecontexts.REVIEW_CONTEXT` is ``success`` and no
:data:`~dev_lab.dev.forgecontexts.HOLD_CONTEXT` is pending. Every other state -- absent, a claim still reviewing,
an ``error``, a ``failure`` (a security finding) -- is not a review, and :func:`review_missing` names it. A review
that DID NOT RUN leaves its recorded cause (:mod:`dev_lab.dev.reviewcap`) in the merge message.

WHO POSTED A SUCCESS COUNTS ONLY WHERE THE FORGE VETS AUTHORS (:func:`forge_posted`; user ruling 2026-11-06,
"Gitea is safe; vetting is for GitHub", extended to review statuses the same day). GitHub
(:attr:`~dev_lab.dev._forgebackends.Backend.vets_authors`) counts its Actions bot's post alone
(:data:`~dev_lab.dev._forgebackends.ACTIONS_BOT`, D11): a developer's or an agent's token never satisfies it. Gitea
is private and vets no author, so a success counts whoever posted it -- the serve's login, an Actions job's null
creator, an agent -- exactly as :meth:`~dev_lab.dev.forgework.Client.trusts` trusts every login there.

The remedy for a head whose review could not run is :data:`RERUN`: the forge's own review, run again.
"""

from __future__ import annotations

import base64
import contextlib
import os
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Final, Protocol
from urllib.parse import quote

from dev_lab.dev._forgebackends import ACTIONS_BOT, GITEA, GITHUB
from dev_lab.dev.forgecontexts import HOLD_CONTEXT, JUDGE_CHECK, REVIEW_CONTEXT
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgestatus import status_post

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping, Sequence

    from dev_lab.dev.forgestatus import CommitStatus
    from dev_lab.dev.forgework import Client

    #: Why the head the statuses (newest first) describe is not reviewed, or ``None``: what a gate answers.
    type Reviewed = Callable[[Sequence[CommitStatus]], str | None]

__all__ = [
    'APPROVED',
    'RERUN',
    'VERDICT_STATES',
    'DeclarationUnread',
    'app_verdicts',
    'forge_posted',
    'github_posted',
    'job_run_url',
    'manifest_at',
    'post_review',
    'posted_verdicts',
    'review_missing',
    'standing_verdicts',
    'status_gate',
]

#: The remedy for a head with no forge-posted review: the forge reviews it again, never a session.
RERUN: Final = "re-run the forge's review of the head (the PR's review job)"

#: The PR review state of an approval, and every state a judge's verdict leaves, as each forge reports them back.
APPROVED: Final = 'APPROVED'
VERDICT_STATES: Final = frozenset({APPROVED, 'REQUEST_CHANGES', 'CHANGES_REQUESTED'})

_NOT_FOUND: Final = 404


def github_posted(status: CommitStatus) -> bool:
    """Whether GitHub recorded *status* as its Actions job's: the only creator a job token is given there."""
    return status.creator == ACTIONS_BOT


class DeclarationUnread(ValueError):
    """The repo's ``pyproject.toml`` at a ref could not be read: whose review counts is undecided, so none does."""


class RepoReader(Protocol):
    """What :func:`manifest_at` asks of a client: its repository path and one forge call."""

    @property
    def repo(self) -> str: ...

    def call(self, method: str, path: str, /) -> object: ...


def manifest_at(client: RepoReader, ref: str) -> str:
    """The repo's ``pyproject.toml`` text at *ref*, as the forge holds it -- never a working tree (:func:`file_at`)."""
    return file_at(client, 'pyproject.toml', ref)


def file_at(client: RepoReader, path: str, ref: str) -> str:
    """The text of *path* at *ref* in the client's repo, as the forge holds it -- never a working tree.

    Raises:
        DeclarationUnread: the file is absent at *ref*, cannot be read, or the answer carries no content.

    """
    try:
        answer: Any = client.call('GET', f'{client.repo}/contents/{quote(path)}?ref={ref}')
    except ForgeCallFailed as failed:
        msg = f'{path} at {ref} cannot be read: {failed}'
        raise DeclarationUnread(msg) from failed
    content = answer.get('content') if isinstance(answer, dict) else None
    if not content:
        msg = f'{path} at {ref}: the forge answered no content'
        raise DeclarationUnread(msg)
    return base64.b64decode(content).decode()


def forge_posted(client: Client) -> Callable[[CommitStatus], bool]:
    """The test of whether a status counts as *client*'s forge's own review (module docstring).

    Where the backend vets authors (GitHub) only its Actions bot's post counts (:func:`github_posted`); elsewhere
    (Gitea) every post does.
    """
    return github_posted if client.backend.vets_authors else lambda _status: True


def job_run_url(client: Client, env: Mapping[str, str] | None = None) -> str:
    """The web URL of the Actions run this process is a job of, on *client*'s Gitea forge; ``''`` anywhere else.

    Read from the forge (``GET .../actions/runs/{GITHUB_RUN_ID}``), never assembled: a run's web path is its index
    on some Gitea releases and its id on others; the status links the run that posted it.
    """
    env = os.environ if env is None else env
    run_id = env.get('GITHUB_RUN_ID', '')
    if client.backend is not GITEA or env.get('GITEA_ACTIONS') != 'true' or not run_id.isdigit():
        return ''
    return str(client.call('GET', f'{client.repo}/actions/runs/{run_id}').get('html_url') or '')


#: The states :func:`post_review` posted inside :func:`posted_verdicts`, in order; ``None`` outside it.
_POSTED: ContextVar[list[str] | None] = ContextVar('posted_verdicts', default=None)


@contextlib.contextmanager
def posted_verdicts() -> Iterator[list[str]]:
    """The states every :func:`post_review` inside the block posts, in order -- what THIS process said.

    The review job's exit is read from it (:func:`dev_lab.dev.forgereview_job.job_exit`): the door that posts is the
    one that knows, never a re-read of the head.
    """
    said: list[str] = []
    token = _POSTED.set(said)
    try:
        yield said
    finally:
        _POSTED.reset(token)


def post_review(client: Client, head: str, *, state: str, description: str, target_url: str = '') -> None:
    """Post *head*'s :data:`REVIEW_CONTEXT` -- the ONE door every review status is posted through.

    Inside Gitea's review job the status links the job's own run (:func:`job_run_url`); anywhere else it links
    *target_url* (the review's comment, a standing verdict).
    """
    status_post(client, head, context=REVIEW_CONTEXT, state=state, description=description,
                target_url=job_run_url(client) or target_url)  # fmt: skip
    if (said := _POSTED.get()) is not None:
        said.append(state)


def status_gate(posted: Callable[[CommitStatus], bool]) -> Reviewed:
    """The serve-mode reading: :func:`review_missing` over a head's statuses, *posted* telling the forge's own post."""
    return lambda statuses: review_missing(statuses, posted)


def _hold_missing(statuses: Sequence[CommitStatus]) -> str | None:
    hold = next((one for one in statuses if one.context == HOLD_CONTEXT), None)
    if hold is not None and hold.state != 'success':
        return f'{HOLD_CONTEXT} is {hold.state}: {hold.description}'
    return None


def standing_verdicts(reviews: Sequence[Mapping[str, Any]], *, login: str, head: str) -> list[Mapping[str, Any]]:
    """*login*'s verdict reviews (:data:`VERDICT_STATES`) at *head* that stand: neither dismissed nor stale.

    Gitea keeps a dismissed review's state and marks it ``dismissed``, and marks one ``stale`` once the head moves;
    GitHub reports a dismissal as the state ``DISMISSED``, never a verdict state.
    """
    return [
        row for row in reviews
        if (row.get('user') or {}).get('login') == login and row.get('commit_id') == head
        and row.get('state') in VERDICT_STATES and not row.get('dismissed') and not row.get('stale')
    ]  # fmt: skip


def app_verdicts(client: Client, head: str) -> list[dict[str, Any]]:
    """Every :data:`~dev_lab.dev.forgecontexts.JUDGE_CHECK` check run GitHub lists at *head*, whoever posted it."""
    if client.backend is not GITHUB:
        msg = f'judge_app is a GitHub App, and {client.forge.host} is no GitHub: declare judge_login there'
        raise DeclarationUnread(msg)
    listed: Any = client.call('GET', f'{client.repo}/commits/{head}/check-runs?check_name={JUDGE_CHECK}&per_page=100')
    runs = listed.get('check_runs') if isinstance(listed, dict) else None
    return [row for row in runs or [] if isinstance(row, dict)]


def review_missing(statuses: Sequence[CommitStatus], posted: Callable[[CommitStatus], bool]) -> str | None:
    """Why the head *statuses* (newest first) describe is not reviewed, or ``None`` when it is.

    A ``success`` counts only when *posted* (:func:`forge_posted`) counts its poster.
    """
    latest: dict[str, CommitStatus] = {}
    for one in statuses:
        latest.setdefault(one.context, one)
    review = latest.get(REVIEW_CONTEXT)
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
    return _hold_missing(statuses)
