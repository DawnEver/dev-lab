"""PR-REVIEW-BLOCKS-ON-HIGH-OR-SECURITY: the declared review command on every open PR into the PR base, per head.

Step 4 of the branch flow (user ruling 2026-10-19). ONE review on both forges (user ruling 2026-10-29); only who
TRIGGERS it differs. On Gitea the ``forge serve`` tick runs :func:`step` over every open PR; on GitHub a workflow
job runs ``forge review run --pr <N>`` (:func:`dev_lab.dev.forgereview_job.review_run`) for the one PR its event
names. Both run the same round (:func:`review_pull`). A job whose review secret is absent -- a fork PR, which
GitHub never hands a secret -- holds
the head (:data:`NEEDS_MAINTAINER`) until a maintainer re-runs the forge's review with the secret; nothing new is
stored.

THE FORGE ONLY ORCHESTRATES. The review itself -- profiles, prompts, providers, models, keys, merging -- is
the method's, run by the command the repo declares (``[tool.dev_lab.review] command``); this module runs
it on ``<merge base>..<head>`` and reads its stdout as the findings JSON
(:mod:`dev_lab.dev.forgereview_findings`). It holds no model client, no prompt and no key.

WHERE IT RUNS follows what it needs -- the declared command -- never the poller lease. Every ``forge serve`` tick
runs :func:`step` (via :func:`dev_lab.dev.forgeservesteps.review`), poller or not; a host whose ``[runtimes]``
cannot fill or start the command
(:func:`~dev_lab.dev.forgereview_declared.command_for`, :func:`can_start`) says so once and reads no PR. Among the
capable hosts the claim below makes each head reviewed once.

WHAT IT POSTS, per open, non-draft PR into ``[tool.dev_lab.integrator] integration`` whose head carries no
:data:`REVIEW_CONTEXT` status yet:

* the head's review ROUND as ONE comment keyed by the head sha (``Marker.REVIEW``): its tagged findings carried
  from the earlier rounds, re-checked, and recorded as a ledger (:mod:`dev_lab.dev.forgereview_rounds`; round 1
  opens with the change's context summary). Past ``max_rounds`` or the PR's dollar cap nothing runs: the cap is
  named and recorded (:mod:`dev_lab.dev.reviewbudget`), and the merge goes on WARNED (:mod:`dev_lab.dev.reviewcap`);
* a :data:`REVIEW_CONTEXT` status on the head: ``failure`` while an open ``HIGH`` or security finding is neither
  fixed nor disposed (``forge review dispose``, :mod:`dev_lab.dev.forgereview_dispose`), else ``success`` -- the
  auto-merge waits on every state but ``success`` (:func:`dev_lab.dev.reviewgate.review_missing`);
  ``pending`` saying
  :data:`TAKEOVER_PENDING` when every reviewer was ``exhausted`` or ``auth`` (nothing is commented; the integrator
  session reviews that head through the same method -- the task's API keys, then a ccc, then a ccds session), ``error``
  when the command failed or printed no known findings version. NONE of these is advisory: each waits the merge
  until the FORGE posts ``success`` (D11: :mod:`dev_lab.dev.reviewgate` reads the status's recorded creator).
  It is not a PART (:func:`dev_lab.dev.platformparts.parts_of` skips it): promotion and push admission never wait
  on it, the merge does;
* a ``pending`` :data:`~dev_lab.dev.platformparts.HOLD_CONTEXT` beside a ``pending`` :data:`REVIEW_CONTEXT` ONLY
  when the review could not run for this PR: its job has no review secret (:data:`NEEDS_MAINTAINER`) or its host
  cannot run the command (:class:`HostCannot`, on a workflow job). The forge's review is re-run, and its round
  releases the hold; a session's ``forge review takeover <sha>`` is advisory only (D11). A head is never held for
  its SIZE (D123, user ruling 2026-10-31, superseding 2026-10-26): an oversize head is one structure-level review.

WHAT IS READ is :mod:`dev_lab.dev.forgereview_scope`'s: the branch's own change since its last reviewed head,
minus generated files, in slices of at most ``max_diff_bytes`` under one lens each -- or, past the bounds, ONE
whole-range slice the reviewer explores from the directory level. Each slice runs the command
once; their outputs merge into one document, and a declared ``synthesis`` command then reads that document
(``{findings}``) over the whole range for what crosses slices.

THE COST IS BOUNDED: one review per head sha (the status is the record; a second tick on the same head runs
nothing and posts nothing), drafts skipped, generated files never read, ``max_total_bytes`` per head.

A ROUND IS SPENT ONLY ON NEW WORK (D52, user ruling 2026-11-01): every push was a round and every forge sync of
integration into a PR restarted its review at the merge base (consumer #5397, twice in a day), against a cap of
:data:`~dev_lab.dev.forgereview_rounds.FAMILY_MAX_ROUNDS`.

* A PURE SYNC carries: a head whose tree is git's clean automatic merge of its last reviewed head with integration
  posts that head's counted success (:func:`~dev_lab.dev.forgereview_claim.synced`), and runs nothing. Any other
  head since a reviewed one is read from that merge (:func:`~dev_lab.dev.forgereview_scope.own_base`): its own new
  work only. An increment with no code to read stands on its reviewed head only when that head's success is
  counted; otherwise the PR is read whole again -- an empty push never turns a ``failure`` into a ``success``.
* DEBOUNCE, on the serve tick: a head committed inside ``quiet``
  (:data:`~dev_lab.dev.forgereview_declared.DEFAULT_QUIET`) is not reviewed yet --
  nothing is posted, no round is spent -- and the next tick past it reviews it, so a burst of pushes costs one
  round. The tick re-reads every PR anyway, so waiting holds no runner.
* DRAFTS are never reviewed (skipped here and by the review job); marking one ready is a trigger
  (``ready_for_review`` in the workflows' types; the serve's next tick). A push after ready does NOT turn the PR
  back into a draft (D53): a fix push gets its round, and the debounce coalesces a burst of them.

A BATCH STILL RUNNING IS NO VERDICT (user ruling 2026-11-04, :mod:`dev_lab.dev.forgereview_batch`): the model calls
go through the vendor's batch endpoint by default; a round whose batch has not returned within ``batch_wait`` posts
``pending`` :data:`~dev_lab.dev.forgereview_batch.BATCH_PENDING` naming it -- no findings, no round, no verdict --
and leaves the batch state on the PR, so the next run of that head (a tick, a re-run, a takeover) resumes it.

ANY FAILURE IS ``error`` WITH ITS REASON (P4). A HOST that cannot run the review -- a host value the command names
but this host's ``[runtimes]`` does not declare, or a command it cannot start (:func:`can_start`: a missing
executable or module) -- is checked BEFORE the claim and posts NOTHING: a fact about the host is not the head's
status. One that started and turned out unable (:class:`ReviewUnsupported`) replaces its own claim with
:data:`~dev_lab.dev.forgereview_claim.HOST_UNABLE` naming the host and why, and that head stays
claimable by a capable host, or by this one once fixed. A command that ran and refused or printed no known
findings is the head's own ``error``, and that head is not retried. Otherwise the host CLAIMS the head:
a ``pending`` status ``claimed by <host> at <time>, reviewing``. Every other host skips a head whose review status is
anything but a released (``released by``) or stale claim (:func:`~dev_lab.dev.forgereview_claim.claimable`), so
N serving hosts review a head once.

Undeclared, nothing is reviewed and the step says so. Exit :data:`REFUSED_EXIT` is the command's named refusal
(:class:`ReviewRefused`): its stderr reason is the ``error`` status.

WHAT A REPO DECLARES -- ``[tool.dev_lab.review]``, the family's command and its placeholders, read from the
integration branch a PR trusts -- is :mod:`dev_lab.dev.forgereview_declared`.
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
from dev_lab.dev.forgepulls import ListingIncomplete, pr_list
from dev_lab.dev.forgereview_batch import BATCH_PENDING, batch_args, held_state, trusted_logins, wait_of, within
from dev_lab.dev.forgereview_claim import (
    CAPPED,
    DESCRIPTION,
    claim_of,
    counted_success,
    passed,
    run_ended,
    synced,
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
from dev_lab.dev.forgereview_declared import JUDGE, PATHS_FIELD, Review, command_for, judge_for, review_at
from dev_lab.dev.forgereview_findings import Findings, FindingsInvalid, UnknownSchemaVersion, parse_findings
from dev_lab.dev.forgereview_judge import (
    AdjudicationRefused,
    identity,
    ruling,
    self_review,
    upheld,
)
from dev_lab.dev.forgereview_rounds import ledger_of, post_round, recorded_usd, trailed, trusted_bodies
from dev_lab.dev.forgereview_runtimes import retired_table
from dev_lab.dev.forgereview_scope import (
    Scope,
    gather,
    plan,
    reviewed_ancestor,
    reviewed_heads,
    synced_from,
)
from dev_lab.dev.forgestatus import DESCRIPTION_LIMIT, status_list, status_post
from dev_lab.dev.labsession import sessions
from dev_lab.dev.platformparts import HOLD_CONTEXT, REVIEW_CONTEXT
from dev_lab.dev.reviewbudget import (
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
from dev_lab.dev.reviewcap import capped_line
from dev_lab.dev.reviewcode import ONLY_GENERATED
from dev_lab.dev.reviewgate import forge_posted, post_review
from dev_lab.dev.reviewruntime import review_runtimes

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client, PullRequest
    from dev_lab.dev.lanepolicy import Policy

__all__ = [
    'NEEDS_MAINTAINER',
    'REVIEW_CONTEXT',
    'TAKEOVER_KINDS',
    'TAKEOVER_PENDING',
    'HostCannot',
    'hold',
    'review_pull',
    'review_tick',
    'step',
]  # fmt: skip

#: A reviewer status meaning its provider cannot serve this run at all: the review needs a takeover.
TAKEOVER_KINDS: Final = frozenset({'exhausted', 'auth'})

#: What :data:`REVIEW_CONTEXT` says when every reviewer is one of :data:`TAKEOVER_KINDS` (a ``pending`` status).
TAKEOVER_PENDING: Final = 'takeover pending'

#: What :data:`REVIEW_CONTEXT` and the hold say (``pending``) when the job running the review has no review secret:
#: a fork PR. The head is held until a maintainer re-runs the forge's review with the secret present.
NEEDS_MAINTAINER: Final = 'review needs a maintainer: the review secret is absent (a fork PR)'


class HostCannot(OSError):
    """The host cannot fill or start the review command: a fact about the HOST, checked before any claim.

    The serve tick says it and leaves the head to a capable host; a workflow job -- the ONLY reviewer of its PR
    -- holds the head for the takeover door and fails (:func:`dev_lab.dev.forgereview_job.review_run`).
    """


def _scope(
    root: Path, client: Client, review: Review, pull: PullRequest, target: str, *, done: Sequence[str]
) -> Scope:  # fmt: skip
    """What *pull*'s head review reads: its new work since the reviewed heads *done*, cut by *review*'s budget.

    An increment with no code to read stands on its reviewed head only when that head's success is counted; else
    the whole PR is read (D52, module docstring): an empty push after a ``failure`` is never "nothing to review".
    """
    sliceable = PATHS_FIELD in review.command
    scope = plan(root, target, pull.head_sha, review.budget, done, sliceable=sliceable)
    earlier = reviewed_ancestor(root, pull.head_sha, done)
    if scope.slices or not earlier or counted_success(client, earlier, base=pull.base) is not None:
        return scope
    return plan(root, target, pull.head_sha, review.budget, (), sliceable=sliceable)


def _young(root: Path, head: str, runner: Runner) -> str | None:
    """Why *head* is not reviewed YET (D52 debounce): committed inside the runner's ``quiet``; ``None`` when old."""
    if not runner.quiet:
        return None
    committed = datetime.fromisoformat(forgereview_scope.git(root, 'show', '-s', '--format=%cI', head)[1].strip())
    if (age := runner.clock() - committed) >= runner.quiet:
        return None
    return f'not reviewed yet: committed {int(age.total_seconds())} s ago, inside quiet {runner.quiet}'


