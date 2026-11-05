"""INTEGRATION-TAKES-ONLY-FORGE-MERGES: the forge merges a reviewed, safe, clean PR into integration, server side.

User ruling 2026-10-19: every change is a short-lived branch returning by a PR to the integration branch,
which takes ONLY server-side merges. THE TEST PARTS GATE THAT MERGE (user ruling 2026-11-04, superseding
2026-10-29's "parts never gate", after dev-lab#78 merged with ``tests/base`` FAILED and reddened integration): every
part the head needs stands PASS (:func:`dev_lab.dev.platformparts.standing`, the reading promotion uses at scope full
in :func:`dev_lab.dev.integrate.promote`); absent or pending waits, FAIL refuses. Opted into by declaring
``[tool.dev_lab.integrator] pr_merges_since = "<sha>"``; from then on the integration tick
(:func:`dev_lab.dev.forgeintegration.tick`) asks :func:`decide` of each open PR into integration and,
when nothing is missing, asks the forge to merge it (:func:`merge`). A client push adding a commit to the
branch is refused at pre-push (:mod:`dev_lab.dev.sessionbranch`, P5).

ONE DECISION ON BOTH FORGES (user ruling 2026-10-29); only who MERGES differs. :func:`judged` reads a PR's head and
decides; a workflow job runs ``forge merge ready [--pr <N>]`` (:func:`ready`; no number: every open PR into
integration), which posts the decision as ONE status, :data:`~dev_lab.dev.forgecontexts.MERGE_READY_CONTEXT`,
and on ``success`` asks the forge to merge that head itself (:func:`merge`, as the job's own token). That job
merges on GitHub always, and on Gitea where the repo declares the CI merger (:data:`CI_MERGER`, :func:`ci_merges`;
P3, user ruling 2026-11-02): Gitea's ``merge.yml`` runs it on the light runner, and the serve tick then only says
the decision. A Gitea repo that does not declare it is still merged by the serve tick on the same :func:`judged`.
GitHub still enforces the branch's required checks on that merge; one still pending refuses it, and the native
auto-merge ``forge pr create`` enabled merges once they are green. GitHub refuses to enable auto-merge on a PR
that is already mergeable (dev-lab#15), which is why the job that posts ready merges rather than waiting on it.
The PR base is :attr:`~dev_lab.dev.lanepolicy.Policy.integration`.

A PR IS MERGED WHEN, and only when, read from the object store and the forge:

* its head's test parts all stand PASS (:func:`parts_wait`);
* its head is REVIEWED (:func:`dev_lab.dev.forgereview_gate.review_gate`, user ruling 2026-10-31): the
  latest ``tests/review`` is a ``success`` the FORGE posted (its recorded creator, D11) and no ``tests/review-hold``
  is pending -- or, where the base declares ``where = "judge"``, the declared judge login's latest verdict review
  at the head is APPROVED. Absent, reviewing, ``error``, ``failure`` and a success any other login posted all
  wait -- nothing is advisory; a review that cannot run is re-run by the forge. ONE WAIVER (user ruling 2026-11-05):
  a review that reached a cap (:func:`dev_lab.dev.reviewcap.capped_waiver`, read from trusted comments) no
  longer blocks -- the merge proceeds WARNED, its commit message and decision carrying ``Unreviewed: ...``;
* it is an INTERNAL PR (:func:`external`, user ruling 2026-11-05): a fork's, or a non-writer's, is never merged by
  the forge -- ``tests/merge-ready`` stays ``pending`` :data:`EXTERNAL`;
* its head's ``tests/security`` stands ``success`` (:mod:`dev_lab.dev.forgesecurity`): ``failure`` names the
  findings, ``error`` is a scan that gave no answer, and both wait;
* its head merges into ``origin/<integration>`` with no conflict (it contains integration, or the
  three-way merge is clean -- :func:`dev_lab.dev.trialmerge.trial`);
* the merge commit the forge will write passes the merge audit
  (:func:`dev_lab.dev.mergeaudit.judge`, the same judgement the commit-msg hook makes) -- its message
  names the branch (``Merged-Branch:``), so INTEGRATION-IS-MERGES-ONLY holds of it too;
* every commit its head adds over integration passes the repo's OWN declared message row -- the pre-push row
  running ``cz-push-range``, run here on the range ``origin/<integration>..<head>`` with that row's env in its
  ``--merge-decision`` mode -- commits the base already holds are history, the PR's own are all judged, none
  exempt (:func:`message_wait`). A worktree with no venv skips that row at commit and push, so the
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
import subprocess
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.log import emit
from lab_commons.outcomes import Conclusion

from dev_lab.dev.branchset import declared_branchset
from dev_lab.dev.family import declared_table
from dev_lab.dev.forgecontexts import MERGE_READY_CONTEXT
from dev_lab.dev.forgedraft import WAITING, waiting
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgepulls import ListingIncomplete, pr_list
from dev_lab.dev.forgereview_declared import load_review
from dev_lab.dev.forgereview_gate import review_gate
from dev_lab.dev.forgesecurity import security_wait
from dev_lab.dev.forgestatus import status_list, status_post
from dev_lab.dev.forgework import GITHUB, client_for
from dev_lab.dev.githooks import PYTHON_ENV, bash_executable, hook_path
from dev_lab.dev.githooks.table import hook_table
from dev_lab.dev.jobparts import pull_request_waived
from dev_lab.dev.lanepolicy import load_policy
from dev_lab.dev.mergeaudit import MergeAuditError, judge
from dev_lab.dev.mergeresolution import unresolved
from dev_lab.dev.platformparts import standing
from dev_lab.dev.reviewcap import capped_waiver
from dev_lab.dev.sessionbranch import MERGED_BRANCH
from dev_lab.dev.trialmerge import trial
from dev_lab.dev.unproduced import unproduced_waived

if TYPE_CHECKING:
    from dev_lab.dev.forgestatus import CommitStatus
    from dev_lab.dev.forgework import Client, PullRequest
    from dev_lab.dev.lanepolicy import Policy
    from dev_lab.dev.reviewgate import Reviewed

__all__ = [
    'CI_MERGER',
    'EXTERNAL',
    'FORGE_PULL',
    'READY',
    'Decision',
    'auto_merge',
    'ci_merges',
    'decide',
    'external',
    'judged',
    'main',
    'merge',
    'merge_message',
    'message_wait',
    'ready',
]  # fmt: skip

#: The merge decision's ``pending`` line for a PR the forge never merges (:func:`external`).
EXTERNAL: Final = 'external PR: a maintainer merges it'

#: The Gitea workflow that merges, closes landed PRs and sweeps (``ci_base.toml``); declaring it is the opt-in.
CI_MERGER: Final = 'merge.yml'


def ci_merges(root: Path) -> bool:
    """Whether *root* declares ``[tool.dev_lab.ci."merge.yml"]``: then serve neither merges, closes nor sweeps."""
    pyproject = root / 'pyproject.toml'
    data = tomllib.loads(pyproject.read_text(encoding='utf-8')) if pyproject.is_file() else {}
    return CI_MERGER in declared_table(data, 'ci', {})


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
    base_sha = _door.run(
        ['git', 'rev-parse', base], cwd=str(root), capture_output=True, text=True, encoding='utf-8', check=True
    )
    line = f'refs/heads/pr {head} refs/heads/pr {base_sha.stdout.strip()}\n'
    done = _door.run(
        [bash_executable(), hook_path(_MESSAGE_SCRIPT).as_posix(), '--merge-decision'],
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
    unreviewed: str = ''  # the capped-review warning (:mod:`dev_lab.dev.reviewcap`) when the review was waived

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


def parts_wait(root: Path, head: str, statuses: Sequence[CommitStatus]) -> str | None:
    """Why *head*'s test parts do not all stand PASS, or ``None``: the one :func:`standing` reading, any scope.

    An unproduced part and a hosted one (produced only on a full run, never for a pull request) are waived.
    """
    waived = unproduced_waived(root, head, statuses) | pull_request_waived(root, head)
    parts = standing(statuses, head=head, waived=waived)
    if parts.result is Conclusion.PASS:
        return None
    return '; '.join([f'they stand {parts.reading}', *parts.problems])


def decide(
    root: Path,
    policy: Policy,
    *,
    branch: str,
    number: int,
    head: str,
    statuses: Sequence[CommitStatus],
    reviewed: Reviewed,
    capped: str | None = None,
) -> Decision:
    """What PR *number* (*branch* at *head*) lacks to be merged into ``origin/<integration>``; writes nothing.

    *capped* (:func:`dev_lab.dev.reviewcap.capped_waiver`) waives the review condition alone, and the message and
    the decision carry it.
    """
    into = policy.integration
    base = f'refs/remotes/origin/{into}'
    message = merge_message(branch, number, policy)
    missing: list[str] = []
    try:  # a review config that cannot review is named here, never silently mergeable
        load_review(root)
    except ValueError as config:
        missing.append(f'its review config: {config}')
    waived = ''
    if (unreviewed := reviewed(statuses)) is not None:
        if capped:
            waived = capped
            title, _, trailers = message.partition('\n\n')
            message = f'{title}\n\n{capped}\n\n{trailers}'
        else:
            missing.append(f'its review: {unreviewed}')
    if (unsafe := security_wait(statuses)) is not None:
        missing.append(f'its security check: {unsafe}')
    if (red := parts_wait(root, head, statuses)) is not None:
        missing.append(f'its test parts: {red}')
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
    return Decision(tuple(missing), message, waived)


def external(client: Client, pull: PullRequest) -> bool:
    """Whether *pull* is an EXTERNAL contributor's, which the forge never merges (user ruling 2026-11-05).

    External is a fork's head, or an author the forge does not record with write permission
    (:meth:`~dev_lab.dev.forgework.Client.can_write` -- the one trust test a cap raise passes,
    :func:`~dev_lab.dev.forgereview_rounds.trusted_bodies`). It is still tested and reviewed; a human merges it.
    """
    return pull.fork or not client.can_write(pull.author)


def judged(root: Path, client: Client, policy: Policy, *, branch: str, number: int, head: str) -> Decision:
    """:func:`decide` on PR *number*'s *head* as the forge holds it now: its statuses."""
    statuses = [one for one in status_list(client, head) if one.context != MERGE_READY_CONTEXT]
    try:
        reviewed = review_gate(client, head, base=policy.integration)
    except ValueError as config:  # a declaration that cannot gate is this PR's wait, never the tick's crash

        def reviewed(_statuses: Sequence[CommitStatus], why: str = str(config)) -> str:
            return f'the review gate cannot be read: {why}'

    capped = capped_waiver(client, number, base=policy.integration)
    found = decide(
        root, policy, branch=branch, number=number, head=head, statuses=statuses, reviewed=reviewed, capped=capped
    )
    pull, missing = client.pr_view(number), found.missing
    if external(client, pull):  # INTERNAL-ONLY (2026-11-05): never merged by the forge, whatever else is green
        missing = (EXTERNAL, *missing)
    if pull.draft:  # DRAFT-UNTIL-READY (D53): a draft never lands, whatever else is green
        missing = (WAITING.format(n=number), *missing)
    return Decision(missing, found.message, found.unreviewed)


