"""``forge review``: the session's doors onto the PR review, and the review job's own verb.

The review is a one-shot independent acceptance with advice (:mod:`dev_lab.dev.forgereview`). D11 (#11 round 3,
F-4eee841cf16c): every identity a local session asserts is forgeable by a same-user agent, so a session's review is
never the forge's -- only the forge posts ``tests/review``.

* ``review again <pr>`` (:func:`~dev_lab.dev.forgereview_stands.ask_again`) asks the forge to review the PR's head
  again: after fixing a security finding, or to have grown work read. The forge's next review run honours it.
* ``review takeover <sha>`` (:func:`takeover`) runs the SAME method and scope and posts the findings comment as a
  session's ADVISORY review: no status, no merge. ``review plan <sha>`` prints the slices only.
* ``review carry <pr> --resolve ID | --defer ID --reason ...`` (:func:`~dev_lab.dev.forgereview_stands.carry`)
  disposes of a finding a continuation PR carries from its branch's landed PRs, in the branch's review record.
* ``review cap <pr> --usd <n> [--reserve] --why`` records the integrator's raise of one PR's dollar cap.
* ``review run --pr N`` is the review job's (:mod:`dev_lab.dev.forgereview_job`).
"""

from __future__ import annotations

import argparse
import functools
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from lab_commons.log import emit

from dev_lab.dev.forgeclaim import this_machine
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgelanes import fetch_pull
from dev_lab.dev.forgepulls import Marker, comment_upsert, pages, pr_list
from dev_lab.dev.forgereview_advice import post_review_comment
from dev_lab.dev.forgereview_batch import BATCH_PENDING, batch_args, held_state, trusted_logins, wait_of, within
from dev_lab.dev.forgereview_command import ReviewPending, Runner, can_start, run_command
from dev_lab.dev.forgereview_declared import (
    PATHS_FIELD,
    Review,
    command_for,
    operator_integration,
    review_at,
    trusted_integration,
)
from dev_lab.dev.forgereview_findings import parse_findings
from dev_lab.dev.forgereview_identity import Identity, ReviewerRefused, identity
from dev_lab.dev.forgereview_job import job_exit, review_due, review_run
from dev_lab.dev.forgereview_scope import Scope, gather, git, landed_base, plan
from dev_lab.dev.forgereview_stands import ask_again, carry
from dev_lab.dev.forgestatus import status_list
from dev_lab.dev.forgework import PullRequest, client_for
from dev_lab.dev.labsession import sessions
from dev_lab.dev.reviewbudget import Raised, raise_line
from dev_lab.dev.reviewgate import RERUN, forge_posted, posted_verdicts, review_missing
from dev_lab.dev.reviewgitauth import take
from dev_lab.dev.reviewledger import LEDGER_TOKEN, forge_ledger
from dev_lab.dev.reviewruntime import review_runtimes
from dev_lab.dev.taskkeys import REVIEW_TASK, keys_loaded

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = ['LEDGER_TITLE', 'TakeoverRefused', 'ledger_of', 'main', 'pull_for', 'raise_cap', 'scope_of', 'takeover']


class TakeoverRefused(ValueError):
    """The door will not review this head, and says why."""


def pull_for(client: Client, sha: str) -> PullRequest | None:
    """The PR whose head starts with *sha*: an open one first, else the highest-numbered; ``None``: a plain commit.

    Open PRs are listed first; the whole history only when no open PR carries it.
    """
    for state in ('open', 'all'):
        found = [pull for pull in pr_list(client, state=state) if pull.head_sha and pull.head_sha.startswith(sha)]
        if found:
            return max(found, key=lambda pull: pull.number)
    return None


#: The title of the issue that holds a PR-less head's review comment; ``{sha}`` is the full head.
LEDGER_TITLE: Final = 'review of commit {sha}'


