"""``forge merge ready [--pr <N>]``: post each PR head its ONE merge decision status, and merge a ready head.

Split out of :mod:`dev_lab.dev.forgemerge`, which DECIDES (:func:`~dev_lab.dev.forgemerge.judged`); this posts
that decision as :data:`~dev_lab.dev.forgecontexts.MERGE_READY_CONTEXT` and, where the job merges (GitHub, or a
repo that :func:`~dev_lab.dev.forgemerge.ci_merges`), asks the forge to merge
(:func:`dev_lab.dev.forgemergecall.merge`). One PR's failure never stops the tick.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons.log import emit

from dev_lab.dev.branchset import declared_branchset
from dev_lab.dev.forgecontexts import MERGE_READY_CONTEXT
from dev_lab.dev.forgedraft import waiting
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgemerge import EXTERNAL, Decision, ci_merges, external, judged
from dev_lab.dev.forgemergecall import merge
from dev_lab.dev.forgepulls import ListingIncomplete, pr_list
from dev_lab.dev.forgestatus import status_post
from dev_lab.dev.forgework import GITHUB, client_for
from dev_lab.dev.lanepolicy import load_policy
from dev_lab.dev.reviewturn import review_turn

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = ['READY', 'main', 'ready']

#: What a ``success`` :data:`~dev_lab.dev.forgecontexts.MERGE_READY_CONTEXT` says.
READY: Final = 'ready: every merge condition holds'


def ready(root: Path, client: Client, number: int) -> str:
    """Post PR *number*'s :func:`~dev_lab.dev.forgemerge.judged` decision as ONE :data:`MERGE_READY_CONTEXT` status.

    The line said is returned.

    ``success`` when nothing is missing, ``pending`` naming what is when it only waits on a check not yet terminal
    (:attr:`~dev_lab.dev.forgemerge.Decision.waiting`), else ``failure`` naming it (cut to the forge's description
    limit; the workflow log carries the whole line). A PR into another branch than the PR base is ``failure`` saying
    so. On GitHub, or where the repo :func:`~dev_lab.dev.forgemerge.ci_merges`, a ``success`` is followed by the merge
    of that judged head (:func:`~dev_lab.dev.forgemergecall.merge`); a refusal -- the head
    moved, a required check still pending -- is said, never raised: the decision stands posted either way.
    """
    policy, pull = load_policy(root), client.pr_view(number)
    if pull.base != policy.integration:
        decision = Decision((f'a PR into {policy.integration}, not {pull.base}',), '')
    elif pull.draft:  # D53: pending, naming the ready door -- it waits on its author, not on a check
        return waiting(client, pull) or f'#{number} {pull.head_sha[:12]} {MERGE_READY_CONTEXT} pending: draft'
    elif external(client, pull):  # pending: it waits on a maintainer, never on a check
        status_post(client, pull.head_sha, context=MERGE_READY_CONTEXT, state='pending', description=EXTERNAL)
        return f'#{number} {pull.head_sha[:12]} {MERGE_READY_CONTEXT} pending: {EXTERNAL}'
    else:
        decision = judged(root, client, policy, branch=pull.head, number=number, head=pull.head_sha)
    missing = decision.missing
    suffix = f' ({"; ".join(decision.notes)})' if decision.notes else ''
    held = 'pending' if decision.waiting else 'failure'
    state, why = (held, 'waits on: ' + '; '.join(missing) + suffix) if missing else ('success', READY + suffix)
    if decision.unreviewed and not missing:
        why = f'{READY}{suffix}, WARNED -- {decision.unreviewed}'
    elif decision.review is not None and not missing:
        why = f'{READY}{suffix}, WARNED -- its advisory review: {decision.review}'
    status_post(client, pull.head_sha, context=MERGE_READY_CONTEXT, state=state, description=why)
    turn = review_turn(client, number, pull.head_sha, decision)  # the review is the last gate: asked here
    said = f'#{number} {pull.head_sha[:12]} {MERGE_READY_CONTEXT} {state}: {why}{turn}'
    if missing or (client.backend is not GITHUB and not ci_merges(root)):
        return said
    ephemeral = declared_branchset(root).is_ephemeral(pull.head)
    try:
        merge(client, number, head=pull.head_sha, message=decision.message, delete_branch=ephemeral)
    except ForgeCallFailed as refused:
        return f'{said}; NOT merged -- {refused}'
    if unpassed := decision.unreviewed or decision.review:
        client.issue_comment(number, f'Merged WITHOUT a passing review (advisory) -- {unpassed}')
    return f'{said}; merged'


def main(argv: Sequence[str] | None = None, *, cwd: Path | None = None, client: Client | None = None) -> int:
    """``forge merge ready [--pr <N>]``: post the merge decision of PR *N*, else of every open PR into integration.

    Exit 0 posted (ready or not), 2 refused.
    """
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge merge', description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    verbs.add_parser('ready', help=f'post the PR head its {MERGE_READY_CONTEXT} decision').add_argument(
        '--pr', type=int, help='one PR; omitted: every open PR into the integration branch'
    )
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd() if cwd is None else cwd
    try:
        built = client or client_for(root)
        if args.pr is not None:
            numbers = [args.pr]
        else:
            into = load_policy(root).integration
            numbers = [pull.number for pull in pr_list(built) if pull.base == into]
    except (ForgeCallFailed, ListingIncomplete, OSError, ValueError) as failed:
        emit(f'[merge] refused: {failed}', err=True)
        return 2
    failed = [number for number in numbers if not _ready_or_said(root, built, number)]
    if failed:
        emit(
            f'[merge] refused: {len(failed)} PR(s) could not be judged: {", ".join(f"#{n}" for n in failed)}', err=True
        )
        return 2
    return 0


def _ready_or_said(root: Path, client: Client, number: int) -> bool:
    """Run :func:`ready` on PR *number*; whether it ran. ONE PR'S FAILURE NEVER STOPS THE TICK.

    Any exception judging it (a forge call, an audit's git timing out) is that PR's ``error`` status naming the
    cause, said on stderr; the PRs after it are still judged, and :func:`main` exits non-zero at the end.
    """
    try:
        emit(f'[merge] {ready(root, client, number)}')
    except Exception as error:  # noqa: BLE001 -- any cause is this PR's, never the tick's
        why = f'could not be judged: {_cause(error)}'
        emit(f'[merge] #{number} {why}', err=True)
        try:
            head = client.pr_view(number).head_sha
            status_post(client, head, context=MERGE_READY_CONTEXT, state='error', description=why)
        except Exception as unposted:  # noqa: BLE001 -- the line above already said it
            emit(f'[merge] #{number} its error status was not posted: {unposted}', err=True)
        return False
    return True


def _cause(error: BaseException) -> str:
    """What went wrong, in one line: a timeout names the command and its limit."""
    if isinstance(error, subprocess.TimeoutExpired):
        argv = error.cmd if isinstance(error.cmd, str) else ' '.join(map(str, error.cmd[:4]))
        return f'`{argv}` timed out after {error.timeout:g} s'
    return f'{type(error).__name__}: {error}'
