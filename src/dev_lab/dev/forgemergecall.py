"""The forge's merge calls: merge one judged PR head, or have the forge merge it once its decision is green.

Split out of :mod:`dev_lab.dev.forgemerge` (the merge DECISION): these WRITE to the forge, on either backend.
The merge is a MERGE COMMIT (never squash or rebase: the merge audit reads merge commits), pinned to the judged head.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dev_lab.dev import forgepr, forgestatus, sessionprs
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgework import GITHUB
from dev_lab.dev.prcurrent import HOOK_ID, RULE, SYNC

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = ['MERGE_REFUSALS', 'MergeRefused', 'auto_merge', 'merge']

#: GitHub's answer to deleting a ref that is already gone (a repo that auto-deletes head branches on merge).
_REF_GONE: Final = 'Reference does not exist'
_NOT_FOUND: Final = 404
_UNPROCESSABLE: Final = 422
#: The statuses a forge refuses a MERGE with for a cause the PR carries (a conflict, an unmet check, a moved head):
#: Gitea 405 (a conflict reads "Please try again later"), GitHub 405 "not mergeable" and 409 "Head branch was modified".
MERGE_REFUSALS: Final = frozenset({405, 409, _UNPROCESSABLE})
#: GitHub's ``mergeable_state`` of a PR that conflicts with its base.
_DIRTY: Final = 'dirty'
_RED: Final = frozenset({'failure', 'error'})


class MergeRefused(ForgeCallFailed):
    """The forge refused a merge; its message is the cause the PR carries and its door, its report the call's.

    A :class:`ForgeCallFailed`, so every door already catching a failed merge says this line, never a traceback.
    """

    def __init__(self, said: str, refused: ForgeCallFailed) -> None:
        """Carry *refused*'s report, said as *said*."""
        super().__init__(refused.report)
        self.args = (said,)


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


def merge(client: Client, number: int, *, head: str, message: str, delete_branch: bool, force: bool = False) -> None:
    """Ask the forge to merge PR *number* at *head* with a merge commit saying *message*.

    *force* is break-glass's alone (:meth:`dev_lab.ops.breakglassforge.ClientForge.merge`): the merge is asked to
    OVERRIDE the branch's unmet required checks. Gitea overrides them only when the request says so
    (``force_merge``) AND its login is one the protection admits -- a repository admin, or its bypass allowlist
    (:mod:`dev_lab.dev._protect_gitea`); unasked, it refuses a merge whose required check is pending or red even
    from that login (measured 2026-11-22 on a repo whose one branch requires its check workflow). GitHub has no
    such flag: the ruleset's bypass actor merges past it as itself. Every other door leaves it ``False``.

    Both forges refuse a *head* that is no longer the PR's (Gitea ``head_commit_id``, GitHub ``sha``). On GitHub,
    which deletes no branch with a merge, *delete_branch* deletes the PR's head branch after it: a branch already gone
    (404, or 422 "Reference does not exist" -- the repo auto-deletes head branches; DawnEver/cc-market #12,
    2026-11-13) is the delete done, any other refusal raises. The merged PR ends in every session record holding it
    (:func:`dev_lab.dev.sessionprs.ended`) before that delete is asked.

    Before GitHub deletes the head, every open PR STACKED on it (its base) is retargeted to the merged PR's base
    with one comment saying why (:func:`dev_lab.dev.forgepr.retarget_children`): GitHub CLOSES a PR whose base
    branch is deleted, and a closed PR whose base is gone cannot be reopened (dev-lab #1003, document-lab #67).
    Gitea retargets the children itself when its merge deletes the head (``RETARGET_CHILDREN_ON_MERGE``, on by
    default since Gitea 1.20).

    A forge's refusal of the merge itself (:data:`MERGE_REFUSALS`) raises :class:`MergeRefused` naming its cause and
    door (:func:`_why`): a conflict with the base, a head that is not current, else the forge's own text.
    """
    try:
        _merge(client, number, head=head, message=message, delete_branch=delete_branch, force=force)
    except ForgeCallFailed as refused:
        if refused.final not in MERGE_REFUSALS:
            raise
        raise MergeRefused(_why(client, number, head, refused), refused) from refused


def _why(client: Client, number: int, head: str, refused: ForgeCallFailed) -> str:
    """Why the forge refused merging PR *number*, read off the PR: a conflict, a stale head, else the forge's text.

    A conflict is Gitea ``mergeable: false`` or GitHub ``mergeable_state: dirty``; a stale head is a red
    PR-HEAD-IS-CURRENT status (``pr-current``) on *head*. A read failing here leaves the forge's own text.
    """
    name = f'{client.forge.owner}/{client.forge.repo}#{number}'
    try:
        pull = client.call('GET', f'{client.repo}/pulls/{number}')
        base, branch = pull['base']['ref'], pull['head']['ref']
        if pull.get('mergeable_state') == _DIRTY or (client.backend is not GITHUB and pull.get('mergeable') is False):
            return (
                f'{name} conflicts with {base}: merge {base} into {branch} -- {SYNC}, resolve, push '
                f'(the forge answered: {refused})'
            )
        stale = [one for one in forgestatus.status_list(client, head) if one.context == HOOK_ID and one.state in _RED]
    except (ForgeCallFailed, KeyError, TypeError) as unread:
        return f'{name}: the forge refused the merge: {refused} (its cause could not be read: {unread})'
    if stale:
        why = stale[0].description
        return f'{name}: its head is not current ({RULE}): {why} -- {SYNC}, push (the forge answered: {refused})'
    return f'{name}: the forge refused the merge: {refused}'


def _merge(client: Client, number: int, *, head: str, message: str, delete_branch: bool, force: bool) -> None:
    title, _, body = message.partition('\n\n')
    if client.backend is GITHUB:
        client.call(
            'PUT',
            f'{client.repo}/pulls/{number}/merge',
            {'commit_title': title, 'commit_message': body, 'sha': head, 'merge_method': 'merge'},
        )
        sessionprs.ended(client.forge, number)
        if delete_branch:
            landed = client.pr_view(number)
            forgepr.retarget_children(client, landed.head, onto=landed.base, landed=number)
            _delete_head(client, landed.head)
        return
    asked = {
        'Do': 'merge',
        'MergeTitleField': title,
        'MergeMessageField': body,
        'head_commit_id': head,
        'delete_branch_after_merge': delete_branch,
    }
    client.call('POST', f'{client.repo}/pulls/{number}/merge', asked | ({'force_merge': True} if force else {}))
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
