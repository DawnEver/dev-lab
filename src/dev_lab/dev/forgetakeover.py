"""REVIEW TAKEOVER: an ADVISORY review by the integrator session of a head the forge's review has not reached.

D11 (#11 round 3, F-4eee841cf16c): every identity a local session asserts is forgeable by a same-user agent, so a
session's review is never the gate. The gate is :func:`dev_lab.dev.reviewgate.review_missing`, which counts only a
``tests/review`` success the FORGE recorded as written by its own identity. The remedy for "the forge could not run
the review" is :data:`~dev_lab.dev.reviewgate.RERUN` -- the forge's review run again; its round releases any hold.

* :func:`held` -- the open PR heads into integration whose latest :data:`HOLD_CONTEXT` is ``pending``; the forge
  prompts the integrator with each (:func:`alarms`, one ``integration`` issue per head, and
  ``forge notices --integrator``), naming the remedy.
* ``python -m dev_lab.dev.forge review takeover <sha>`` (:func:`takeover`) runs the SAME method and scope and posts
  the findings comment marked as an emergency, ADVISORY review: no status, no release, no merge.
  ``review plan <sha>`` prints the slices only.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from lab_commons.log import emit

from dev_lab.dev.forgealarm import INTEGRATION, Alarm
from dev_lab.dev.forgeclaim import this_machine
from dev_lab.dev.forgeintegration import _fetch_pull
from dev_lab.dev.forgepulls import comment_list, pages, pr_list
from dev_lab.dev.forgereview import (
    PATHS_FIELD,
    HostCannot,
    Review,
    command_for,
    hold,
    judge_for,
    load_review,
    review_pull,
)  # fmt: skip
from dev_lab.dev.forgereview_command import Runner, can_start, run_command
from dev_lab.dev.forgereview_dispose import adjudicate_thread, dispose, raise_cap
from dev_lab.dev.forgereview_dispose import blocked as review_blocked
from dev_lab.dev.forgereview_dispose import line as blocked_line
from dev_lab.dev.forgereview_findings import parse_findings
from dev_lab.dev.forgereview_judge import AdjudicationRefused, identity, pending, upheld
from dev_lab.dev.forgereview_rounds import post_round, trailed, trusted_bodies
from dev_lab.dev.forgereview_runtimes import host_runtimes
from dev_lab.dev.forgereview_scope import Scope, gather, git, landed_base, plan, reviewed_heads
from dev_lab.dev.forgestatus import status_list
from dev_lab.dev.forgework import ForgeCallFailed, PullRequest, client_for
from dev_lab.dev.labsession import sessions
from dev_lab.dev.lanepolicy import load_policy
from dev_lab.dev.platformparts import HOLD_CONTEXT
from dev_lab.dev.reviewbudget import Raised
from dev_lab.dev.reviewgate import RERUN, forge_posted, posted_verdicts, review_missing
from dev_lab.dev.reviewgitauth import take

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = [
    'LEDGER_TITLE', 'TakeoverRefused', 'alarms', 'held', 'job_exit', 'ledger_of', 'main', 'pull_for',
    'review_run', 'runtimes_with', 'scope_of', 'takeover',
]  # fmt: skip


class TakeoverRefused(ValueError):
    """The door will not review or release this head, and says why."""


def held(client: Client, base: str) -> tuple[PullRequest, ...]:
    """The open, non-draft PRs into *base* whose head's latest :data:`HOLD_CONTEXT` is ``pending``."""
    out = []
    for pull in pr_list(client):
        if pull.base != base or pull.draft or not pull.head_sha:
            continue
        latest = next((one for one in status_list(client, pull.head_sha) if one.context == HOLD_CONTEXT), None)
        if latest is not None and latest.state == 'pending':
            out.append(pull)
    return tuple(out)


def line(pull: PullRequest) -> str:
    """The prompt line for a held *pull*: what it is and the exact door."""
    return f'#{pull.number} {pull.head_sha[:12]}: review held -- {RERUN}'