def ledger_of(client: Client, head: str, base: str) -> PullRequest:
    """Where a PR-less *head*'s review comment lives: its one issue (made on first use), as the thread a PR would be.

    A Break-Glass commit has no PR, so its findings comment goes to this issue, keyed by the issue number.

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
    issue = client.issue_create(title, f'The review of {head}, a commit with no pull request: its comment lives here.')
    return issue.number, issue.url


def _commit(root: Path, sha: str) -> str:
    """*sha* resolved in the checkout at *root*; refused, naming the checkout, when it does not hold it."""
    try:
        return git(root, 'rev-parse', '--verify', '--end-of-options', f'{sha}^{{commit}}')[1].strip()
    except OSError as missing:
        msg = f'{sha} is not a commit of {root}: name the checkout that holds it with --repo'
        raise TakeoverRefused(msg) from missing


def scope_of(root: Path, review: Review, head: str, *, base: str) -> Scope:
    """What the takeover reads: the head's own change (``landed_base``), cut as the forge's review cuts it."""
    return plan(root, landed_base(root, base, head), head, review.budget, sliceable=PATHS_FIELD in review.command)


def raise_cap(client: Client, number: int, raised: Raised, *, by: Identity) -> str:
    """Record the integrator's raise of PR *number*'s dollar cap, with its reason; the line said.

    The record names its raiser's login (*by*), and is read only from a comment the forge records as that login's
    (:func:`~dev_lab.dev.forgereview_advice.trusted_bodies`); the month's remainder still bounds the raised cap.
    """
    if raised.usd is None:
        msg = 'a raise names --usd'
        raise ValueError(msg)
    if not raised.why.strip():
        msg = 'a raise records its reason: --why "<reason>"'
        raise ValueError(msg)
    text = (
        f'Review cap of #{number} raised by {by.text()}: {raised.usd:.2f} USD'
        f'{" drawn from the reserve" if raised.reserve else ""} -- {raised.why}\n\n'
        f'{raise_line(replace(raised, by=by.login))}'
    )
    comment_upsert(client, number, kind=Marker.REVIEW_CAP, text=text)
    return f'#{number}: review cap raised ({raised.why})'


def takeover(
    root: Path, client: Client, review: Review, head: str, *, pull: PullRequest | None, base: str, host: str,
    run: Callable[[Sequence[str], Path], str] = run_command,
    runtimes: Mapping[str, Mapping[str, Any]] = MappingProxyType({}),
) -> tuple[str, ...]:  # fmt: skip
    """Review *head* where the forge's review is missing and post the findings as an ADVISORY session review.

    D11: it posts no status, so it never satisfies a merge or Break-Glass; the remedy that does is
    :data:`~dev_lab.dev.reviewgate.RERUN`. It refuses a head the forge already reviewed. A head with no PR keeps its
    comment in its own issue (:func:`ledger_of`).
    """
    if review_missing(status_list(client, head), forge_posted(client)) is None:
        msg = f'{head[:12]} is already reviewed by the forge: nothing to take over'
        raise TakeoverRefused(msg)
    scope = scope_of(root, review, head, base=base)
    thread = pull if pull is not None else ledger_of(client, head, base)
    with held_state(client, thread.number, head, trusted_logins(client)) as state:
        try:
            said = _taken(root, client, review, head, scope=scope, thread=thread, base=base, host=host,
                          run=within(run, datetime.now(UTC) + wait_of(review)), runtimes=runtimes,
                          batching=batch_args(review, state))  # fmt: skip
        except ReviewPending as waiting:  # nothing is posted: the same takeover, run again, resumes the batch
            msg = f'{BATCH_PENDING} {waiting}; run the takeover again to resume it'
            raise TakeoverRefused(msg) from waiting
    return (f'{said} ({len(scope.slices)} slice(s)); {RERUN} for a review that counts',)


def _taken(
    root: Path, client: Client, review: Review, head: str, *, scope: Scope, thread: PullRequest, base: str,
    host: str, run: Callable[[Sequence[str], Path], str], runtimes: Mapping[str, Mapping[str, Any]],
    batching: Sequence[str],
) -> str:  # fmt: skip
    """The takeover's review over *scope*, posted on *thread* as advice; the line said."""
    argvs = [command_for(review, scope.range, runtimes, paths=s.paths, lens=s.lens, batching=batching)
             for s in scope.slices]  # fmt: skip
    synth = command_for(review, scope.range, runtimes, synthesis=True, batching=batching)
    found = parse_findings(gather(scope.range, argvs, synth, run, root, pr_body=thread.body))
    if not any(one.status in {'ok', 'skipped'} for one in found.reviewers):
        kinds = ', '.join(f'{one.name} {one.status}' for one in found.reviewers) or 'none planned'
        msg = f'no reviewer returned findings ({kinds}); nothing is posted'
        raise TakeoverRefused(msg)
    return post_review_comment(
        root, client, thread, scope.range, found=found, by='integrator takeover', outside=scope.outside,
        unread=scope.unread, reviewer=identity(client, host), authors=sessions(root, landed_base(root, base, head),
        head), advisory=True,
    )  # fmt: skip