def ready(root: Path, client: Client, number: int) -> str:
    """Post PR *number*'s :func:`judged` decision as ONE :data:`MERGE_READY_CONTEXT` status on its head; the line.

    ``success`` when nothing is missing, else ``failure`` naming what is (cut to the forge's description limit; the
    workflow log carries the whole line). A PR into another branch than the PR base is ``failure`` saying so.
    On GitHub, or where the repo :func:`ci_merges`, a ``success`` is followed by the merge of that judged head
    (:func:`merge`); a refusal -- the head
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
    state, why = ('failure', 'waits on: ' + '; '.join(missing)) if missing else ('success', READY)
    if decision.unreviewed and not missing:
        why = f'{READY}, WARNED -- {decision.unreviewed}'
    status_post(client, pull.head_sha, context=MERGE_READY_CONTEXT, state=state, description=why)
    said = f'#{number} {pull.head_sha[:12]} {MERGE_READY_CONTEXT} {state}: {why}'
    if missing or (client.backend is not GITHUB and not ci_merges(root)):
        return said
    ephemeral = declared_branchset(root).is_ephemeral(pull.head)
    try:
        merge(client, number, head=pull.head_sha, message=decision.message, delete_branch=ephemeral)
    except ForgeCallFailed as refused:
        return f'{said}; NOT merged -- {refused}'
    if decision.unreviewed:
        client.issue_comment(number, f'Merged WITHOUT a passing review -- {decision.unreviewed}')
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


def auto_merge(client: Client, number: int) -> str:
    """Have PR *number* merged once its merge decision is green; the line said. Who MERGES is the forge's.

    Gitea: nothing to ask -- the serve tick merges on the decision (:func:`judged`). GitHub: its native auto-merge,
    a merge commit, which waits on the branch's required checks (:data:`MERGE_READY_CONTEXT` among them). A refusal
    GitHub answers (auto-merge off for the repository, a PR already mergeable) is said, never raised: the job that
    posts the decision merges a ready PR itself (:func:`ready`).
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

    Both forges refuse a *head* that is no longer the PR's (Gitea ``head_commit_id``, GitHub ``sha``). On GitHub,
    which deletes no branch with a merge, *delete_branch* deletes the PR's head branch after it.
    """
    title, _, body = message.partition('\n\n')
    if client.backend is GITHUB:
        client.call(
            'PUT',
            f'{client.repo}/pulls/{number}/merge',
            {'commit_title': title, 'commit_message': body, 'sha': head, 'merge_method': 'merge'},
        )
        if delete_branch:
            client.call('DELETE', f'{client.repo}/git/refs/heads/{client.pr_view(number).head}')
        return
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