def _settle(root: Path, client: Client, pull: PullRequest, review: Review, scope: Scope, *, found: Findings,
            authored: Mapping[str, str], runner: Runner, usd: float = 0.0,
            run: Callable[[Sequence[str], Path], str], batching: Sequence[str]) -> str:  # fmt: skip
    """Replace the claim on *pull*'s head with the final status *found* earns (and its round); the line said."""
    head = pull.head_sha
    if found.reviewers and all(one.status in TAKEOVER_KINDS for one in found.reviewers):
        kinds = ', '.join(f'{one.name} {one.status}' for one in found.reviewers)
        why = f'{TAKEOVER_PENDING}: no reviewer could run ({kinds}); waits for the forge review to be re-run'[
            :DESCRIPTION
        ]
        post_review(client, head, state='pending', description=why)
        return f'#{pull.number} {head[:12]}: {why}'
    if not any(one.status in {'ok', 'skipped'} for one in found.reviewers):
        kinds = ', '.join(f'{one.name} {one.status}' for one in found.reviewers) or 'none planned'
        why = f'not reviewed: no reviewer returned findings ({kinds}); waits for a takeover'[:DESCRIPTION]
        post_review(client, head, state='error', description=why)
        return f'#{pull.number} {head[:12]}: {why}'
    return post_round(root, client, pull, scope.range, found=found, max_rounds=review.max_rounds,
                      outside=scope.outside, authored=authored, usd=usd, reviewers=review.reviewers,
                      **_judging(root, client, review, pull, runner=runner, run=run, batching=batching))  # fmt: skip


