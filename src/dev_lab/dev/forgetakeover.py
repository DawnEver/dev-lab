"""REVIEW TAKEOVER: a head whose review could not run is the INTEGRATOR AGENT's to review; its door is the only release.

A head is HELD on :data:`HOLD_CONTEXT` only when the review could not run for it -- its job had no review secret
(:data:`~dev_lab.dev.forgereview.NEEDS_MAINTAINER`) or its host could not run the command
(:class:`~dev_lab.dev.forgereview.HostCannot`) -- never for its size (D123, user ruling 2026-10-31, superseding the
2026-10-26 hold-on-oversize). The integrator session reviews it through the SAME method and scope the program
review reads, and the auto-merge waits on the hold until then. It is also the Break-Glass path's review
(:mod:`dev_lab.dev.breakglass`). A human is asked only for a decision the review surfaces.

* :func:`held` -- the open PR heads into integration whose latest :data:`HOLD_CONTEXT` is ``pending``; the forge
  prompts the integrator with each (:func:`alarms`, one ``integration`` issue per head, and
  ``forge notices --integrator``), naming the door.
* ``python -m dev_lab.dev.forge review takeover <sha>`` (:func:`takeover`) runs the review, posts the findings
  comment and :data:`REVIEW_CONTEXT`, and releases the hold. ``review plan <sha>`` prints the slices only.
* :func:`release` REFUSES without a findings comment for that sha on its PR: the release is the record that a
  review happened. The raw ``forge status post --context tests/review-hold`` is refused to agents
  (``STATUS-VIA-DOORS``), so this door is the one release.
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
from dev_lab.dev.forgepulls import Marker, comment_list, marker, pages, pr_list
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
from dev_lab.dev.forgereview_dispose import adjudicate_thread, dispose, merge_ready_after
from dev_lab.dev.forgereview_dispose import blocked as review_blocked
from dev_lab.dev.forgereview_dispose import line as blocked_line
from dev_lab.dev.forgereview_findings import parse_findings
from dev_lab.dev.forgereview_judge import AdjudicationRefused, identity, upheld
from dev_lab.dev.forgereview_rounds import post_round, trailed, trusted_bodies
from dev_lab.dev.forgereview_runtimes import host_runtimes
from dev_lab.dev.forgereview_scope import Scope, gather, git, landed_base, plan, reviewed_heads
from dev_lab.dev.forgestatus import status_list, status_post
from dev_lab.dev.forgework import ACTIONS_BOT, GITHUB, ForgeCallFailed, PullRequest, client_for
from dev_lab.dev.labsession import sessions
from dev_lab.dev.lanepolicy import load_policy
from dev_lab.dev.platformparts import HOLD_CONTEXT
from dev_lab.dev.reviewgate import review_missing

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = [
    'DOOR', 'LEDGER_TITLE', 'RELEASED', 'TakeoverRefused', 'alarms', 'held', 'ledger_of', 'main', 'pull_for',
    'release', 'review_run', 'runtimes_with', 'scope_of', 'takeover',
]  # fmt: skip

#: The door the integrator runs on a held head; ``{sha}`` is the head.
DOOR: Final = 'python -m dev_lab.dev.forge review takeover {sha}'

#: What a released :data:`HOLD_CONTEXT` says (``success``), followed by who and the findings comment.
RELEASED: Final = 'released after the integrator review'


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
    return f'#{pull.number} {pull.head_sha[:12]}: review held -- run {DOOR.format(sha=pull.head_sha)}'


def alarms(client: Client, base: str, repo: str) -> list[Alarm]:
    """One ``integration`` prompt per held head, keyed by its sha, naming the door."""
    return [
        Alarm(
            INTEGRATION,
            repo,
            f'review held {pull.head_sha[:12]} (#{pull.number})',
            f'{line(pull)}. The integrator reviews it over every slice and the door releases tests/review-hold; '
            'a human is asked only for a decision the review surfaces.',
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

    Only an issue the FORGE opened is the ledger (F-7fbe6eafaadf, security): its own login, or the workflow bot on
    GitHub -- never a squatter's issue of the same title, and never a PR (GitHub's issues API lists PRs too).
    """
    title = LEDGER_TITLE.format(sha=head)
    mine = {client.whoami(), *((ACTIONS_BOT,) if client.backend is GITHUB else ())}
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


def _comment_for(client: Client, number: int, sha: str) -> str | None:
    """The url of PR *number*'s findings comment for *sha*, else ``None``."""
    key = marker(Marker.REVIEW, sha)
    return next((one.url for one in comment_list(client, number) if key in one.body), None)