def alarms(client: Client, base: str, repo: str) -> list[Alarm]:
    """One ``integration`` prompt per held head, keyed by its sha, naming the door."""
    return [
        Alarm(
            INTEGRATION,
            repo,
            f'review held {pull.head_sha[:12]} (#{pull.number})',
            f"{line(pull)}. Only the forge's own review releases tests/review-hold and counts; a session's "
            '`forge review takeover` is advisory. A human is asked only for a decision the review surfaces.',
        )
        for pull in held(client, base)
    ]


def pull_for(client: Client, sha: str) -> PullRequest | None:
    """The PR whose head starts with *sha*: an open one first, else the highest-numbered; ``None``: a plain commit.

    Open PRs are listed first; the whole history only when no open PR carries it.
    """
    for state in ('open', 'all'):
        found = [pull for pull in pr_list(client, state=state) if pull.head_sha and pull.head_sha.startswith(sha)]
        if found:
            return max(found, key=lambda pull: pull.number)
    return None


#: The title of the issue that holds a PR-less head's review ledger; ``{sha}`` is the full head.
LEDGER_TITLE: Final = 'review of commit {sha}'


def ledger_of(client: Client, head: str, base: str) -> PullRequest:
    """Where a PR-less *head*'s review ledger lives: its one issue (made on first use), as the thread a PR would be.

    A Break-Glass commit has no PR, so its findings comment and every ``dispose <number> <id>`` go to this issue:
    the round, the dispositions and the verdict are the SAME code a PR's are, keyed by the issue number.

    Only an issue the FORGE opened is the ledger (F-7fbe6eafaadf, security): its own login, or its workflow job's
    Actions login -- never a squatter's issue of the same title, and never a PR (GitHub's issues API lists PRs too).
    """
    title = LEDGER_TITLE.format(sha=head)
    mine = {client.whoami(), client.backend.actions_login}
    found = [
        one
        for one in pages(client, f'{client.repo}/issues', {'state': 'all'})
        if one.get('title') == title and not one.get('pull_request') and (one.get('user') or {}).get('login') in mine
    ]
    number, url = (found[0]['number'], found[0].get('html_url', '')) if found else _opened(client, title, head)
    return PullRequest(number, title, 'open', '', url, '', '', base, head_sha=head)


def _opened(client: Client, title: str, head: str) -> tuple[int, str]:
    issue = client.issue_create(title, f'The review of {head}, a commit with no pull request: its ledger lives here.')
    return issue.number, issue.url


def _commit(root: Path, sha: str) -> str:
    """*sha* resolved in the checkout at *root*; refused, naming the checkout, when it does not hold it."""
    try:
        return git(root, 'rev-parse', '--verify', '--end-of-options', f'{sha}^{{commit}}')[1].strip()
    except OSError as missing:
        msg = f'{sha} is not a commit of {root}: name the checkout that holds it with --repo'
        raise TakeoverRefused(msg) from missing


def scope_of(root: Path, client: Client, review: Review, head: str, *, base: str, pull: PullRequest | None) -> Scope:
    """What the takeover reads: the head's own change (``landed_base``), cut as the program review cuts it."""
    done = () if pull is None else reviewed_heads(comment.body for comment in comment_list(client, pull.number))
    sliceable = PATHS_FIELD in review.command
    return plan(root, landed_base(root, base, head), head, review.budget, done, sliceable=sliceable)


