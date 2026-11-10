"""PR-REVIEW-IS-ONE-SHOT-ADVICE: ONE independent review per PR, its findings advice, the declared command run once.

User rulings 2026-11-06: the review is "a small-scale independent acceptance check with suggestions", and "one
session maintains one task, one PR". ONE review on both forges (user ruling 2026-10-29); only who TRIGGERS it
differs. On Gitea the ``forge serve`` tick runs :func:`step` over every open PR; on GitHub a workflow job runs
``forge review run --pr <N>`` (:func:`dev_lab.dev.forgereview_job.review_run`) for the one PR its event names. Both
run :func:`review_pull`.

REVIEW IS THE LAST GATE (user ruling 2026-11-05; integrator ruling M8 2026-11-06). The merge decision asks
(:func:`dev_lab.dev.reviewturn.review_turn`): a head is reviewed only once the decision called it DUE -- tests
green, no conflict, every other condition standing. A head with no review status, or the decision's WAITS, is
not reviewed and nothing is posted or spent, whoever started the run; a push asks for nothing.

ONCE PER PR. A PR is reviewed at its first merge-ready head; every later head -- a fix push, a sync with integration --
gets the standing review's verdict posted on it, and nothing runs. It is reviewed again only when:

* its own change has GROWN to :data:`REVIEW_AGAIN_GROWTH` times the reviewable code bytes the review measured
  (:func:`~dev_lab.dev.forgereview_scope.code_bytes`, from the merge base, so a sync never grows it), or
* a session ASKS (``forge review again <pr>``, :mod:`dev_lab.dev.forgereview_stands`): what clears a security
  finding once it is fixed.

WHAT IT POSTS: the review's one comment and ``tests/review`` (:mod:`dev_lab.dev.forgereview_advice`): ``success``
once the review ran, naming the advice by severity; ``failure`` ONLY on a security finding -- or, in a continuation
PR, on a finding carried from its branch's landed PRs and not yet resolved or deferred (:mod:`branchreview`).
A review that DID NOT RUN
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
import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from dev_lab.dev import forgereview_scope
from dev_lab.dev.branchreview import Carried, carried_for, context
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgepulls import ListingIncomplete, pr_list
from dev_lab.dev.forgereview_advice import post_review_comment, record_of, recorded_usd, trusted_bodies
from dev_lab.dev.forgereview_batch import BATCH_PENDING, batch_args, held_state, trusted_logins, wait_of, within
from dev_lab.dev.forgereview_claim import (
    DESCRIPTION,
    RETRYING,
    UNREVIEWED_STATUS,
    WAITS,
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
from dev_lab.dev.forgereview_stands import asked_again, restands, stands
from dev_lab.dev.labsession import sessions
from dev_lab.dev.reviewbudget import (
    Gate,
    Month,
    NoReviewAllotment,
    ShareRefused,
    Spend,
    charged_to,
    gate,
    open_share,
    raised_of,
    read_spend,
    share_of,
    tag_of,
)
from dev_lab.dev.reviewcap import unreviewed_line
from dev_lab.dev.reviewcode import ONLY_GENERATED
from dev_lab.dev.reviewgate import forge_posted, post_review
from dev_lab.dev.reviewledger import LEDGER_UNREAD, ForgeLedger, Hosted, Ledger, hosted_here, spend_of
from dev_lab.dev.reviewruntime import review_runtimes

if TYPE_CHECKING:
    from dev_lab.dev.forgereview_advice import Record
    from dev_lab.dev.forgestatus import CommitStatus
    from dev_lab.dev.forgework import Client, PullRequest
    from dev_lab.dev.lanepolicy import Policy

__all__ = [
    'NEEDS_MAINTAINER',
    'REVIEW_AGAIN_GROWTH',
    'HostCannot',
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


def _not_called(latest: CommitStatus | None) -> bool:
    """Whether the merge decision has not called this head's review: no status yet, or its WAITS."""
    return latest is None or (latest.state == 'pending' and latest.description.startswith(WAITS))


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


def _grown(record: Record, size: int) -> bool:
    """Whether the PR's own code (*size* bytes) grew :data:`REVIEW_AGAIN_GROWTH` times what *record* measured."""
    return bool(record.size) and size >= REVIEW_AGAIN_GROWTH * record.size