def _judging(
    root: Path, client: Client, review: Review, pull: PullRequest, *, runner: Runner,
    run: Callable[[Sequence[str], Path], str], batching: Sequence[str],
) -> dict:  # fmt: skip
    """The judge, the reviewer and the head's author sessions every round is posted with.

    The JUDGE reads the PR's whole change at its head (merge base..head), never the round's increment: a finding
    about a file the increment did not touch is judged on that file as the head holds it (#7 round 3).
    """
    since = forgereview_scope.git(root, 'merge-base', f'origin/{pull.base}', pull.head_sha)[1].strip()
    return {
        'judged': judge_for(root, review, f'{since}..{pull.head_sha}', run, runner.runtimes, batching=batching),
        'reviewer': identity(client, runner.host, serving=runner.serving),
        'authors': sessions(root, f'origin/{pull.base}', pull.head_sha),
    }


def _without_command(client: Client, pull: PullRequest, scope: Scope) -> str | None:
    """The line said when *pull*'s head is settled with no command run (nothing but generated files to read)."""
    if scope.slices:
        return None
    post_review(client, pull.head_sha, state='success', description=ONLY_GENERATED[:DESCRIPTION])
    return f'#{pull.number} {pull.head_sha[:12]}: {ONLY_GENERATED}'


def capped(
    root: Path, client: Client, review: Review, pull: PullRequest, runner: Runner
) -> tuple[Review | None, str | None, float]:
    """*review* as *pull*'s next round may run it (:mod:`dev_lab.dev.reviewbudget`), a note or the WAIT line, its cap.

    A waiting head gets a ``pending`` :data:`~dev_lab.dev.forgereview_claim.CAPPED` status naming the cap and the
    remedy, and the review is ``None`` -- posted and said once (``None, None`` after), and read again every tick,
    so a raise or a new month releases it. The cap is also RECORDED on the PR
    (:func:`~dev_lab.dev.reviewcap.capped_line`): the merge reads its waiver from that trusted comment, never from
    the status.
    """
    head, bodies = pull.head_sha, trusted_bodies(client, pull.number, review.reviewers)
    prior = ledger_of(bodies)
    rounds_done = 0 if prior is None else prior.round - (prior.head == head)
    spend = runner.spend(runner.runtimes, root)
    tag = tag_of(pull.url, pull.number)
    spent = max(recorded_usd(bodies), 0.0 if spend is None else spend.of(tag))  # the rounds every host recorded
    allowed = gate(number=pull.number, spent_usd=spent, rounds_done=rounds_done,
                   max_rounds=review.max_rounds, spend=spend, raised=raised_of(bodies))  # fmt: skip
    if allowed.state == 'run':
        model = review.model if allowed.model is None else allowed.model
        unknown = '' if spend is not None else ' (no spend report on this host: the round cap alone holds)'
        return dataclasses.replace(review, max_rounds=allowed.max_rounds, model=model), unknown, allowed.usd
    said = f'{CAPPED} {allowed.why}'[:DESCRIPTION]
    latest = next((one for one in status_list(client, head) if one.context == REVIEW_CONTEXT), None)
    if latest is not None and (latest.state, latest.description) == ('pending', said[:DESCRIPTION_LIMIT]):
        return None, None, 0.0
    post_review(client, head, state='pending', description=said)
    client.issue_comment(
        pull.number, f'Review stopped at its cap; this PR merges unreviewed once all else is green: {allowed.why}'
        f'\n\n{capped_line(allowed.why)}',
    )  # fmt: skip
    return None, f'#{pull.number} {head[:12]}: {said}', 0.0


