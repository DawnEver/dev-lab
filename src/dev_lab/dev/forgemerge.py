"""INTEGRATION-TAKES-ONLY-FORGE-MERGES: the forge merges a green pull request into integration, server side.

User ruling 2026-10-19: every change is a short-lived branch returning by a PR to the integration branch,
which takes ONLY server-side merges of PRs whose every forge part passed. Opted into by declaring
``[tool.dev_lab.integrator] pr_merges_since = "<sha>"``; from then on the integration tick
(:func:`dev_lab.dev.forgeintegration.tick`) asks :func:`decide` of each open PR into integration and,
when nothing is missing, asks the forge to merge it (:func:`merge`). A client push adding a commit to the
branch is refused at pre-push (:mod:`dev_lab.dev.sessionbranch`, P5).

ONE DECISION ON BOTH FORGES (user ruling 2026-10-29); only who MERGES differs. :func:`judged` reads a PR's head and
decides; on Gitea the serve tick merges on it, and on GitHub a workflow job runs ``forge merge ready --pr <N>``
(:func:`ready`), which posts the decision as ONE status, :data:`~dev_lab.dev.forgecontexts.MERGE_READY_CONTEXT`, and
GitHub's native auto-merge -- enabled on every PR ``forge pr create`` opens there -- merges once that required check
is green. The PR base is :attr:`~dev_lab.dev.lanepolicy.Policy.pr_base`: integration where declared, else the trunk.

A PR IS MERGED WHEN, and only when, read from the object store and the forge:

* every ``tests/<part>`` part of its head stands PASS (:func:`dev_lab.dev.platformparts.standing`), except a
  scarce part its diff does not reach -- WAIVED, run on integration after the merge
  (:mod:`dev_lab.dev.forgescarce`, user ruling 2026-10-22);
* its review is not HELD: a pending ``tests/review-hold`` waits until the integrator's takeover review releases it
  (``forge review takeover <sha>``, :mod:`dev_lab.dev.forgetakeover`; :func:`review_hold`);
* its review does not BLOCK it (:func:`review_blocks`, user ruling 2026-10-26): with a review declared, the head's
  ``tests/review`` must be posted -- absent or a claim still reviewing waits -- and not ``failure``, which says an
  open HIGH or security finding is neither fixed nor disposed (:mod:`dev_lab.dev.forgereview_rounds`). An
  ``error`` (a review that could not run) stays advisory;
* its head's ``tests/security`` stands ``success`` (:mod:`dev_lab.dev.forgesecurity`): ``failure`` names the
  findings, ``error`` is a scan that gave no answer, and both wait;
* its head merges into ``origin/<integration>`` with no conflict (it contains integration, or the
  three-way merge is clean -- :func:`dev_lab.dev.trialmerge.trial`);
* the merge commit the forge will write passes the merge audit
  (:func:`dev_lab.dev.mergeaudit.judge`, the same judgement the commit-msg hook makes) -- its message
  names the branch (``Merged-Branch:``), so INTEGRATION-IS-MERGES-ONLY holds of it too;
* every merge commit its head adds over integration declares each file its parents conflict on
  (:func:`dev_lab.dev.mergeresolution.unresolved`, MERGE-RESOLUTION-DECLARED) -- the one place no client and no
  web-UI merge can skip it.

Otherwise the PR stays open and the missing conditions are said in its one integration comment. The merge
is a MERGE COMMIT (``Do: merge``, never squash or rebase), pinned to the judged head (``head_commit_id``: a
head that moved since is refused by the forge, and judged afresh next tick). A head in a declared ephemeral
namespace is deleted by the forge with the merge.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons.log import emit
from lab_commons.outcomes import Conclusion

from dev_lab.dev.forgecontexts import MERGE_READY_CONTEXT
from dev_lab.dev.forgereview import TAKEOVER_PENDING, load_review
from dev_lab.dev.forgescarce import unreached
from dev_lab.dev.forgesecurity import security_wait
from dev_lab.dev.forgestatus import status_list, status_post
from dev_lab.dev.forgework import GITEA, GITHUB, ForgeCallFailed, client_for
from dev_lab.dev.lanepolicy import load_policy
from dev_lab.dev.mergeaudit import MergeAuditError, judge
from dev_lab.dev.mergeresolution import unresolved
from dev_lab.dev.platformparts import HOLD_CONTEXT, REVIEW_CONTEXT, standing
from dev_lab.dev.sessionbranch import MERGED_BRANCH
from dev_lab.dev.trialmerge import trial

if TYPE_CHECKING:
    from dev_lab.dev.forgestatus import CommitStatus
    from dev_lab.dev.forgework import Client
    from dev_lab.dev.lanepolicy import Policy

__all__ = [
    'FORGE_PULL', 'READY', 'Decision', 'auto_merge', 'decide', 'judged', 'main', 'merge', 'merge_message', 'ready',
    'review_blocks',
    'review_hold',
]  # fmt: skip

#: The trailer naming the pull request a forge merge closed.
FORGE_PULL: Final = 'Forge-Pull'

#: What a ``success`` :data:`MERGE_READY_CONTEXT` says.
READY: Final = 'ready: every merge condition holds'

#: GitHub's native auto-merge, as a merge commit (never squash or rebase: the merge audit reads merge commits).
_AUTO_MERGE: Final = (
    'mutation($id: ID!) { enablePullRequestAutoMerge(input: {pullRequestId: $id, mergeMethod: MERGE}) '
    '{ clientMutationId } }'
)


def review_hold(statuses: Sequence[CommitStatus]) -> str | None:
    """Why a merge of the commit waits on its review, or ``None``: a latest :data:`HOLD_CONTEXT` not yet released."""
    latest = next((one for one in statuses if one.context == HOLD_CONTEXT), None)
    if latest is None or latest.state == 'success':
        return None
    return f'{HOLD_CONTEXT} is {latest.state}: {latest.description}'


def review_blocks(statuses: Sequence[CommitStatus]) -> str | None:
    """Why a merge of the commit waits on a DECLARED review, or ``None``: its ``tests/review`` absent, pending, failed.

    ``pending`` is a claim still reviewing or a head held over the cap; ``error`` and :data:`TAKEOVER_PENDING` (no
    reviewer could run) stay advisory, as before the ruling: no finding exists to block on.
    """
    latest = next((one for one in statuses if one.context == REVIEW_CONTEXT), None)
    if latest is None:
        return f'{REVIEW_CONTEXT} is not posted yet: the head is not reviewed'
    if latest.state == 'failure' or (latest.state == 'pending' and not latest.description.startswith(TAKEOVER_PENDING)):
        return f'{REVIEW_CONTEXT} is {latest.state}: {latest.description}'
    return None


@dataclass(frozen=True)
class Decision:
    """Whether one PR may be merged now: what is missing (nothing, when it may), and the message it merges with."""

    missing: tuple[str, ...]
    message: str

    @property
    def ready(self) -> bool:
        """Whether nothing is missing."""
        return not self.missing


def merge_message(branch: str, number: int, policy: Policy) -> str:
    """The merge commit's message: a conventional subject, then the ``Merged-Branch``/``Forge-Pull`` trailers."""
    return (
        f'chore(merge): {branch} into {policy.pr_base} (#{number})\n\n'
        f'{MERGED_BRANCH}: {branch}\n{FORGE_PULL}: {number}\n'
    )


