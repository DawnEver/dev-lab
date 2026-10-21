"""INTEGRATION-TAKES-ONLY-FORGE-MERGES: the forge merges a green pull request into integration, server side.

User ruling 2026-10-19: every change is a short-lived branch returning by a PR to the integration branch,
which takes ONLY server-side merges of PRs whose every forge part passed. Opted into by declaring
``[tool.lab_commons.integrator] pr_merges_since = "<sha>"``; from then on the integration tick
(:func:`lab_commons.dev.forgeintegration.tick`) asks :func:`decide` of each open PR into integration and,
when nothing is missing, asks the forge to merge it (:func:`merge`). A client push adding a commit to the
branch is refused at pre-push (:mod:`lab_commons.dev.sessionbranch`, P5).

A PR IS MERGED WHEN, and only when, read from the object store and the forge:

* every ``tests/<part>`` part of its head stands PASS (:func:`lab_commons.dev.integrator.lane_ready`, the one
  ready predicate);
* its head merges into ``origin/<integration>`` with no conflict (it contains integration, or the
  three-way merge is clean -- :func:`lab_commons.dev.trialmerge.trial`);
* the merge commit the forge will write passes the merge audit
  (:func:`lab_commons.dev.mergeaudit.judge`, the same judgement the commit-msg hook makes) -- its message
  names the branch (``Merged-Branch:``), so INTEGRATION-IS-MERGES-ONLY holds of it too.

Otherwise the PR stays open and the missing conditions are said in its one integration comment. The merge
is a MERGE COMMIT (``Do: merge``, never squash or rebase), pinned to the judged head (``head_commit_id``: a
head that moved since is refused by the forge, and judged afresh next tick). A head in a declared ephemeral
namespace is deleted by the forge with the merge.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from lab_commons.dev.forgework import GITEA
from lab_commons.dev.integrator import lane_ready
from lab_commons.dev.mergeaudit import MergeAuditError, judge
from lab_commons.dev.platformparts import standing
from lab_commons.dev.sessionbranch import MERGED_BRANCH
from lab_commons.dev.trialmerge import trial

if TYPE_CHECKING:
    from pathlib import Path

    from lab_commons.dev.forgestatus import CommitStatus
    from lab_commons.dev.forgework import Client
    from lab_commons.dev.lanepolicy import Policy

__all__ = ['FORGE_PULL', 'Decision', 'decide', 'merge', 'merge_message']

#: The trailer naming the pull request a forge merge closed.
FORGE_PULL: Final = 'Forge-Pull'


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
    root: Path, policy: Policy, *, branch: str, number: int, head: str, statuses: Sequence[CommitStatus]
) -> Decision:
    """What PR *number* (*branch* at *head*) lacks to be merged into ``origin/<integration>``; writes nothing."""
    base = f'refs/remotes/origin/{policy.integration}'
    message = merge_message(branch, number, policy)
    missing: list[str] = []
    if not lane_ready(statuses, head=head):
        reading = standing(statuses, head=head).reading
        missing.append(f'every `tests/<part>` part PASS on {head[:12]} (it stands {reading})')
    tried = trial(root, base, head)
    if not tried.clean:
        files = ', '.join(f'`{name}`' for name in tried.conflicts)
        missing.append(
            f'a clean merge: it conflicts with `{policy.integration}` in {files} -- merge `{policy.integration}` '
            f'into the branch (python -m lab_commons.dev.forge sync) and push it'
        )
    else:
        try:
            problems = judge(root, [base, head], tried.tree, message, roots=policy.test_roots, label=f'#{number}')
        except MergeAuditError as error:
            problems = (str(error),)
        missing += [f'a merge the audit passes: {problem}' for problem in problems]
    return Decision(tuple(missing), message)


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
