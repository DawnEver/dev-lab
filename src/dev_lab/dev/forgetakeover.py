"""REVIEW TAKEOVER: an over-cap head is the INTEGRATOR AGENT's to review, and its door is the only release.

User ruling 2026-10-26. A head a metered program review cannot read (:data:`OVER_CAP_TAKEOVER`: over
``max_total_bytes``, one file over ``max_diff_bytes``) is HELD on :data:`HOLD_CONTEXT`, and the auto-merge waits
on it. It is a TAKEOVER, as a review whose reviewers were all exhausted is: the integrator session reviews it
through the SAME method -- the declared command, sliced, ``{paths}`` and ``{lens}`` -- over EVERY slice. A session
is never metered, so the byte cap that bounds an API-key program review does not bind it (``plan(metered=False)``).
A human is asked only for a decision the review surfaces, never for the routine review or the release.

* :func:`held` -- the open PR heads into integration whose latest :data:`HOLD_CONTEXT` is ``pending``; the forge
  prompts the integrator with each (:func:`alarms`, one ``integration`` issue per head, and
  ``forge notices --integrator``), naming the door.
* ``python -m dev_lab.dev.forge review takeover <sha>`` (:func:`takeover`) runs the review, posts the findings
  comment and :data:`REVIEW_CONTEXT`, and releases the hold. ``review plan <sha>`` prints the slices only.
* :func:`release` REFUSES without a findings comment for that sha on its PR: the release is the record that a
  review happened. The raw ``forge status post --context tests/review-hold`` is refused to agents
  (``REVIEW-HOLD-VIA-TAKEOVER``), so this door is the one release.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from lab_commons.log import emit

from dev_lab.dev.forgealarm import INTEGRATION, Alarm
from dev_lab.dev.forgepulls import Marker, comment_list, marker, pr_list
from dev_lab.dev.forgereview import PATHS_FIELD, Review, command_for, load_review
from dev_lab.dev.forgereview_command import run_command
from dev_lab.dev.forgereview_dispose import DisposeRefused, dispose
from dev_lab.dev.forgereview_dispose import blocked as review_blocked
from dev_lab.dev.forgereview_dispose import line as blocked_line
from dev_lab.dev.forgereview_findings import parse_findings
from dev_lab.dev.forgereview_rounds import post_round
from dev_lab.dev.forgereview_scope import Scope, gather, plan, reviewed_heads
from dev_lab.dev.forgestatus import status_list, status_post
from dev_lab.dev.platformparts import HOLD_CONTEXT

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client, PullRequest

__all__ = ['DOOR', 'RELEASED', 'TakeoverRefused', 'alarms', 'held', 'main', 'release', 'scope_of', 'takeover']

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
    return f'#{pull.number} {pull.head_sha[:12]}: review held over the cap -- run {DOOR.format(sha=pull.head_sha)}'


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


def _pull_of(client: Client, sha: str) -> PullRequest:
    found = [pull for pull in pr_list(client) if pull.head_sha and pull.head_sha.startswith(sha)]
    if len(found) != 1:
        msg = f'{sha} is the head of {len(found)} open PRs; name one open PR head'
        raise TakeoverRefused(msg)
    return found[0]


def _comment_for(client: Client, number: int, sha: str) -> str | None:
    """The url of PR *number*'s findings comment for *sha*, else ``None``."""
    key = marker(Marker.REVIEW, sha)
    return next((one.url for one in comment_list(client, number) if key in one.body), None)


def release(client: Client, sha: str, *, host: str) -> str:
    """Release *sha*'s hold; REFUSED unless its PR carries the findings comment for *sha*. The line said."""
    pull = _pull_of(client, sha)
    url = _comment_for(client, pull.number, pull.head_sha)
    if url is None:
        msg = f'no findings comment for {pull.head_sha[:12]} on #{pull.number}: the release records a review, run one'
        raise TakeoverRefused(msg)
    status_post(client, pull.head_sha, context=HOLD_CONTEXT, state='success', description=f'{RELEASED} by {host}',
                target_url=url)  # fmt: skip
    return f'#{pull.number} {pull.head_sha[:12]}: {RELEASED} by {host}'


def scope_of(root: Path, client: Client, review: Review, pull: PullRequest, base: str) -> Scope:
    """What the takeover reads: the same range and slices as the program review, unmetered."""
    done = reviewed_heads(comment.body for comment in comment_list(client, pull.number))
    sliceable = PATHS_FIELD in review.command
    return plan(root, f'origin/{base}', pull.head_sha, review.budget, done, sliceable=sliceable, metered=False)