def decide(
    root: Path,
    policy: Policy,
    *,
    branch: str,
    number: int,
    head: str,
    statuses: Sequence[CommitStatus],
    waived: frozenset[str] = frozenset(),
) -> Decision:
    """What PR *number* (*branch* at *head*) lacks to be merged into ``origin/<integration>``; writes nothing.

    *waived* are the scarce parts its diff does not reach (:func:`dev_lab.dev.forgescarce.unreached`).
    """
    into = policy.pr_base
    base = f'refs/remotes/origin/{into}'
    message = merge_message(branch, number, policy)
    missing: list[str] = []
    stood = standing(statuses, head=head, waived=waived)
    if stood.result is not Conclusion.PASS:
        but = f' but the unreached scarce {", ".join(sorted(waived))}' if waived else ''
        missing.append(f'every `tests/<part>` part{but} PASS on {head[:12]} (it stands {stood.reading})')
    if (held := review_hold(statuses)) is not None:
        missing.append(f'its review: {held}')
    if load_review(root).command and (blocks := review_blocks(statuses)) is not None:
        missing.append(f'its review: {blocks}')
    if (unsafe := security_wait(statuses)) is not None:
        missing.append(f'its security check: {unsafe}')
    tried = trial(root, base, head)
    if not tried.clean:
        files = ', '.join(f'`{name}`' for name in tried.conflicts)
        missing.append(
            f'a clean merge: it conflicts with `{into}` in {files} -- merge `{into}` '
            f'into the branch (python -m dev_lab.dev.forge sync) and push it'
        )
    else:
        try:
            problems = judge(root, [base, head], tried.tree, message, roots=policy.test_roots, label=f'#{number}')
        except MergeAuditError as error:
            problems = (str(error),)
        missing += [f'a merge the audit passes: {problem}' for problem in problems]
    try:
        undeclared = unresolved(root, base, head)
    except MergeAuditError as error:
        undeclared = (('?', (str(error),)),)
    missing += [
        f'merge {sha[:12]} declaring its resolution (MERGE-RESOLUTION-DECLARED): {"; ".join(problems)} -- a merge '
        f'message cannot be amended, so redo that merge with one `<path>: <class> -- <why>` line per conflicted '
        f'file and push the redone branch'
        for sha, problems in undeclared
    ]
    return Decision(tuple(missing), message)


