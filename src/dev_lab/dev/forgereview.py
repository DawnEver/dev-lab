"""PR-REVIEW-IS-ONE-SHOT-ADVICE: ONE independent review per PR, its findings advice, the declared command run once.

User rulings 2026-11-06: the review is "a small-scale independent acceptance check with suggestions", and "one
session maintains one task, one PR". ONE review on both forges (user ruling 2026-10-29); only who TRIGGERS it
differs. On Gitea the ``forge serve`` tick runs :func:`step` over every open PR; on GitHub a workflow job runs
``forge review run --pr <N>`` (:func:`dev_lab.dev.forgereview_job.review_run`) for the one PR its event names. Both
run :func:`review_pull`.

ONCE PER PR. A PR is reviewed at its first ready head; every later head -- a fix push, a sync with integration --
gets the standing review's verdict posted on it, and nothing runs. It is reviewed again only when:

* its own change has GROWN to :data:`REVIEW_AGAIN_GROWTH` times the reviewable code bytes the review measured
  (:func:`~dev_lab.dev.forgereview_scope.code_bytes`, from the merge base, so a sync never grows it), or
* a session ASKS (:func:`ask_again`, ``forge review again <pr>``): what clears a security finding once it is fixed.

WHAT IT POSTS: the review's one comment and ``tests/review`` (:mod:`dev_lab.dev.forgereview_advice`): ``success``
once the review ran, naming the advice by severity; ``failure`` ONLY on a security finding. A review that DID NOT RUN
never holds the merge (:mod:`dev_lab.dev.reviewcap`): a failed attempt on the serve tick is retried once
(:data:`~dev_lab.dev.forgereview_claim.RETRYING`); a second failure, a failure in a review job, every reviewer
unsupported, exhausted or unauthorised, no review key (a fork PR's job), or a reached dollar cap
(:mod:`dev_lab.dev.reviewbudget`) records its cause on the PR and posts ``pending``
:data:`~dev_lab.dev.forgereview_claim.UNREVIEWED_STATUS` (:func:`unreviewed`): the PR merges ``Unreviewed:``.

THE FORGE ONLY ORCHESTRATES. The review itself -- profiles, prompts, providers, models, keys, merging -- is the
method's, run by the command the repo declares (``[tool.dev_lab.review] command``, :mod:`forgereview_declared`) over
:mod:`dev_lab.dev.forgereview_scope`'s diff slices; its stdout is the findings JSON
(:mod:`dev_lab.dev.forgereview_findings`). WHERE IT RUNS follows what it needs: a host whose ``[runtimes]`` cannot
fill or start the command says so once and reads no PR; among capable hosts, the claim
(:mod:`dev_lab.dev.forgereview_claim`) makes each head reviewed once. DEBOUNCE (D52): the serve reviews a head only
once it is ``quiet`` old. DRAFTS are never reviewed. A BATCH STILL RUNNING IS NO VERDICT
(:mod:`dev_lab.dev.forgereview_batch`): ``pending`` names it, and the next run of that head resumes it.
"""

from __future__ import annotations

import dataclasses
import subprocess
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from dev_lab.dev import forgereview_scope
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgepulls import ListingIncomplete, Marker, comment_list, comment_upsert, marker, pr_list
from dev_lab.dev.forgereview_advice import post_review_comment, record_of, recorded_usd, trusted_bodies, verdict
from dev_lab.dev.forgereview_batch import BATCH_PENDING, batch_args, held_state, trusted_logins, wait_of, within
from dev_lab.dev.forgereview_claim import (
    DESCRIPTION,
    RETRYING,
    UNREVIEWED_STATUS,
    claim_of,
    claimable,
    latest_review,
    retried,
    run_ended,
    unable,
)  # fmt: skip
from dev_lab.dev.forgereview_command import (
    ReviewPending,
    ReviewRefused,
    ReviewUnsupported,
    Runner,
    can_start,
    run_command,
)
from dev_lab.dev.forgereview_declared import JUDGE, PATHS_FIELD, Review, command_for, review_at
from dev_lab.dev.forgereview_findings import FindingsInvalid, UnknownSchemaVersion, parse_findings
from dev_lab.dev.forgereview_identity import ReviewerRefused, identity, ruling, self_review
from dev_lab.dev.forgereview_runtimes import retired_table
from dev_lab.dev.forgereview_scope import Scope, code_bytes, gather, plan
from dev_lab.dev.labsession import sessions
from dev_lab.dev.reviewbudget import Spend, charged_to, gate, raised_of, read_spend, tag_of
from dev_lab.dev.reviewcap import unreviewed_line
from dev_lab.dev.reviewcode import ONLY_GENERATED
from dev_lab.dev.reviewgate import forge_posted, post_review
from dev_lab.dev.reviewruntime import review_runtimes

