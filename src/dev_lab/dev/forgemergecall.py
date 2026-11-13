"""The forge's merge calls: merge one judged PR head, or have the forge merge it once its decision is green.

Split out of :mod:`dev_lab.dev.forgemerge` (the merge DECISION): these WRITE to the forge, on either backend.
The merge is a MERGE COMMIT (never squash or rebase: the merge audit reads merge commits), pinned to the judged head.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dev_lab.dev import sessionprs
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgework import GITHUB

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = ['auto_merge', 'merge']

#: GitHub's answer to deleting a ref that is already gone (a repo that auto-deletes head branches on merge).
_REF_GONE: Final = 'Reference does not exist'
_NOT_FOUND: Final = 404
_UNPROCESSABLE: Final = 422

#: GitHub's native auto-merge, as a merge commit (never squash or rebase: the merge audit reads merge commits).
_AUTO_MERGE: Final = (
    'mutation($id: ID!) { enablePullRequestAutoMerge(input: {pullRequestId: $id, mergeMethod: MERGE}) '
    '{ clientMutationId } }'
)


def auto_merge(client: Client, number: int) -> str:
    """Have PR *number* merged once its merge decision is green; the line said. Who MERGES is the forge's.

    Gitea: nothing to ask -- the serve tick merges on the decision (:func:`dev_lab.dev.forgemerge.judged`). GitHub:
    its native auto-merge, a merge commit, which waits on the branch's required checks
    (:data:`~dev_lab.dev.forgecontexts.MERGE_READY_CONTEXT` among them). A refusal GitHub answers (auto-merge off
    for the repository, a PR already mergeable) is said, never raised: the job that posts the decision
    merges a ready PR itself (:func:`dev_lab.dev.forgemergeready.ready`).
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
    which deletes no branch with a merge, *delete_branch* deletes the PR's head branch after it: a branch already gone
    (404, or 422 "Reference does not exist" -- the repo auto-deletes head branches; DawnEver/cc-market #12,
    2026-11-13) is the delete done, any other refusal raises. The merged PR ends in every session record holding it
    (:func:`dev_lab.dev.sessionprs.ended`) before that delete is asked.
    """
    title, _, body = message.partition('\n\n')
    if client.backend is GITHUB:
        client.call(
            'PUT',
            f'{client.repo}/pulls/{number}/merge',
            {'commit_title': title, 'commit_message': body, 'sha': head, 'merge_method': 'merge'},
        )
        sessionprs.ended(client.forge, number)
        if delete_branch:
            _delete_head(client, client.pr_view(number).head)
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
    sessionprs.ended(client.forge, number)


def _delete_head(client: Client, branch: str) -> None:
    """Delete *branch* on GitHub; already gone is deleted, any other refusal raises."""
    try:
        client.call('DELETE', f'{client.repo}/git/refs/heads/{branch}')
    except ForgeCallFailed as refused:
        last = refused.report.attempts[-1] if refused.report.attempts else None
        code = last.returncode if last else 0
        if code != _NOT_FOUND and not (code == _UNPROCESSABLE and _REF_GONE in (last.output if last else '')):
            raise
