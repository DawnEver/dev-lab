"""INTEGRATION-TAKES-ONLY-FORGE-MERGES: the forge merges a reviewed, safe, clean PR into integration, server side.

User ruling 2026-10-19: every change is a short-lived branch returning by a PR to the integration branch,
which takes ONLY server-side merges. THE TEST PARTS DO NOT GATE THAT MERGE (user ruling 2026-10-29, every repo):
they still run on a PR head, and a part that is absent, pending or FAILED is reported, but full PASS is required
only to promote integration to the trunk (:func:`dev_lab.dev.integrate.promote`). Opted into by declaring
``[tool.dev_lab.integrator] pr_merges_since = "<sha>"``; from then on the integration tick
(:func:`dev_lab.dev.forgeintegration.tick`) asks :func:`decide` of each open PR into integration and,
when nothing is missing, asks the forge to merge it (:func:`merge`). A client push adding a commit to the
branch is refused at pre-push (:mod:`dev_lab.dev.sessionbranch`, P5).

ONE DECISION ON BOTH FORGES (user ruling 2026-10-29); only who MERGES differs. :func:`judged` reads a PR's head and
decides; on Gitea the serve tick merges on it, and on GitHub a workflow job runs ``forge merge ready --pr <N>``
(:func:`ready`), which posts the decision as ONE status, :data:`~dev_lab.dev.forgecontexts.MERGE_READY_CONTEXT`, and
GitHub's native auto-merge -- enabled on every PR ``forge pr create`` opens there -- merges once that required check
is green. The PR base is :attr:`~dev_lab.dev.lanepolicy.Policy.integration`.

A PR IS MERGED WHEN, and only when, read from the object store and the forge:

* its head is REVIEWED (:func:`dev_lab.dev.reviewgate.review_missing`, user ruling 2026-10-31): the latest
  ``tests/review`` is a ``success`` the FORGE posted (its recorded creator, D11) and no ``tests/review-hold`` is
  pending. Absent, reviewing, ``error``, ``failure`` and a success any other login posted all wait -- nothing is
  advisory; a review that cannot run is re-run by the forge;
* its head's ``tests/security`` stands ``success`` (:mod:`dev_lab.dev.forgesecurity`): ``failure`` names the
  findings, ``error`` is a scan that gave no answer, and both wait;
* its head merges into ``origin/<integration>`` with no conflict (it contains integration, or the
  three-way merge is clean -- :func:`dev_lab.dev.trialmerge.trial`);
* the merge commit the forge will write passes the merge audit
  (:func:`dev_lab.dev.mergeaudit.judge`, the same judgement the commit-msg hook makes) -- its message
  names the branch (``Merged-Branch:``), so INTEGRATION-IS-MERGES-ONLY holds of it too;
* every commit its head adds over integration passes the repo's OWN declared message row -- the pre-push row
  running ``cz-push-range``, run here on the range ``origin/<integration>..<head>`` with that row's env, its named
  exemptions included (:func:`message_wait`). A worktree with no venv skips that row at commit and push, so the
  merge is the one place no client can skip it; a repo declaring no such row is not judged on messages;
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
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.forgecontexts import MERGE_READY_CONTEXT
from dev_lab.dev.forgereview import load_review
from dev_lab.dev.forgesecurity import security_wait
from dev_lab.dev.forgestatus import status_list, status_post
from dev_lab.dev.forgework import GITEA, GITHUB, ForgeCallFailed, client_for
from dev_lab.dev.githooks import PYTHON_ENV, bash_executable, hook_path
from dev_lab.dev.githooks.table import hook_table
from dev_lab.dev.lanepolicy import load_policy
from dev_lab.dev.mergeaudit import MergeAuditError, judge
from dev_lab.dev.mergeresolution import unresolved
from dev_lab.dev.reviewgate import forge_creators, review_missing
from dev_lab.dev.sessionbranch import MERGED_BRANCH
from dev_lab.dev.trialmerge import trial

if TYPE_CHECKING:
    from dev_lab.dev.forgestatus import CommitStatus
    from dev_lab.dev.forgework import Client
    from dev_lab.dev.lanepolicy import Policy

__all__ = [
    'FORGE_PULL', 'READY', 'Decision', 'auto_merge', 'decide', 'judged', 'main', 'merge', 'merge_message',
    'message_wait', 'ready',
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


#: The shipped script judging commit messages over a range; the repo's pre-push row running it is the declaration.
_MESSAGE_SCRIPT: Final = 'cz-push-range'


def message_wait(root: Path, base: str, head: str) -> str | None:
    """Why *head*'s commits over *base* fail the repo's declared message row, or ``None`` (passed, or none declared).

    The SAME script and env the pre-push row runs, handed git's pre-push line for ``<base sha>..<head>``.
    """
    row = next((one for one in hook_table(root).get('pre-push', ()) if _MESSAGE_SCRIPT in one.run), None)
    if row is None:
        return None
    base_sha = _door.run(['git', 'rev-parse', base], cwd=str(root), capture_output=True, text=True, check=True)
    line = f'refs/heads/pr {head} refs/heads/pr {base_sha.stdout.strip()}\n'
    done = _door.run(
        [bash_executable(), hook_path(_MESSAGE_SCRIPT).as_posix()],
        cwd=str(root),
        input=line,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=False,
        env={**os.environ, PYTHON_ENV: sys.executable, **row.env},
    )
    if done.returncode == 0:
        return None
    said = [one for one in (done.stdout + done.stderr).splitlines() if one.strip()]
    return f'{row.id} refuses a message over {base}..{head[:12]}: {said[-1] if said else done.returncode}'


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
        f'chore(merge): {branch} into {policy.integration} (#{number})\n\n'
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
    github: bool,
) -> Decision:
    """What PR *number* (*branch* at *head*) lacks to be merged into ``origin/<integration>``; writes nothing."""
    into = policy.integration
    base = f'refs/remotes/origin/{into}'
    message = merge_message(branch, number, policy)
    missing: list[str] = []
    try:  # a review config that cannot review is named here, never silently mergeable
        load_review(root)
    except ValueError as config:
        missing.append(f'its review config: {config}')
    if (unreviewed := review_missing(statuses, forge_creators(github=github))) is not None:
        missing.append(f'its review: {unreviewed}')
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
    if (off := message_wait(root, base, head)) is not None:
        missing.append(f'conventional commit messages: {off}')
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
    """:func:`decide` on PR *number*'s *head* as the forge holds it now: its statuses."""
    statuses = [one for one in status_list(client, head) if one.context != MERGE_READY_CONTEXT]
    return decide(root, policy, branch=branch, number=number, head=head, statuses=statuses,
                  github=client.backend is GITHUB)  # fmt: skip


def ready(root: Path, client: Client, number: int) -> str:
    """Post PR *number*'s :func:`judged` decision as ONE :data:`MERGE_READY_CONTEXT` status on its head; the line.

    ``success`` when nothing is missing, else ``failure`` naming what is (cut to the forge's description limit; the
    workflow log carries the whole line). A PR into another branch than the PR base is ``failure`` saying so.
    """
    policy, pull = load_policy(root), client.pr_view(number)
    if pull.base != policy.integration:
        missing: tuple[str, ...] = (f'a PR into {policy.integration}, not {pull.base}',)
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
