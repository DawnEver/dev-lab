"""The forge's merge calls: merge one judged PR head, or have the forge merge it once its decision is green.

Split out of :mod:`dev_lab.dev.forgemerge` (the merge DECISION): these WRITE to the forge, on either backend.
The merge is a MERGE COMMIT (never squash or rebase: the merge audit reads merge commits), pinned to the judged head.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dev_lab.dev.forgework import GITHUB

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = ['auto_merge', 'merge']

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