if TYPE_CHECKING:
    from dev_lab.dev.forgereview_advice import Record
    from dev_lab.dev.forgework import Client, PullRequest
    from dev_lab.dev.lanepolicy import Policy

__all__ = [
    'NEEDS_MAINTAINER',
    'REVIEW_AGAIN_GROWTH',
    'HostCannot',
    'ask_again',
    'review_pull',
    'review_tick',
    'step',
    'unreviewed',
]  # fmt: skip

#: A PR is reviewed again when its own reviewable code has grown to this many times what its review measured: a PR
#: that doubled is mostly work no review has seen, while a fix push or a follow-up commit is not.
REVIEW_AGAIN_GROWTH: Final = 2

#: Why a review job with no review secret (a fork PR) does not review: the PR merges unreviewed, named.
NEEDS_MAINTAINER: Final = 'the review secret is absent (a fork PR)'


class HostCannot(OSError):
    """The host cannot fill or start the review command: a fact about the HOST, checked before any claim.

    The serve tick says it and leaves the head to a capable host; a workflow job -- the ONLY reviewer of its PR
    -- records the PR unreviewed (:func:`dev_lab.dev.forgereview_job.review_run`).
    """


def ask_again(client: Client, number: int, head: str, who: str) -> str:
    """Record *who*'s request to review PR *number* again at *head*; the forge's next review run honours it."""
    comment_upsert(client, number, kind=Marker.REVIEW_AGAIN, key=head,
                   text=f'Review asked again at `{head[:12]}` by {who}.')  # fmt: skip
    return f'#{number} {head[:12]}: review asked again; the next review run reviews this head'


def _asked(client: Client, number: int, head: str) -> bool:
    key = marker(Marker.REVIEW_AGAIN, head)
    return any(key in comment.body for comment in comment_list(client, number))


def unreviewed(client: Client, pull: PullRequest, why: str) -> str:
    """Record that *pull*'s review did not run and why, and post ``pending`` :data:`UNREVIEWED_STATUS`; the line.

    The merge reads the cause from the trusted comment (:func:`~dev_lab.dev.reviewcap.waiver_of`) and merges with
    an ``Unreviewed:`` line; it is said once per head.
    """
    head, said = pull.head_sha, f'{UNREVIEWED_STATUS} {why}'[:DESCRIPTION]
    latest = latest_review(client, head)
    if latest is None or (latest.state, latest.description) != ('pending', said):
        post_review(client, head, state='pending', description=said)
        client.issue_comment(pull.number, f'Not reviewed: {why}. This PR merges unreviewed once all else is green.'
                             f'\n\n{unreviewed_line(why)}')  # fmt: skip
    return f'#{pull.number} {head[:12]}: {said}'


def _failed(client: Client, pull: PullRequest, why: str, runner: Runner) -> str:
    """A review attempt that gave no review: retried once on the serve tick, else recorded :func:`unreviewed`."""
    if runner.serving and not retried(client, pull.head_sha):
        said = f'{RETRYING} {why}'[:DESCRIPTION]
        post_review(client, pull.head_sha, state='error', description=said)
        return f'#{pull.number} {pull.head_sha[:12]}: {said}'
    return unreviewed(client, pull, why)


def _young(root: Path, head: str, runner: Runner) -> str | None:
    """Why *head* is not reviewed YET (D52 debounce): committed inside the runner's ``quiet``; ``None`` when old."""
    if not runner.quiet:
        return None
    committed = datetime.fromisoformat(forgereview_scope.git(root, 'show', '-s', '--format=%cI', head)[1].strip())
    if (age := runner.clock() - committed) >= runner.quiet:
        return None
    return f'not reviewed yet: committed {int(age.total_seconds())} s ago, inside quiet {runner.quiet}'


def _stands(client: Client, pull: PullRequest, record: Record) -> str:
    """Post *record*'s verdict on *pull*'s head, naming the head it reviewed: nothing runs. The line said."""
    state, said = verdict(record, pull.number)
    why = f'review of {record.head[:12]} stands: {said}'[:DESCRIPTION]
    post_review(client, pull.head_sha, state=state, description=why)
    return f'#{pull.number} {pull.head_sha[:12]}: {why}'


def _grown(record: Record, size: int) -> bool:
    """Whether the PR's own code (*size* bytes) grew :data:`REVIEW_AGAIN_GROWTH` times what *record* measured."""
    return bool(record.size) and size >= REVIEW_AGAIN_GROWTH * record.size