def hold(client: Client, pull: PullRequest, why: str) -> str:
    """Hold *pull*'s head for the takeover door: :data:`REVIEW_CONTEXT` and the hold both ``pending`` *why*."""
    post_review(client, pull.head_sha, state='pending', description=why[:DESCRIPTION])
    status_post(client, pull.head_sha, context=HOLD_CONTEXT, state='pending', description=why[:DESCRIPTION])
    return f'#{pull.number} {pull.head_sha[:12]}: {why}'


def review_pull(root: Path, client: Client, review: Review, pull: PullRequest, runner: Runner) -> str | None:
    """Review *pull*'s head once (the round in the module docstring); the line said, ``None`` when nothing was.

    The declared command reviews ``<merge base>..<head>`` and prints the findings JSON; one comment and one
    :data:`REVIEW_CONTEXT` status per head are posted from it. A host that cannot start it posts nothing;
    a command that fails or prints anything but a known findings version posts ``error`` naming why, and is not
    retried on that head.
    """
    head, target = pull.head_sha, f'origin/{pull.base}'
    counted = forge_posted(client, head, base=pull.base) if runner.verifies else None
    if (
        stands := passed(root, client, head, runner.clock(), review.stale, counted=counted, ended=run_ended(client))
    ) is not None:
        return f'#{pull.number} {head[:12]}: {stands}' if stands else None
    # the forge's own rounds only: a pasted marker naming an unreviewed sha would shrink the range or seed a carry
    done = reviewed_heads(trusted_bodies(client, pull.number, review.reviewers))
    if (source := synced_from(root, target, head, done)) and (why := synced(client, head, source, base=pull.base)):
        return f'#{pull.number} {head[:12]}: {why}'
    if (wait := _young(root, head, runner)) is not None:
        return f'#{pull.number} {head[:12]}: {wait}'
    allowed, note, usd = capped(root, client, review, pull, runner)
    if allowed is None:
        return note
    review = allowed
    scope = _scope(root, client, review, pull, target, done=done)
    said = _without_command(client, pull, scope)
    if said is None and not runner.secret:
        said = hold(client, pull, NEEDS_MAINTAINER)
    if said is not None:
        return said
    return _charged_round(root, client, review, pull, scope=scope, runner=runner, usd=usd) + (note or '')