def _budget(
    root: Path, client: Client, review: Review, pull: PullRequest, runner: Runner
) -> tuple[Review | None, str, Gate, Hosted | None]:
    """*review* as the PR's dollar budget lets it run (:mod:`dev_lab.dev.reviewbudget`), else ``None``; why; its cap.

    A host with no machine file whose base declares the month reviews under it, charged to the forge's ledger
    (:mod:`dev_lab.dev.reviewledger`): the fourth value. Otherwise an ai-lab with no review allotment skips, named.
    """
    bodies = trusted_bodies(client, pull.number, review.reviewers)
    hosted = None
    try:
        spend = runner.spend(runner.runtimes, root)
    except NoReviewAllotment as none:  # the reached-cap case: skipped, named (ruling 2026-11-10)
        if review.month is None or not runner.hosted():
            return None, f'skipped: {none}', Gate('skip', f'skipped: {none}'), None
        try:
            hosted = _hosted(root, client, review.month, pull, runner)
        except (ForgeCallFailed, OSError, ValueError) as unread:
            why = f'skipped: {LEDGER_UNREAD}: {unread}'
            return None, why, Gate('skip', why), None
        spend = hosted.spend
    spent = max(recorded_usd(bodies), 0.0 if spend is None else spend.of(tag_of(pull.url, pull.number)))
    allowed = gate(number=pull.number, spent_usd=spent, spend=spend, raised=raised_of(bodies))
    if allowed.state != 'run':
        return None, allowed.why, allowed, None
    return dataclasses.replace(review, model=allowed.model or review.model), allowed.why, allowed, hosted


def _hosted(root: Path, client: Client, month: Month, pull: PullRequest, runner: Runner) -> Hosted:
    """The declared *month* on this host, its spend read from the forge's ledger (:mod:`dev_lab.dev.reviewledger`)."""
    ledger, now = runner.ledger(client), runner.clock()
    spend = spend_of(month, ledger.entries(), now=now, repo_tag=tag_of(pull.url, pull.number).rpartition('#')[0])

    def read_spent() -> float | None:
        try:
            got = runner.spend(runner.runtimes, root)
        except (NoReviewAllotment, OSError, ValueError):
            return None
        return None if got is None else got.spent_usd

    return Hosted(month, ledger, spend, read_spent, now)


def review_pull(root: Path, client: Client, review: Review, pull: PullRequest, runner: Runner) -> str | None:
    """Review *pull* once (the module docstring), or post the standing review on its head; ``None`` when nothing.

    A head that holds its own review status (posted, or a live claim) is left alone; a request to review it again
    (:func:`~dev_lab.dev.forgereview_stands.ask_again`) overrides a settled status.
    """
    head, target = pull.head_sha, f'origin/{pull.base}'
    record = record_of(trusted_bodies(client, pull.number, review.reviewers))
    asked = (record is None or record.head != head) and asked_again(client, pull.number, head)
    latest = latest_review(client, head)
    if latest is not None and latest.state == 'success' and runner.verifies and not forge_posted(client)(latest):
        latest = None  # a success the gate does not count is no review (dev-lab #38)
    settled = latest is not None and (latest.state != 'pending' or latest.description.startswith(UNREVIEWED_STATUS))
    carry = carried_for(client, pull, review.reviewers)
    moved = restands(client, pull, record, carry, latest)  # a disposition moved a held verdict: no model call
    if moved is not None or (not asked and _not_called(latest)):  # the last gate: no call on a red or conflicting head
        return moved
    if not claimable(latest, runner.clock(), review.stale, run_ended(client)) and not (asked and settled):
        return None
    since = carry.since if carry else ''
    if (
        record is not None
        and not asked
        and (record.head == head or not _grown(record, code_bytes(root, target, head, review.budget, since)))
    ):
        return stands(client, pull, record, carry)
    if (wait := _young(root, head, runner)) is not None:
        return f'#{pull.number} {head[:12]}: {wait}'
    allowed, note, held, hosted = _budget(root, client, review, pull, runner)
    if allowed is None:
        return unreviewed(client, pull, f'review {note}')
    return _run_hosted(root, client, allowed, pull, runner, held=held, carry=carry, hosted=hosted, note=note)


def _run_hosted(
    root: Path, client: Client, review: Review, pull: PullRequest, runner: Runner, *, held: Gate,
    carry: Carried | None, hosted: Hosted | None, note: str,
) -> str:  # fmt: skip
    """:func:`_run`; a *hosted* one inside its forge hold (:meth:`~dev_lab.dev.reviewledger.Hosted.run`)."""
    if hosted is None:
        return f'{_run(root, client, review, pull, runner, held=held, carry=carry)} ({note})'
    with hosted.run(number=pull.number, usd=held.usd, env=os.environ) as refused:
        if refused is not None:
            return unreviewed(client, pull, f'review skipped: {refused}')
        return f'{_run(root, client, review, pull, runner, held=held, carry=carry)} ({note}; month on the forge)'