def judged(root: Path, client: Client, policy: Policy, *, branch: str, number: int, head: str) -> Decision:
    """:func:`decide` on PR *number*'s *head* as the forge holds it now: its statuses, its unreached scarce parts."""
    statuses = [one for one in status_list(client, head) if one.context != MERGE_READY_CONTEXT]
    waived = unreached(root, client, policy.pr_base, head, statuses)
    return decide(root, policy, branch=branch, number=number, head=head, statuses=statuses, waived=waived)


def ready(root: Path, client: Client, number: int) -> str:
    """Post PR *number*'s :func:`judged` decision as ONE :data:`MERGE_READY_CONTEXT` status on its head; the line.

    ``success`` when nothing is missing, else ``failure`` naming what is (cut to the forge's description limit; the
    workflow log carries the whole line). A PR into another branch than the PR base is ``failure`` saying so.
    """
    policy, pull = load_policy(root), client.pr_view(number)
    if pull.base != policy.pr_base:
        missing: tuple[str, ...] = (f'a PR into {policy.pr_base}, not {pull.base}',)
    else:
        missing = judged(root, client, policy, branch=pull.head, number=number, head=pull.head_sha).missing
    state, why = ('failure', 'waits on: ' + '; '.join(missing)) if missing else ('success', READY)
    status_post(client, pull.head_sha, context=MERGE_READY_CONTEXT, state=state, description=why)
    return f'#{number} {pull.head_sha[:12]} {MERGE_READY_CONTEXT} {state}: {why}'


def main(argv: Sequence[str] | None = None, *, cwd: Path | None = None, client: Client | None = None) -> int:
    """``forge merge ready --pr <N>``: post the PR's merge decision. Exit 0 posted (ready or not), 2 refused."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge merge', description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    verbs.add_parser('ready', help=f'post the PR head its {MERGE_READY_CONTEXT} decision').add_argument(
        '--pr', type=int, required=True
    )
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd() if cwd is None else cwd
    try:
        emit(f'[merge] {ready(root, client or client_for(root), args.pr)}')
    except (ForgeCallFailed, OSError, ValueError) as failed:
        emit(f'[merge] refused: {failed}', err=True)
        return 2
    return 0


def auto_merge(client: Client, number: int) -> str:
    """Have PR *number* merged once its merge decision is green; the line said. Who MERGES is the forge's.

    Gitea: nothing to ask -- the serve tick merges on the decision (:func:`judged`). GitHub: its native auto-merge,
    a merge commit, which waits on the branch's required checks (:data:`MERGE_READY_CONTEXT` among them). A refusal
    GitHub answers (auto-merge off for the repository, a PR already mergeable) is said, never raised.
    """
    if client.backend is not GITHUB:
        return f'#{number}: the forge serve tick merges it once its merge decision is green'
    node = client.call('GET', f'{client.repo}/pulls/{number}')['node_id']
    answer = client.call('POST', '/graphql', {'query': _AUTO_MERGE, 'variables': {'id': node}})
    if errors := answer.get('errors'):
        return f'#{number}: auto-merge NOT enabled -- {errors[0].get("message", errors[0])}'
    return f'#{number}: auto-merge enabled -- GitHub merges it (a merge commit) once its required checks are green'


def merge(client: Client, number: int, *, head: str, message: str, delete_branch: bool) -> None:
    """Ask the forge to merge PR *number* at *head* with a merge commit saying *message*.

    Raises:
        ValueError: the forge is not gitea-shaped -- the one merge door built (UNSUPPORTED-RAISES).

    """
    if client.backend is not GITEA:
        msg = f'a server-side PR merge is built for gitea only; {client.forge.host} is {client.backend.name}'
        raise ValueError(msg)
    title, _, body = message.partition('\n\n')
    client.call(
        'POST',
        f'{client.repo}/pulls/{number}/merge',
        {
            'Do': 'merge',
            'MergeTitleField': title,
            'MergeMessageField': body,
            'head_commit_id': head,
            'delete_branch_after_merge': delete_branch,
        },
    )