def _charged_round(
    root: Path, client: Client, review: Review, pull: PullRequest, *, scope: Scope, runner: Runner, usd: float
) -> str:
    """:func:`_command_round` charged in *pull*'s share of the review allotment, opened at its cap *usd*.

    The PR's cap is a CHILD of ai-lab's ``review`` allotment (:func:`~dev_lab.dev.reviewbudget.share_of`), so
    ai-lab refuses a call past the PR's cap or the review's month, naming the level. A share ai-lab will not open
    runs nothing; ``inf`` (no spend report on this host) opens none and charges the tag alone.
    """
    tag = tag_of(pull.url, pull.number)
    try:
        share = None if usd == float('inf') else runner.allot(runner.runtimes, root, share_of(tag), usd)
    except ShareRefused as refused:
        return f'#{pull.number} {pull.head_sha[:12]}: not reviewed -- its review budget share did not open: {refused}'
    with charged_to(tag, share):
        return _command_round(root, client, review, pull, scope=scope, runner=runner)


def _command_round(
    root: Path, client: Client, review: Review, pull: PullRequest, *, scope: Scope, runner: Runner
) -> str:
    """Claim *pull*'s head, run the command over *scope*'s slices and settle the head; the line said.

    Every command of the round batches through the head's state on the PR and shares ONE wait
    (:mod:`dev_lab.dev.forgereview_batch`); a batch still running ends the round :func:`_batch_pending`.
    """
    with held_state(client, pull.number, pull.head_sha, trusted_logins(client)) as state:
        run = within(runner.run, runner.clock() + wait_of(review), runner.clock)
        return _round(root, client, review, pull, scope=scope, runner=runner, run=run,
                      batching=batch_args(review, state))  # fmt: skip