def takeover(
    root: Path, client: Client, review: Review, head: str, *, pull: PullRequest | None, base: str, host: str,
    run: Callable[[Sequence[str], Path], str] = run_command,
    runtimes: Mapping[str, Mapping[str, Any]] = MappingProxyType({}),
) -> tuple[str, ...]:  # fmt: skip
    """Review *head* where the forge's review is missing and post the findings as an ADVISORY emergency review.

    D11: it posts no status and releases nothing, so it never satisfies a merge or Break-Glass; the remedy that
    does is :data:`~dev_lab.dev.reviewgate.RERUN`. It refuses a head the forge already reviewed. A head with no PR
    keeps its ledger in its own issue (:func:`ledger_of`).
    """
    if review_missing(status_list(client, head), forge_posted(client, head, base=base)) is None:
        msg = f'{head[:12]} is already reviewed by the forge: nothing to take over'
        raise TakeoverRefused(msg)
    scope = scope_of(root, client, review, head, base=base, pull=pull)
    since = landed_base(root, base, head)
    thread = pull if pull is not None else ledger_of(client, head, base)
    argvs = [command_for(review, scope.range, runtimes, paths=s.paths, lens=s.lens) for s in scope.slices]
    synth = command_for(review, scope.range, runtimes, synthesis=True)
    gone = upheld(trusted_bodies(client, thread.number))  # upheld claims only: a trailer never reaches the engine
    found = parse_findings(gather(scope.range, argvs, synth, run, root, pr_body=thread.body, disposed=gone))
    if not any(one.status in {'ok', 'skipped'} for one in found.reviewers):
        kinds = ', '.join(f'{one.name} {one.status}' for one in found.reviewers) or 'none planned'
        msg = f'no reviewer returned findings ({kinds}); nothing is posted'
        raise TakeoverRefused(msg)
    said = post_round(
        root, client, thread, scope.range, found=found, max_rounds=review.max_rounds, by='integrator takeover',
        outside=scope.outside, authored=trailed(root, since, head), judged=judge_for(root, review, scope.range, run,
        runtimes), reviewer=identity(client, host), authors=sessions(root, since, head), emergency=True,
    )  # fmt: skip
    return (f'{said} ({len(scope.slices)} slice(s)); {RERUN} for a review that counts',)


#: What the hold says when the job's host cannot run the review command: the forge's review is re-run.
HOST_CANNOT: Final = 'the review job cannot run the review command'


def review_run(root: Path, client: Client, review: Review, number: int, *, base: str, runner: Runner) -> str:
    """:func:`review_pull` on PR *number* alone -- what a GitHub workflow job runs for its event's PR; the line.

    The job is the ONLY reviewer of its PR, so a host that cannot run the command is never silent: the head is held
    until the forge's review is re-run, and :class:`~dev_lab.dev.forgereview.HostCannot` is raised (the job fails).

    The same run then RULES on every claim still pending on the PR (:func:`adjudicate_thread`, as the job's own
    identity): GitHub runs an ``issue_comment`` workflow only from the default branch, so ``review-claims.yml``
    cannot rule on a PR whose fix it carries (#11) -- the PR's own ``pull_request`` job can.
    """
    pull = client.pr_view(number)
    if pull.base != base or pull.draft or not pull.head_sha:
        return f'#{number}: not reviewed -- only an open, non-draft PR into {base} is'
    try:
        said = review_pull(root, client, review, pull, runner) or f'#{number} {pull.head_sha[:12]}: already reviewed'
    except HostCannot as cannot:
        raise HostCannot(hold(client, pull, f'{HOST_CANNOT}: {cannot}')) from cannot
    if not pending(trusted_bodies(client, number)):
        return said
    ruled = adjudicate_thread(
        root, client, review, number, base=base, adjudicator=identity(client, runner.host, serving=runner.serving),
        run=runner.run, runtimes=runner.runtimes,
    )  # fmt: skip
    return '; '.join([said, *ruled])