def takeover(
    root: Path, client: Client, review: Review, sha: str, *, base: str, host: str,
    run: Callable[[Sequence[str], Path], str] = run_command,
    capabilities: Mapping[str, Mapping[str, Any]] = MappingProxyType({}),
) -> tuple[str, ...]:  # fmt: skip
    """Review held *sha* over every slice, post the findings and :data:`REVIEW_CONTEXT`, release; the lines said."""
    pull = _pull_of(client, sha)
    if pull not in held(client, base):
        msg = f'#{pull.number} {pull.head_sha[:12]} carries no pending {HOLD_CONTEXT}: nothing to take over'
        raise TakeoverRefused(msg)
    if not review.command:
        msg = '[tool.lab_commons.review] command is not declared: there is no method to review with'
        raise TakeoverRefused(msg)
    scope = scope_of(root, client, review, pull, base)
    if scope.held is not None:
        msg = f'{scope.held}: declare {PATHS_FIELD} in the review command'
        raise TakeoverRefused(msg)
    argvs = [command_for(review, scope.range, capabilities, paths=s.paths, lens=s.lens) for s in scope.slices]
    synth = command_for(review, scope.range, capabilities, synthesis=True)
    found = parse_findings(gather(scope.range, argvs, synth, run, root))
    if not any(one.status in {'ok', 'skipped'} for one in found.reviewers):
        kinds = ', '.join(f'{one.name} {one.status}' for one in found.reviewers) or 'none planned'
        msg = f'no reviewer returned findings ({kinds}); nothing is posted and the hold stands'
        raise TakeoverRefused(msg)
    said = post_round(
        root, client, pull, scope.range, found=found, max_rounds=review.max_rounds, by='integrator takeover'
    )
    return f'{said} ({len(scope.slices)} slice(s))', release(client, pull.head_sha, host=host)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge review', description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    verbs.add_parser('takeover', help='review a held head over every slice, post it, release the hold').add_argument(
        'sha'
    )
    verbs.add_parser('plan', help='print the slices a takeover of a held head reads').add_argument('sha')
    verbs.add_parser('held', help='list the held heads and the door for each')
    disposal = verbs.add_parser('dispose', help='close a blocking finding with a reason (the integrator only)')
    disposal.add_argument('pr', type=int)
    disposal.add_argument('finding')
    disposal.add_argument('--why', required=True, help='why it is not fixed: refused when empty')
    verbs.add_parser('blocked', help='list the heads a blocking finding holds, with their ids and the door')
    return parser


def main(
    argv: Sequence[str] | None = None, *, cwd: Path | None = None, client: Client | None = None,
    run: Callable[[Sequence[str], Path], str] = run_command,
    fetch: Callable[[Path, int], object] | None = None,
) -> int:  # fmt: skip
    """``forge review takeover|plan <sha>``, ``held``, ``blocked``, ``dispose <pr> <id> --why``.

    Exit 0 done, 1 held or blocked heads listed, 2 refused.
    """
    from lab_commons.box.machine import provided  # noqa: PLC0415
    from lab_commons.config import section  # noqa: PLC0415

    from dev_lab.dev.forgeclaim import this_machine  # noqa: PLC0415
    from dev_lab.dev.forgeintegration import _fetch_pull  # noqa: PLC0415
    from dev_lab.dev.forgework import ForgeCallFailed, client_for  # noqa: PLC0415
    from dev_lab.dev.lanepolicy import load_policy  # noqa: PLC0415

    args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd() if cwd is None else cwd
    pull_in = fetch or (lambda where, number: _fetch_pull(where, 'origin', number))
    try:
        origin, base = client or client_for(root), load_policy(root).integration
        if args.verb == 'held':
            pulls = held(origin, base)
            for pull in pulls:
                emit(line(pull))
            return 1 if pulls else 0
        if args.verb == 'blocked':
            rows = review_blocked(origin, base)
            for pull, ids in rows:
                emit(blocked_line(pull, ids))
            return 1 if rows else 0
        if args.verb == 'dispose':
            emit(f'[review] {dispose(origin, args.pr, args.finding, args.why, host=this_machine())}')
            return 0
        review, pull = load_review(root), _pull_of(origin, args.sha)
        pull_in(root, pull.number)
        if args.verb == 'plan':
            scope = scope_of(root, origin, review, pull, base)
            emit(
                f'#{pull.number} {scope.range}: {len(scope.slices)} slice(s){f" -- {scope.held}" if scope.held else ""}'
            )
            for one in scope.slices:
                emit(f'  {one.lens} {one.size} B: {" ".join(one.paths)}')
            return 0
        here = provided(section('capabilities'))
        for said in takeover(
            root, origin, review, args.sha, base=base, host=this_machine(), run=run, capabilities=here
        ):
            emit(f'[review] {said}')
    except (
        TakeoverRefused,
        DisposeRefused,
        ForgeCallFailed,
        OSError,
        ValueError,
        subprocess.SubprocessError,
    ) as failed:
        emit(f'[review] refused: {failed}', err=True)
        return 2
    return 0