def _batch_pending(client: Client, pull: PullRequest, waiting: ReviewPending) -> str:
    """Replace the claim with ``pending`` :data:`BATCH_PENDING` naming the batch: no verdict; the line said."""
    why = f'{BATCH_PENDING} {waiting}'[:DESCRIPTION]
    post_review(client, pull.head_sha, state='pending', description=why)
    return f'#{pull.number} {pull.head_sha[:12]}: {why}'


def _round(
    root: Path, client: Client, review: Review, pull: PullRequest, *, scope: Scope, runner: Runner,
    run: Callable[[Sequence[str], Path], str], batching: Sequence[str],
) -> str:  # fmt: skip
    """:func:`_command_round` once its batch state is held: *run* is the timed runner, *batching* the flags."""
    head, clock = pull.head_sha, runner.clock
    try:
        argvs = [command_for(review, scope.range, runner.runtimes, paths=s.paths, lens=s.lens, batching=batching)
                 for s in scope.slices]  # fmt: skip
        cannot = runner.ready(argvs[0], root)
    except ReviewUnsupported as unsupported:
        cannot = str(unsupported)
    if cannot is not None:  # checked before the claim: the HOST cannot, so nothing is posted on the head
        raise HostCannot(cannot)
    # the reviewer and the judge read these ranges with no forge token: a partial clone holds their blobs first
    forgereview_scope.prefetch(root, scope.range, f'origin/{pull.base}...{head}')
    # checked before the claim too: a session that authored the head posts nothing on it
    me = identity(client, runner.host, serving=runner.serving)
    ruling(me, f'reviewing #{pull.number}')
    self_review(me, sessions(root, f'origin/{pull.base}', head), f'reviewing #{pull.number}')
    post_review(client, head, state='pending', description=claim_of(runner.host, clock()))
    before = _tagged(root, pull, runner)
    try:
        synth = command_for(review, scope.range, runner.runtimes, synthesis=True, batching=batching)
        gone = upheld(trusted_bodies(client, pull.number, review.reviewers))
        found = parse_findings(gather(scope.range, argvs, synth, run, root, pr_body=pull.body, disposed=gone))
    except ReviewPending as waiting:
        return _batch_pending(client, pull, waiting)
    except ReviewUnsupported as unsupported:  # started, then the host could not: replaces the claim
        return unable(client, pull, runner.host, str(unsupported))
    except (UnknownSchemaVersion, ReviewRefused) as named:
        why = f'not reviewed: {named}'[:DESCRIPTION]
        post_review(client, head, state='error', description=why)
        return f'#{pull.number} {head[:12]}: {why}'
    except (OSError, FindingsInvalid, subprocess.SubprocessError) as failed:
        why = f'the review command failed ({type(failed).__name__}); not retried here, waits for a takeover'
        post_review(client, head, state='error', description=why)
        return f'#{pull.number} {head[:12]}: {why}: {failed}'
    authored = trailed(root, f'origin/{pull.base}', head)
    usd = max(0.0, _tagged(root, pull, runner) - before)
    try:
        return _settle(root, client, pull, review, scope, found=found, authored=authored, runner=runner, usd=usd,
                       run=run, batching=batching)  # fmt: skip
    except ReviewPending as waiting:  # the judge's batch: the round is posted by the run that settles it
        return _batch_pending(client, pull, waiting)


def _tagged(root: Path, pull: PullRequest, runner: Runner) -> float:
    """What this host's ai-lab has charged to *pull* so far; 0 without a spend report.

    A round's dollars are the difference across it, recorded in its ledger
    (:func:`~dev_lab.dev.forgereview_rounds.recorded_usd`).
    """
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
    allot: Callable[[Mapping[str, Mapping[str, Any]], Path, str, float], str | None] = open_share,
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
    )

    def said(pull: PullRequest) -> str | None:
        try:
            return review_pull(root, client, review, pull, runner)
        except HostCannot as cannot:  # another serving host may run it: nothing is posted
            return f'#{pull.number} {pull.head_sha[:12]}: not reviewed on this host -- {cannot}'
        except AdjudicationRefused as author:  # the head's own author session: another reviewer runs it
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
