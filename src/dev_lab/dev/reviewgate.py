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

ON GITEA THE VERDICT IS THE RUN'S, NOT A STATUS'S (dev-lab #30, user ruling 2026-11-01, option (b)). Gitea runs a
``pull_request`` workflow from the PR HEAD, and EVERY Actions job's status is ``creator: null``: a PR adding an
``on: pull_request`` workflow could post that same null-creator success naming the honest run. So review.yml is
triggered by ``pull_request_target``, which Gitea detects from the BASE commit (``notifier_helper.go``, 1.27) -- the
PR can neither change what runs nor read the secret -- and a success counts only when, besides the status checks
above, the latest CONCLUDED run at this head that is that workflow (``event == "pull_request_target"``, ``path``
``review.yml@<ref>``, :func:`review_runs`) concluded ``success``. A PR-head workflow can neither create nor alter
such a run, and the job exits non-zero unless it posted success (:func:`dev_lab.dev.forgereview_job.job_exit`, from
what :func:`post_review` recorded in :func:`posted_verdicts`). A run with no conclusion -- queued, running, or
RE-RUN IN PLACE (Gitea keeps its id and resets its conclusion while it executes) -- decides nothing, and the newest
run that has one decides. A head whose only review run is being re-run therefore waits for it to conclude: its
earlier conclusion is no longer observable, so a success naming it cannot be told from one a PR-head workflow
planted during a first run. That re-run reviews the head afresh
(:attr:`~dev_lab.dev.forgereview_command.Runner.verifies`) and concludes by its own post.

ON GITEA THE BASE'S DECLARATION ALONE SAYS WHICH IDENTITY IS THE FORGE (:func:`adopts_actions_review`): a repo whose
integration branch declares ``[tool.dev_lab.ci."review.yml"]`` (it renders ``.gitea/workflows/review.yml``) is judged
by the Actions rule above. Under ``pull_request_target`` only the base's workflow ever runs, so a PR that adopts
review.yml is reviewed by the serve rule until it lands -- an adoption read at the head would wait forever for an
Actions review that cannot come -- and a PR never un-adopts it: the base is the integration branch, which the PR
cannot edit. A repo not declaring it at its base has no review job: its review is posted by ``forge serve``, and the
forge is the login the judging client authenticates as (:meth:`~dev_lab.dev.forgework.Client.whoami`) -- the pre-#14
rule (be39f7a6, ``forge_bots`` with ``[tool.dev_lab.review] forge_bot`` = "the login forge serve posts as"), its
identity now read from the forge rather than declared. RESIDUAL, ACCEPTED ON RECORD (D18, "fake isolation"): on a
Gitea host the serve's login is shared with the agents on that host, so until the repo adopts the Actions review a
same-host agent's token is indistinguishable from the serve's.
A declaration that cannot be read -- no ``pyproject.toml``, an answer without content -- refuses
(:class:`DeclarationUnread`); only a parsed manifest lacking the table is "not adopted". A runs listing the forge
answers without a list refuses too (:class:`RunsUnread`), as a failed call does: never a pass.

The remedy for a head whose review could not run is :data:`RERUN`: the forge's own review, run again.
"""

from __future__ import annotations

import base64
import contextlib
import os
import re
import tomllib
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlsplit

from dev_lab.dev._forgebackends import ACTIONS_BOT, GITEA, GITHUB
from dev_lab.dev.family import declared_table
from dev_lab.dev.forgecontexts import HOLD_CONTEXT, REVIEW_CONTEXT
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgepulls import pages
from dev_lab.dev.forgestatus import status_post

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping, Sequence

    from dev_lab.dev._forgebackends import Backend
    from dev_lab.dev.forgestatus import CommitStatus
    from dev_lab.dev.forgework import Client

    #: Why the head the statuses (newest first) describe is not reviewed, or ``None``: what a gate answers.
    type Reviewed = Callable[[Sequence[CommitStatus]], str | None]

__all__ = [
    'ACTIONS_REVIEW',
    'APPROVED',
    'PREPARE_WORKFLOW',
    'RERUN',
    'VERDICT_STATES',
    'DeclarationUnread',
    'RunsUnread',
    'adopts_actions_review',
    'forge_posted',
    'github_posted',
    'head_reviews',
    'job_run_url',
    'judge_missing',
    'manifest_at',
    'post_review',
    'posted_verdicts',
    'review_missing',
    'review_runs',
    'run_path',
    'standing_verdicts',
    'status_gate',
]

#: The remedy for a head with no forge-posted review: the forge reviews it again, never a session.
RERUN: Final = "re-run the forge's review of the head (the PR's review job)"

#: The ``[tool.dev_lab.ci]`` workflow whose declaration adopts Gitea Actions as the forge's reviewer.
ACTIONS_REVIEW: Final = 'review.yml'

#: The base's workflow whose run attaches a judge repo's bundle (:mod:`~dev_lab.dev.forgereview_pointer`);
#: :mod:`~dev_lab.dev.ciworkflows` renders it, on either forge, under this name: the one the judge lists runs by.
PREPARE_WORKFLOW: Final = 'review-prepare.yml'

#: The event a run of the BASE's workflow for a PR is stored under (Gitea: ``notifier_helper.go``, 1.27; GitHub alike).
REVIEW_EVENT: Final = 'pull_request_target'

#: The PR review state of an approval, and every state a judge's verdict leaves, as each forge reports them back.
APPROVED: Final = 'APPROVED'
VERDICT_STATES: Final = frozenset({APPROVED, 'REQUEST_CHANGES', 'CHANGES_REQUESTED'})

#: How many of the repository's runs at a head are read: a head is re-run a handful of times, never this many.
_RUNS_READ: Final = 50

_NOT_FOUND: Final = 404


def github_posted(status: CommitStatus) -> bool:
    """Whether GitHub recorded *status* as its Actions job's: the only creator a job token is given there."""
    return status.creator == ACTIONS_BOT


def run_path(url: str, owner: str, repo: str) -> str:
    """``/<owner>/<repo>/actions/runs/<n>`` named in *url* (absolute or relative), lower-cased; ``''`` when none."""
    found = re.search(
        rf'/{re.escape(owner)}/{re.escape(repo)}/actions/runs/\d+(?=/|$)', urlsplit(url).path, re.IGNORECASE
    )
    return found.group(0).lower() if found else ''


class DeclarationUnread(ValueError):
    """The repo's ``pyproject.toml`` at a ref could not be read: whose review counts is undecided, so none does."""


class RunsUnread(ValueError):
    """The forge's runs at a head could not be read: whether its review run concluded success is undecided."""


def manifest_at(client: Client, ref: str) -> str:
    """The repo's ``pyproject.toml`` text at *ref*, as the forge holds it -- never a working tree.

    Raises:
        DeclarationUnread: the file is absent at *ref*, or the forge's answer carries no content.

    """
    try:
        answer: Any = client.call('GET', f'{client.repo}/contents/pyproject.toml?ref={ref}')
    except ForgeCallFailed as failed:
        msg = f'pyproject.toml at {ref} cannot be read: {failed}'
        raise DeclarationUnread(msg) from failed
    content = answer.get('content') if isinstance(answer, dict) else None
    if not content:
        msg = f'pyproject.toml at {ref}: the forge answered no content'
        raise DeclarationUnread(msg)
    return base64.b64decode(content).decode()


def adopts_actions_review(client: Client, ref: str) -> bool:
    """Whether the repo's ``pyproject.toml`` at *ref* (:func:`manifest_at`) declares :data:`ACTIONS_REVIEW`."""
    return ACTIONS_REVIEW in declared_table(tomllib.loads(manifest_at(client, ref)), 'ci', {})


def review_runs(
    client: Client, head: str, *, workflow: str = ACTIONS_REVIEW, pull: int | None = None
) -> list[dict[str, Any]]:
    """The runs of the base's *workflow* (:data:`ACTIONS_REVIEW`) at *head*, newest first, as the forge lists them.

    Only a :data:`REVIEW_EVENT` run whose ``path`` is ``review.yml@<ref>`` (Gitea's converter:
    ``fmt.Sprintf("%s@%s", run.WorkflowID, run.Ref)``, the entry file's name) -- the one workflow a PR cannot edit.
    Given *pull*, only a run of THAT pull request (:func:`_of_workflow`; Gitea: ``<ref>`` is its
    ``refs/pull/<n>/head``, GitHub: its ``pull_requests``), so a second PR of the same head into a branch whose
    workflow its author wrote is never one of them.
    """
    query = f'head_sha={head}&{client.backend.page_param}={_RUNS_READ}'
    listed: Any = client.call('GET', f'{client.repo}/actions/runs?{query}')
    runs = (listed or {}).get('workflow_runs') if isinstance(listed, dict) else None
    if not isinstance(runs, list):
        msg = f'the runs at {head[:12]}: the forge answered no list'
        raise RunsUnread(msg)
    honest = [
        run for run in runs
        if run.get('head_sha') == head and run.get('event') == REVIEW_EVENT
        and _of_workflow(run, workflow, pull, client.backend)
    ]  # fmt: skip
    return sorted(honest, key=lambda run: int(run.get('id') or 0), reverse=True)


def _of_workflow(run: dict[str, Any], workflow: str, pull: int | None, backend: Backend) -> bool:
    """Whether *run* is of the base's *workflow* -- given *pull*, for THAT pull request alone.

    Gitea names the pull request in the run's ``path``. GitHub lists the file alone and names the pull request in
    ``pull_requests``, which must be exactly *pull*: a fork's run lists none and a run listing two is undecided, so
    neither is ever one of them.
    """
    path = str(run.get('path') or '')
    if backend.run_pulls_listed:
        listed = run.get('pull_requests')
        pulls = [one.get('number') for one in listed if isinstance(one, dict)] if isinstance(listed, list) else []
        return path == backend.run_path.format(workflow=workflow) and (pull is None or pulls == [pull])
    if pull is None:
        return path.startswith(f'{workflow}@')
    return path == backend.run_path.format(workflow=workflow, pull=pull)


def forge_posted(client: Client, head: str, *, base: str) -> Callable[[CommitStatus], bool]:
    """The test of whether a status on *head* was posted by *client*'s forge's own review (module docstring).

    On Gitea the runs at *head* are read once, on the first null-creator status asked about; a repo that has not
    adopted the Actions review at *base* (:func:`adopts_actions_review`) is reviewed by the serve, the client's own
    login.
    """
    if client.backend is GITHUB:
        return github_posted
    if not adopts_actions_review(client, base):
        serve = client.whoami()
        return lambda status: bool(serve) and status.creator == serve
    owner, repo = client.forge.owner, client.forge.repo
    read: list[tuple[frozenset[str], bool]] = []

    def at_head() -> tuple[frozenset[str], bool]:
        """The honest review runs' paths at the head, and whether the latest of them to conclude concluded success."""
        if not read:
            runs = review_runs(client, head)
            concluded = next((run for run in runs if run.get('conclusion')), None)
            paths = frozenset(path for run in runs if (path := run_path(run.get('html_url') or '', owner, repo)))
            read.append((paths, concluded is not None and concluded.get('conclusion') == 'success'))
        return read[0]

    def posted(status: CommitStatus) -> bool:
        if status.creator != '':
            return False
        named = run_path(status.url, owner, repo)
        if not named:
            return False
        paths, succeeded = at_head()
        return named in paths and succeeded

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


#: The states :func:`post_review` posted inside :func:`posted_verdicts`, in order; ``None`` outside it.
_POSTED: ContextVar[list[str] | None] = ContextVar('posted_verdicts', default=None)


@contextlib.contextmanager
def posted_verdicts() -> Iterator[list[str]]:
    """The states every :func:`post_review` inside the block posts, in order -- what THIS process said.

    The review job's exit is read from it (:func:`dev_lab.dev.forgereview_job.job_exit`): the door that posts is the
    one that knows, never a re-read of the head, where a PR-head workflow's null-creator status may stand.
    """
    said: list[str] = []
    token = _POSTED.set(said)
    try:
        yield said
    finally:
        _POSTED.reset(token)


def post_review(client: Client, head: str, *, state: str, description: str, target_url: str = '') -> None:
    """Post *head*'s :data:`REVIEW_CONTEXT` -- the ONE door every review status is posted through.

    Inside Gitea's review job the status names the job's own run (:func:`job_run_url`), which is what
    :func:`forge_posted` verifies; anywhere else it links *target_url* (the round's comment, a carried verdict).
    """
    status_post(client, head, context=REVIEW_CONTEXT, state=state, description=description,
                target_url=job_run_url(client) or target_url)  # fmt: skip
    if (said := _POSTED.get()) is not None:
        said.append(state)


def status_gate(posted: Callable[[CommitStatus], bool]) -> Reviewed:
    """The serve-mode gate: :func:`review_missing` over a head's statuses, *posted* telling the forge's own post."""
    return lambda statuses: review_missing(statuses, posted)


def _hold_missing(statuses: Sequence[CommitStatus]) -> str | None:
    hold = next((one for one in statuses if one.context == HOLD_CONTEXT), None)
    if hold is not None and hold.state != 'success':
        return f'{HOLD_CONTEXT} is {hold.state}: {hold.description}'
    return None


def head_reviews(client: Client, head: str) -> list[dict[str, Any]]:
    """Every PR review on every pull request whose head the forge says *head* is, as the forge lists them.

    Gitea answers ONE pull (``commits/{sha}/pull``, 404 when none), GitHub a list (``commits/{sha}/pulls``).
    """
    if client.backend is GITHUB:
        listed: Any = client.call('GET', f'{client.repo}/commits/{head}/pulls')
    else:
        try:
            listed = [client.call('GET', f'{client.repo}/commits/{head}/pull')]
        except ForgeCallFailed as failed:
            if failed.final != _NOT_FOUND:
                raise
            listed = []
    numbers = [int(pull['number']) for pull in listed or [] if isinstance(pull, dict) and pull.get('number')]
    return [row for number in numbers for row in pages(client, f'{client.repo}/pulls/{number}/reviews', {})]


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


def judge_missing(
    statuses: Sequence[CommitStatus], reviews: Sequence[Mapping[str, Any]], *, head: str, judge: str
) -> str | None:
    """The judge-mode gate: why *head* is not reviewed by the DECLARED *judge* login, or ``None`` when it is.

    Reviewed when the latest standing verdict review (:func:`standing_verdicts`) *judge* left AT *head* is
    :data:`APPROVED` and no hold is pending. Another login's approval, one at an older head, a dismissed or stale
    one, or a later ``REQUEST_CHANGES`` waits.
    """
    verdicts = standing_verdicts(reviews, login=judge, head=head)
    latest = max(verdicts, key=lambda row: int(row.get('id') or 0), default=None)
    if latest is None:
        return f'no verdict review by the judge {judge!r} at {head[:12]}: the judge reviews a prepared bundle'
    if latest.get('state') != APPROVED:
        return f'the judge {judge!r} requested changes at {head[:12]}'
    return _hold_missing(statuses)


def review_missing(statuses: Sequence[CommitStatus], posted: Callable[[CommitStatus], bool]) -> str | None:
    """Why the head *statuses* (newest first) describe is not reviewed, or ``None`` when it is.

    A ``success`` counts only when *posted* (:func:`forge_posted`) says the forge's review job posted it.
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