def job_exit(client: Client, number: int, posted: Sequence[str], *, base: str) -> int:
    """The review job's exit: ``0`` only when the PR's head is reviewed by what this job did (dev-lab #30).

    Gitea's gate counts a review only when the base's ``pull_request_target`` run concluded success
    (:mod:`dev_lab.dev.reviewgate`), so a run must FAIL unless it posted success. *posted* is what this job's
    :func:`~dev_lab.dev.reviewgate.post_review` calls posted, in order
    (:func:`~dev_lab.dev.reviewgate.posted_verdicts`): its LAST state decides. A job that posted none (a head whose
    counted review stands, a PR it does not review) exits ``0`` only when the gate itself counts the head's review.
    """
    if posted:
        return 0 if posted[-1] == 'success' else 1
    head = client.pr_view(number).head_sha
    return 0 if head and review_missing(status_list(client, head), forge_posted(client, head, base=base)) is None else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge review', description=__doc__.splitlines()[0])
    parser.set_defaults(repo=None)
    verbs = parser.add_subparsers(dest='verb', required=True)
    for verb, what in (('takeover', 'review a head whose review is missing, post it, release any hold'),
                       ('plan', 'print the slices a takeover of a head reads')):  # fmt: skip
        door = verbs.add_parser(verb, help=what)
        door.add_argument('sha')
        door.add_argument('--repo', type=Path, help='the checkout that holds the sha (default: the working directory)')
    verbs.add_parser('held', help='list the held heads and the door for each')
    disposal = verbs.add_parser('dispose', help='claim a finding is not a defect; an independent reviewer rules')
    disposal.add_argument('pr', type=int, help="the PR, or a PR-less head's ledger issue")
    disposal.add_argument('finding')
    disposal.add_argument('--why', required=True, help='the claim: why it is not a defect (cite code or tests)')
    raising = verbs.add_parser('cap', help="raise one PR's review caps, the reason recorded on the PR (integrator)")
    raising.add_argument('pr', type=int)
    raising.add_argument('--usd', type=float, help='the dollar cap; the month remainder still bounds it')
    raising.add_argument('--rounds', type=int, help='the round cap')
    raising.add_argument('--why', required=True, help='the recorded reason for the raise')
    ruling = verbs.add_parser('adjudicate', help='rule on every pending claim of a thread (the forge runs this)')
    ruling.add_argument('number', type=int, help="the PR, or a PR-less head's ledger issue")
    ruling.add_argument('--dry-run', action='store_true', help='print the verdicts, post nothing (any session)')
    ruling.add_argument(
        '--runtime', action='append', default=[], metavar='NAME.KEY=VALUE',
        help="a [runtimes] value over this host's machine file (a runner has none), e.g. ai_lab.python=python",
    )  # fmt: skip
    verbs.add_parser('blocked', help='list the heads a blocking finding holds, with their ids and the door')
    running = verbs.add_parser('run', help="review one PR's head: what a GitHub workflow job runs for its event")
    running.add_argument('--pr', type=int, required=True)
    running.add_argument(
        '--secret-env', action='append', default=[], metavar='NAME',
        help='a variable the review command needs; empty or unset (a fork PR) holds the head for a maintainer',
    )  # fmt: skip
    running.add_argument(
        '--git-token-file', type=Path, metavar='PATH',
        help="a file holding the forge read token: read once, removed, sent only to the door's git",
    )  # fmt: skip
    running.add_argument(
        '--api-token-file', type=Path, metavar='PATH',
        help="a file holding the job's forge API token: read once, removed, held by the door's forge client",
    )  # fmt: skip
    running.add_argument(
        '--runtime', action='append', default=[], metavar='NAME.KEY=VALUE',
        help="a [runtimes] value over this host's machine file (a runner has none), e.g. ai_lab.python=python",
    )  # fmt: skip
    return parser


def runtimes_with(here: Mapping[str, Mapping[str, Any]], given: Sequence[str]) -> dict[str, dict[str, Any]]:
    """*here* (the machine file's ``[runtimes]``) with each ``NAME.KEY=VALUE`` of *given* over it."""
    out = {name: dict(row) for name, row in here.items()}
    for one in given:
        where, equals, value = one.partition('=')
        name, dot, key = where.partition('.')
        if not (equals and dot and name and key):
            msg = f'--runtime {one!r} is not NAME.KEY=VALUE'
            raise ValueError(msg)
        out.setdefault(name, {})[key] = value
    return out