def _run(
    root: Path, client: Client, review: Review, pull: PullRequest, runner: Runner, *, held: Gate,
    carry: Carried | None = None,
) -> str:  # fmt: skip
    """Review *pull*'s head now: nothing to read is ``success``, no review key merges unreviewed; the line said.

    The review runs charged in *pull*'s share of ai-lab's ``review`` allotment (on a reserve raise, of its
    provider's reserve), opened at *held*'s cap
    (:func:`~dev_lab.dev.reviewbudget.share_of`), so ai-lab refuses a call past the PR's cap or the review's month,
    naming the level. A share ai-lab will not open runs nothing; ``inf`` (no spend report) opens none. A
    continuation (*carry*) is read from its last landed head and handed what it carries.
    """
    head = pull.head_sha
    scope = plan(root, f'origin/{pull.base}', head, review.budget, sliceable=PATHS_FIELD in review.command,
                 since=carry.since if carry else '')  # fmt: skip
    if not scope.slices:
        post_review(client, head, state='success', description=ONLY_GENERATED[:DESCRIPTION])
        return f'#{pull.number} {head[:12]}: {ONLY_GENERATED}'
    if not runner.secret:
        return unreviewed(client, pull, NEEDS_MAINTAINER)
    tag = tag_of(pull.url, pull.number)
    try:
        if held.usd == float('inf'):
            share = None
        elif held.reserve is not None:
            share = runner.allot(runner.runtimes, root, share_of(tag, reserve=True), held.usd, held.reserve)
        else:
            share = runner.allot(runner.runtimes, root, share_of(tag), held.usd)
    except ShareRefused as refused:
        return f'#{pull.number} {head[:12]}: not reviewed -- its review budget share did not open: {refused}'
    with charged_to(tag, share):
        return _command_review(root, client, review, pull, scope=scope, runner=runner, carry=carry)


def _command_review(
    root: Path, client: Client, review: Review, pull: PullRequest, *, scope: Scope, runner: Runner,
    carry: Carried | None = None,
) -> str:  # fmt: skip
    """Claim *pull*'s head, run the command over *scope*'s slices and post the review; the line said.

    Every command batches through the head's state on the PR and shares ONE wait (:mod:`forgereview_batch`).
    """
    with held_state(client, pull.number, pull.head_sha, trusted_logins(client)) as state:
        run = within(runner.run, runner.clock() + wait_of(review), runner.clock)
        return _review(root, client, review, pull, scope=scope, runner=runner, run=run,
                       batching=batch_args(review, state), carry=carry)  # fmt: skip


def _review(
    root: Path, client: Client, review: Review, pull: PullRequest, *, scope: Scope, runner: Runner,
    run: Callable[[Sequence[str], Path], str], batching: Sequence[str], carry: Carried | None = None,
) -> str:  # fmt: skip
    """:func:`_command_review` once its batch state is held: *run* is the timed runner, *batching* the flags.

    A continuation's reviewer reads its *carry* as context (after the PR body) and its settled findings as disposed.
    """
    head, target = pull.head_sha, f'origin/{pull.base}'
    carried = context(carry) if carry else ''
    settled, since = (carry.settled, carry.since) if carry else ((), '')
    disposed = [(one.id, f'{how.state}: {how.reason}' if how.reason else how.state) for one, how in settled]
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
        body = '\n\n'.join(one for one in (pull.body, carried) if one)
        found = parse_findings(gather(scope.range, argvs, synth, run, root, pr_body=body, disposed=disposed))
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
                               outside=scope.outside, unread=scope.unread, usd=usd, carried=carried,
                               still_open=carry.open if carry else (),
                               size=code_bytes(root, target, head, review.budget, since))  # fmt: skip


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
    allot: Callable[..., str | None] = open_share,  # (runtimes, root, share, usd[, provider]),
    ledger: Callable[[Client], Ledger] = ForgeLedger,
    hosted: Callable[[], bool] = hosted_here,
) -> tuple[str, ...]:
    """:func:`review_pull` on every open, non-draft PR into *base* -- the serve tick's trigger; the lines said.

    *quiet* is the debounce (D52): :func:`step` passes the declared ``quiet``; zero reviews every head now.
    A base declaring ``where = "judge"`` is reviewed by the judge host alone (:mod:`forgereview_bundle`): nothing.
    """
    if review.where == JUDGE:
        return ()
    runner = Runner(
        host=host,
        runtimes=runtimes,
        run=run,
        ready=ready,
        clock=clock,
        serving=True,
        spend=spend,
        quiet=quiet,
        allot=allot,
        ledger=ledger,
        hosted=hosted,
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