def _budget(root: Path, client: Client, review: Review, pull: PullRequest, runner: Runner) -> tuple[Review | None, str]:
    """*review* as the PR's dollar budget lets it run (:mod:`dev_lab.dev.reviewbudget`), else ``None``; and why."""
    bodies = trusted_bodies(client, pull.number, review.reviewers)
    spend = runner.spend(runner.runtimes, root)
    spent = max(recorded_usd(bodies), 0.0 if spend is None else spend.of(tag_of(pull.url, pull.number)))
    allowed = gate(number=pull.number, spent_usd=spent, spend=spend, raised=raised_of(bodies))
    if allowed.state != 'run':
        return None, allowed.why
    return dataclasses.replace(review, model=allowed.model or review.model), allowed.why


def review_pull(root: Path, client: Client, review: Review, pull: PullRequest, runner: Runner) -> str | None:
    """Review *pull* once (the module docstring), or post the standing review on its head; ``None`` when nothing.

    A head that holds its own review status (posted, or a live claim) is left alone; a request to review it again
    (:func:`ask_again`) overrides a settled status.
    """
    head, target = pull.head_sha, f'origin/{pull.base}'
    record = record_of(trusted_bodies(client, pull.number, review.reviewers))
    asked = (record is None or record.head != head) and _asked(client, pull.number, head)
    latest = latest_review(client, head)
    if latest is not None and latest.state == 'success' and runner.verifies and not forge_posted(client)(latest):
        latest = None  # a success the gate does not count is no review (dev-lab #38)
    settled = latest is not None and latest.state != 'pending'
    if not claimable(latest, runner.clock(), review.stale, run_ended(client)) and not (asked and settled):
        return None
    if (
        record is not None
        and not asked
        and (record.head == head or not _grown(record, code_bytes(root, target, head, review.budget)))
    ):
        return _stands(client, pull, record)
    if (wait := _young(root, head, runner)) is not None:
        return f'#{pull.number} {head[:12]}: {wait}'
    allowed, note = _budget(root, client, review, pull, runner)
    if allowed is None:
        return unreviewed(client, pull, f'review {note}')
    return f'{_run(root, client, allowed, pull, runner)} ({note})'


def _run(root: Path, client: Client, review: Review, pull: PullRequest, runner: Runner) -> str:
    """Review *pull*'s head now: nothing to read is ``success``, no review key merges unreviewed; the line said."""
    head = pull.head_sha
    scope = plan(root, f'origin/{pull.base}', head, review.budget, sliceable=PATHS_FIELD in review.command)
    if not scope.slices:
        post_review(client, head, state='success', description=ONLY_GENERATED[:DESCRIPTION])
        return f'#{pull.number} {head[:12]}: {ONLY_GENERATED}'
    if not runner.secret:
        return unreviewed(client, pull, NEEDS_MAINTAINER)
    with charged_to(tag_of(pull.url, pull.number)):
        return _command_review(root, client, review, pull, scope=scope, runner=runner)


def _command_review(
    root: Path, client: Client, review: Review, pull: PullRequest, *, scope: Scope, runner: Runner
) -> str:
    """Claim *pull*'s head, run the command over *scope*'s slices and post the review; the line said.

    Every command batches through the head's state on the PR and shares ONE wait (:mod:`forgereview_batch`).
    """
    with held_state(client, pull.number, pull.head_sha, trusted_logins(client)) as state:
        run = within(runner.run, runner.clock() + wait_of(review), runner.clock)
        return _review(root, client, review, pull, scope=scope, runner=runner, run=run,
                       batching=batch_args(review, state))  # fmt: skip


def _review(
    root: Path, client: Client, review: Review, pull: PullRequest, *, scope: Scope, runner: Runner,
    run: Callable[[Sequence[str], Path], str], batching: Sequence[str],
) -> str:  # fmt: skip
    """:func:`_command_review` once its batch state is held: *run* is the timed runner, *batching* the flags."""
    head, target = pull.head_sha, f'origin/{pull.base}'
    try:
        argvs = [command_for(review, scope.range, runner.runtimes, paths=s.paths, lens=s.lens, batching=batching)
                 for s in scope.slices]  # fmt: skip
        cannot = runner.ready(argvs[0], root)
    except ReviewUnsupported as unsupported:
        cannot = str(unsupported)
    if cannot is not None:  # checked before the claim: the HOST cannot, so nothing is posted on the head
        raise HostCannot(cannot)
    forgereview_scope.prefetch(root, scope.range)  # the reviewer holds no forge token: a partial clone fetches first
    me = identity(client, runner.host, serving=runner.serving)  # checked before the claim too
    authors = sessions(root, target, head)
    ruling(me, f'reviewing #{pull.number}')
    self_review(me, authors, f'reviewing #{pull.number}')
    post_review(client, head, state='pending', description=claim_of(runner.host, runner.clock()))
    before = _tagged(root, pull, runner)
    try:
        synth = command_for(review, scope.range, runner.runtimes, synthesis=True, batching=batching)
        found = parse_findings(gather(scope.range, argvs, synth, run, root, pr_body=pull.body))
    except ReviewPending as waiting:
        why = f'{BATCH_PENDING} {waiting}'[:DESCRIPTION]
        post_review(client, head, state='pending', description=why)
        return f'#{pull.number} {head[:12]}: {why}'
    except ReviewUnsupported as unsupported:  # started, then the host could not: replaces the claim
        return unable(client, pull, runner.host, str(unsupported))
    except (UnknownSchemaVersion, ReviewRefused, OSError, FindingsInvalid, subprocess.SubprocessError) as failed:
        return _failed(client, pull, f'the review command failed ({type(failed).__name__}: {failed})', runner)
    if not any(one.status in {'ok', 'skipped'} for one in found.reviewers):
        kinds = ', '.join(f'{one.name} {one.status}' for one in found.reviewers) or 'none planned'
        return _failed(client, pull, f'no reviewer returned findings ({kinds})', runner)
    usd = max(0.0, _tagged(root, pull, runner) - before)
    return post_review_comment(root, client, pull, scope.range, found=found, reviewer=me, authors=authors,
                               outside=scope.outside, unread=scope.unread, usd=usd,
                               size=code_bytes(root, target, head, review.budget))  # fmt: skip