#: The verbs the forge's own job runs (``review.yml``, ``review-again.yml``): it asks the forge for the trusted
#: integration branch, because an Actions checkout sets no ``origin/HEAD``.
_FORGE_JOBS: Final = frozenset({'run'})


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge review', description=__doc__.splitlines()[0])
    parser.set_defaults(repo=None)
    verbs = parser.add_subparsers(dest='verb', required=True)
    for verb, what in (('takeover', "review a head the forge's review has not reached, posted as advice"),
                       ('plan', 'print the slices a takeover of a head reads')):  # fmt: skip
        door = verbs.add_parser(verb, help=what)
        door.add_argument('sha')
        door.add_argument('--repo', type=Path, help='the checkout that holds the sha (default: the working directory)')
    again = verbs.add_parser('again', help="ask the forge to review a PR's head again (a security finding fixed)")
    again.add_argument('pr', type=int)
    carrying = verbs.add_parser('carry', help='resolve, or defer with a reason, a finding a continuation PR carries')
    carrying.add_argument('pr', type=int)
    how = carrying.add_mutually_exclusive_group(required=True)
    how.add_argument('--resolve', metavar='ID', help='the carried finding is fixed in this PR')
    how.add_argument('--defer', metavar='ID', help='the carried finding is deferred: --reason says why')
    carrying.add_argument('--reason', default='', help='why (required with --defer)')
    raising = verbs.add_parser('cap', help="raise one PR's review dollar cap, the reason recorded on the PR")
    raising.add_argument('pr', type=int)
    raising.add_argument('--usd', type=float, required=True, help='the dollar cap; the month remainder bounds it')
    raising.add_argument('--reserve', action='store_true', help="draw the provider's reserve, past the review month")
    raising.add_argument('--why', required=True, help='the recorded reason for the raise')
    running = verbs.add_parser('run', help="review one PR's head: what a workflow job runs for its event")
    which = running.add_mutually_exclusive_group(required=True)
    which.add_argument('--pr', type=int)
    which.add_argument(
        '--due', action='store_true',
        help='review every open head the merge decision called due, and resume every pending batch (merge tick)',
    )  # fmt: skip
    running.add_argument(
        '--keys-env', metavar='NAME',
        help=f'the variable holding the {REVIEW_TASK} key bundle, piped to the ai-lab loader and unset; empty or '
        'unset (a fork PR) records the PR unreviewed',
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


def _job(
    args: argparse.Namespace, root: Path, origin: Client, base: str, *, run: Callable[[Sequence[str], Path], str],
    ready: Callable[[Sequence[str], Path], str | None], fetch: Callable[[Path, int], object],
) -> int:  # fmt: skip
    """``forge review run``: one PR's head (``--pr``), or every head whose review batch is pending; the exit."""
    runtimes = review_runtimes(args.runtime)
    # the ledger token is taken out of the env before any reviewer starts: no review command inherits it
    ledger = functools.partial(forge_ledger, token=os.environ.pop(LEDGER_TOKEN, '').strip())
    runner = Runner(this_machine(), runtimes, run=run, ready=ready, secret=keys_loaded(args.keys_env, runtimes),
                    verifies=True, ledger=ledger)  # fmt: skip
    review = review_at(root, base)
    if args.due:
        for one in review_due(root, origin, review, base=base, runner=runner, fetch=fetch):
            emit(f'[review] {one}')
        return 0
    with posted_verdicts() as said:
        emit(f'[review] {review_run(root, origin, review, args.pr, base=base, runner=runner)}')
    return job_exit(origin, args.pr, said, base=base)


#: The verbs a session runs on one PR's review record: each says one line (:func:`_on_a_pr`).
_ON_A_PR: Final = frozenset({'again', 'carry', 'cap'})


def _on_a_pr(args: argparse.Namespace, root: Path, origin: Client, base: str, me: Identity) -> str:
    """``review again|carry|cap <pr>``: the line said."""
    if args.verb == 'again':
        return ask_again(origin, args.pr, origin.pr_view(args.pr).head_sha, me.text())
    if args.verb == 'carry':
        state, finding = ('resolved', args.resolve) if args.resolve else ('deferred', args.defer)
        return carry(origin, review_at(root, base), args.pr, finding, state=state, reason=args.reason, who=me.text())
    return raise_cap(origin, args.pr, Raised(args.usd, args.why, reserve=args.reserve), by=me)


def _plan(root: Path, review: Review, head: str, *, base: str, pull: PullRequest | None) -> None:
    scope = scope_of(root, review, head, base=base)
    emit(
        f'{f"#{pull.number} " if pull else ""}{scope.range}: {len(scope.slices)} slice(s), '
        f'{scope.outside} non-code file(s) outside, {len(scope.unread)} code path(s) past the budget'
    )
    emit(f'  code bytes: {sum(one.size for one in scope.slices)}')
    emit(f'  moved (path change only): {len(scope.moved)}')
    for one in scope.slices:
        emit(f'  {one.lens} {one.size} B: {" ".join(one.paths)}')
    if scope.unread:
        emit(f'  not read: {" ".join(scope.unread)}')


def main(
    argv: Sequence[str] | None = None, *, cwd: Path | None = None, client: Client | None = None,
    run: Callable[[Sequence[str], Path], str] = run_command,
    ready: Callable[[Sequence[str], Path], str | None] = can_start,
    fetch: Callable[[Path, int], object] | None = None,
) -> int:  # fmt: skip
    """``forge review takeover|plan <sha>``, ``again <pr>``, ``cap <pr> --usd --why``, ``run``.

    Exit 0 done (``run``: :func:`job_exit`), 2 refused.
    """
    args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    root = args.repo or (Path.cwd() if cwd is None else cwd)
    pull_in = fetch or (lambda where, number: fetch_pull(where, 'origin', number))
    try:
        # run: the tokens arrive by file, never env, before any subprocess (F-5a82981c5f22, F-d61706393b50);
        # the task's key bundle (--keys-env) is unset once loaded, before any reviewer starts (keys_loaded).
        api = take(args.git_token_file, args.api_token_file) if args.verb == 'run' else ''
        origin = client or client_for(root, token=api)
        # never the working tree's: the head's (F-169e99e6c68c); the forge's job asks the forge (an Actions
        # checkout sets no origin/HEAD), the operator's verbs read their clone's origin/HEAD offline (dev-lab #40)
        base = trusted_integration(root, origin) if args.verb in _FORGE_JOBS else operator_integration(root)
        if args.verb == 'run':
            return _job(args, root, origin, base, run=run, ready=ready, fetch=pull_in)
        me = identity(origin, this_machine())
        if args.verb in _ON_A_PR:
            emit(f'[review] {_on_a_pr(args, root, origin, base, me)}')
            return 0
        review, pull = review_at(root, base), pull_for(origin, args.sha)  # the forge first: the PR brings its head
        if pull is not None:
            pull_in(root, pull.number)
        head = _commit(root, pull.head_sha if pull is not None else args.sha)
        if args.verb == 'plan':
            _plan(root, review, head, base=base, pull=pull)
            return 0
        for said in takeover(root, origin, review, head, pull=pull, base=base, host=this_machine(), run=run,
                             runtimes=review_runtimes()):  # fmt: skip
            emit(f'[review] {said}')
    except (TakeoverRefused, ReviewerRefused, ForgeCallFailed, OSError, ValueError, subprocess.SubprocessError) as e:
        emit(f'[review] refused: {e}', err=True)
        return 2
    return 0