def _listed(args: argparse.Namespace, root: Path, origin: Client, base: str, run: Callable[..., str]) -> list[str]:
    """``held`` and ``blocked`` list heads; ``dispose`` records a claim; ``adjudicate`` rules (the forge runs it)."""
    if args.verb == 'held':
        return [line(pull) for pull in held(origin, base)]
    if args.verb == 'blocked':
        return [blocked_line(pull, ids) for pull, ids in review_blocked(origin, base)]
    me = identity(origin, this_machine())
    if args.verb == 'dispose':
        return [f'[review] {dispose(origin, args.pr, args.finding, args.why, by=me)}']
    if args.verb == 'cap':
        return [f'[review] {raise_cap(origin, args.pr, Raised(args.usd, args.rounds, args.why), by=me)}']
    ruled = adjudicate_thread(
        root, origin, load_review(root), args.number, base=base, adjudicator=me, run=run, dry_run=args.dry_run,
        runtimes=runtimes_with(host_runtimes(), args.runtime),
    )  # fmt: skip
    return [f'[review] {one}' for one in ruled]


def main(
    argv: Sequence[str] | None = None, *, cwd: Path | None = None, client: Client | None = None,
    run: Callable[[Sequence[str], Path], str] = run_command,
    ready: Callable[[Sequence[str], Path], str | None] = can_start,
    fetch: Callable[[Path, int], object] | None = None,
) -> int:  # fmt: skip
    """``forge review takeover|plan <sha>``, ``held``, ``blocked``, ``dispose <pr> <id> --why``, ``cap <pr>``, ``run``.

    Exit 0 done, 1 held or blocked heads listed (``run``: the head not reviewed by it, :func:`job_exit`), 2 refused.
    """
    args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    root = args.repo or (Path.cwd() if cwd is None else cwd)
    pull_in = fetch or (lambda where, number: _fetch_pull(where, 'origin', number))
    try:
        # run: the tokens arrive by file, never env, before any subprocess (F-5a82981c5f22, F-d61706393b50);
        # the reviewer's model key (--secret-env) is its own, a separate concern, and stays in the env.
        api = take(args.git_token_file, args.api_token_file) if args.verb == 'run' else ''
        origin, base = client or client_for(root, token=api), load_policy(root).integration
        if args.verb == 'run':
            secret = all(os.environ.get(name) for name in args.secret_env)
            runner = Runner(
                this_machine(),
                runtimes_with(host_runtimes(), args.runtime),
                run=run,
                ready=ready,
                secret=secret,
                verifies=True,
            )
            with posted_verdicts() as said:
                emit(f'[review] {review_run(root, origin, load_review(root), args.pr, base=base, runner=runner)}')
            return job_exit(origin, args.pr, said, base=base)
        if args.verb in {'held', 'blocked', 'dispose', 'cap', 'adjudicate'}:
            said = _listed(args, root, origin, base, run)
            for one in said:
                emit(one)
            return 1 if said and args.verb in {'held', 'blocked'} else 0
        review, pull = load_review(root), pull_for(origin, args.sha)  # the forge first: the PR brings its head
        if pull is not None:
            pull_in(root, pull.number)
        head = _commit(root, pull.head_sha if pull is not None else args.sha)
        if args.verb == 'plan':
            scope = scope_of(root, origin, review, head, base=base, pull=pull)
            emit(
                f'{f"#{pull.number} " if pull else ""}{scope.range}: {len(scope.slices)} slice(s), '
                f'{scope.outside} non-code file(s) outside'
                f'{f" -- one structure-level review: {scope.structure}" if scope.structure else ""}'
            )
            emit(f'  code bytes: {sum(one.size for one in scope.slices)}')
            emit(f'  moved (path change only): {len(scope.moved)}')
            for one in scope.slices:
                emit(f'  {one.lens} {one.size} B: {" ".join(one.paths)}')
            return 0
        here = host_runtimes()
        for said in takeover(root, origin, review, head, pull=pull, base=base, host=this_machine(), run=run,
                             runtimes=here):  # fmt: skip
            emit(f'[review] {said}')
    except (
        TakeoverRefused,
        AdjudicationRefused,
        ForgeCallFailed,
        OSError,
        ValueError,
        subprocess.SubprocessError,
    ) as failed:
        emit(f'[review] refused: {failed}', err=True)
        return 2
    return 0