def _tagged(root: Path, pull: PullRequest, runner: Runner) -> float:
    """What this host's ai-lab has charged to *pull* so far; 0 without a spend report."""
    spend = runner.spend(runner.runtimes, root)
    return 0.0 if spend is None else spend.of(tag_of(pull.url, pull.number))


def review_tick(
    root: Path,
    client: Client,
    review: Review,
    *,
    base: str,
    run: Callable[[Sequence[str], Path], str] = run_command,
    ready: Callable[[Sequence[str], Path], str | None] = can_start,
    host: str,
    runtimes: Mapping[str, Mapping[str, Any]] = MappingProxyType({}),  # this host's: none by default
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    spend: Callable[[Mapping[str, Mapping[str, Any]], Path], Spend | None] = read_spend,
    quiet: timedelta = timedelta(0),
) -> tuple[str, ...]:
    """:func:`review_pull` on every open, non-draft PR into *base* -- the serve tick's trigger; the lines said.

    *quiet* is the debounce (D52): :func:`step` passes the declared ``quiet``; zero reviews every head now.
    A base declaring ``where = "judge"`` is reviewed by the judge host alone (:mod:`forgereview_bundle`): nothing.
    """
    if review.where == JUDGE:
        return ()
    runner = Runner(
        host=host, runtimes=runtimes, run=run, ready=ready, clock=clock, serving=True, spend=spend, quiet=quiet
    )

    def said(pull: PullRequest) -> str | None:
        try:
            return review_pull(root, client, review, pull, runner)
        except HostCannot as cannot:  # another serving host may run it: nothing is posted
            return f'#{pull.number} {pull.head_sha[:12]}: not reviewed on this host -- {cannot}'
        except ReviewerRefused as author:  # the head's own author session: another reviewer runs it
            return f'#{pull.number} {pull.head_sha[:12]}: not reviewed here -- {author}'

    pulls = (pull for pull in pr_list(client) if pull.base == base and not pull.draft and pull.head_sha)
    return tuple(line for pull in pulls if (line := said(pull)) is not None)


def step(
    root: Path,
    built: Client,
    *,
    policy: Policy,
    say: Callable[[str], None],
    host: str,
    run: Callable[[Sequence[str], Path], str] = run_command,
    ready: Callable[[Sequence[str], Path], str | None] = can_start,
) -> None:
    """The review on this serving host, when it can run the command; a failure is said, never raised.

    *host* is the serving host's card name (:func:`dev_lab.dev.forgehosts.card_host`): the name its claim posts.
    A host that cannot fill or start the command says so once and reads no PR.
    """
    try:
        review = review_at(root, policy.integration)
        here = review_runtimes()
        try:  # any range, any slice: can this host run the command at all
            cannot = ready(command_for(review, '', here), root)
        except ReviewUnsupported as unsupported:
            cannot = retired_table(review.command, here) or str(unsupported)
        if cannot is not None:
            say(f'[serve] review: not run on this host -- {cannot}')
            return
        lines = review_tick(
            root, built, review, base=policy.integration, run=run, ready=ready, host=host, runtimes=here,
            quiet=review.quiet_for,
        )  # fmt: skip
        for line in lines:
            say(f'[serve] review: {line}')
    except (ForgeCallFailed, ListingIncomplete, OSError, ValueError, subprocess.SubprocessError) as failed:
        say(f'[serve] the PR review did not run: {failed}')
