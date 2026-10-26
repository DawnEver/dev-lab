"""INTEGRATION-TAKES-ONLY-FORGE-MERGES: the forge merges a green pull request into integration, server side.

User ruling 2026-10-19: every change is a short-lived branch returning by a PR to the integration branch,
which takes ONLY server-side merges of PRs whose every forge part passed. Opted into by declaring
``[tool.lab_commons.integrator] pr_merges_since = "<sha>"``; from then on the integration tick
(:func:`dev_lab.dev.forgeintegration.tick`) asks :func:`decide` of each open PR into integration and,
when nothing is missing, asks the forge to merge it (:func:`merge`). A client push adding a commit to the
branch is refused at pre-push (:mod:`dev_lab.dev.sessionbranch`, P5).

A PR IS MERGED WHEN, and only when, read from the object store and the forge:

* every ``tests/<part>`` part of its head stands PASS (:func:`dev_lab.dev.platformparts.standing`), except a
  scarce part its diff does not reach -- WAIVED, run on integration after the merge
  (:mod:`dev_lab.dev.forgescarce`, user ruling 2026-10-22);
* its review is not HELD: a pending ``tests/review-hold`` waits until the integrator's takeover review releases it
  (``forge review takeover <sha>``, :mod:`dev_lab.dev.forgetakeover`; :func:`review_hold`); every other review
  state stays advisory;
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

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from lab_commons.outcomes import Conclusion

from dev_lab.dev.forgework import GITEA
from dev_lab.dev.mergeaudit import MergeAuditError, judge
from dev_lab.dev.mergeresolution import unresolved
from dev_lab.dev.platformparts import HOLD_CONTEXT, standing
from dev_lab.dev.sessionbranch import MERGED_BRANCH
from dev_lab.dev.trialmerge import trial

if TYPE_CHECKING:
    from pathlib import Path

    from dev_lab.dev.forgestatus import CommitStatus
    from dev_lab.dev.forgework import Client
    from dev_lab.dev.lanepolicy import Policy

__all__ = ['FORGE_PULL', 'Decision', 'decide', 'merge', 'merge_message', 'review_hold']

#: The trailer naming the pull request a forge merge closed.
FORGE_PULL: Final = 'Forge-Pull'


def review_hold(statuses: Sequence[CommitStatus]) -> str | None:
    """Why a merge of the commit waits on its review, or ``None``: a latest :data:`HOLD_CONTEXT` not yet released."""
    latest = next((one for one in statuses if one.context == HOLD_CONTEXT), None)
    if latest is None or latest.state == 'success':
        return None
    return f'{HOLD_CONTEXT} is {latest.state}: {latest.description}'


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
    waived: frozenset[str] = frozenset(),
) -> Decision:
    """What PR *number* (*branch* at *head*) lacks to be merged into ``origin/<integration>``; writes nothing.

    *waived* are the scarce parts its diff does not reach (:func:`dev_lab.dev.forgescarce.unreached`).
    """
    base = f'refs/remotes/origin/{policy.integration}'
    message = merge_message(branch, number, policy)
    missing: list[str] = []
    stood = standing(statuses, head=head, waived=waived)
    if stood.result is not Conclusion.PASS:
        but = f' but the unreached scarce {", ".join(sorted(waived))}' if waived else ''
        missing.append(f'every `tests/<part>` part{but} PASS on {head[:12]} (it stands {stood.reading})')
    if (held := review_hold(statuses)) is not None:
        missing.append(f'its review: {held}')
    tried = trial(root, base, head)
    if not tried.clean:
        files = ', '.join(f'`{name}`' for name in tried.conflicts)
        missing.append(
            f'a clean merge: it conflicts with `{policy.integration}` in {files} -- merge `{policy.integration}` '
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