def release(client: Client, pull: PullRequest, *, host: str) -> str:
    """Release *pull*'s head hold; REFUSED unless it carries the findings comment for that head. The line said."""
    url = _comment_for(client, pull.number, pull.head_sha)
    if url is None:
        msg = f'no findings comment for {pull.head_sha[:12]} on #{pull.number}: the release records a review, run one'
        raise TakeoverRefused(msg)
    status_post(client, pull.head_sha, context=HOLD_CONTEXT, state='success', description=f'{RELEASED} by {host}',
                target_url=url)  # fmt: skip
    return f'#{pull.number} {pull.head_sha[:12]}: {RELEASED} by {host}'


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
    """Review *head* where its review is missing -- an open, closed or merged *pull*, or a plain commit -- and post it.

    The emergency door of :mod:`dev_lab.dev.breakglass` and of a merge that waits on a review that could not run: it
    must always be satisfiable, so it refuses only a head already reviewed. A head with no PR keeps its ledger in its
    own issue (:func:`ledger_of`), where a blocking finding is disposed of as on a PR (``dispose <issue> <id>``).
    """
    if review_missing(status_list(client, head)) is None:
        msg = f'{head[:12]} is already reviewed: nothing to take over'
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
        runtimes), reviewer=identity(client, host), authors=sessions(root, since, head),
    )  # fmt: skip
    pending = next((one for one in status_list(client, head) if one.context == HOLD_CONTEXT), None)
    released = (release(client, pull, host=host),) if pull and pending and pending.state == 'pending' else ()
    after = () if pull is None else tuple(merge_ready_after(root, client, pull.number))
    return (f'{said} ({len(scope.slices)} slice(s))', *released, *after)


#: What the hold says when the job's host cannot run the review command: the takeover door reviews the head.
HOST_CANNOT: Final = 'the review job cannot run the review command'


def review_run(root: Path, client: Client, review: Review, number: int, *, base: str, runner: Runner) -> str:
    """:func:`review_pull` on PR *number* alone -- what a GitHub workflow job runs for its event's PR; the line.

    The job is the ONLY reviewer of its PR, so a host that cannot run the command is never silent: the head is held
    for ``forge review takeover <sha>`` and :class:`~dev_lab.dev.forgereview.HostCannot` is raised (the job fails).
    """
    pull = client.pr_view(number)
    if pull.base != base or pull.draft or not pull.head_sha:
        return f'#{number}: not reviewed -- only an open, non-draft PR into {base} is'
    try:
        return review_pull(root, client, review, pull, runner) or f'#{number} {pull.head_sha[:12]}: already reviewed'
    except HostCannot as cannot:
        raise HostCannot(hold(client, pull, f'{HOST_CANNOT}: {cannot}')) from cannot


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
    ruling = verbs.add_parser('adjudicate', help='rule on every pending claim of a thread (the forge runs this)')
    ruling.add_argument('number', type=int, help="the PR, or a PR-less head's ledger issue")
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
    ruled = adjudicate_thread(
        root, origin, load_review(root), args.number, base=base, adjudicator=me, run=run,
        runtimes=runtimes_with(host_runtimes(), args.runtime),
    )  # fmt: skip
    return [f'[review] {one}' for one in ruled]


def main(
    argv: Sequence[str] | None = None, *, cwd: Path | None = None, client: Client | None = None,
    run: Callable[[Sequence[str], Path], str] = run_command,
    ready: Callable[[Sequence[str], Path], str | None] = can_start,
    fetch: Callable[[Path, int], object] | None = None,
) -> int:  # fmt: skip
    """``forge review takeover|plan <sha>``, ``held``, ``blocked``, ``dispose <pr> <id> --why``, ``run --pr <N>``.

    Exit 0 done, 1 held or blocked heads listed, 2 refused.
    """
    args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    root = args.repo or (Path.cwd() if cwd is None else cwd)
    pull_in = fetch or (lambda where, number: _fetch_pull(where, 'origin', number))
    try:
        origin, base = client or client_for(root), load_policy(root).integration
        if args.verb == 'run':
            secret = all(os.environ.get(name) for name in args.secret_env)
            runner = Runner(
                this_machine(), runtimes_with(host_runtimes(), args.runtime), run=run, ready=ready, secret=secret
            )
            emit(f'[review] {review_run(root, origin, load_review(root), args.pr, base=base, runner=runner)}')
            return 0
        if args.verb in {'held', 'blocked', 'dispose', 'adjudicate'}:
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
