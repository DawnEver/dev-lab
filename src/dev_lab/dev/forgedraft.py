"""DRAFT-UNTIL-READY (D53, user ruling 2026-11-01): a PR opens as a draft, and only a ready PR is reviewed or merged.

A review round is spent only on new work (D52): an author mid-task pushes many heads, and each one reviewed was a
round and a budget spent on work its author had not finished. So the DOOR opens a draft -- ``forge pr create``
unless it is given ``--ready`` -- and the author marks it ready when its own work is done. One mechanism per forge,
behind the client:

* GitHub: ``draft: true`` on create; GraphQL ``markPullRequestReadyForReview`` / ``convertPullRequestToDraft``.
* Gitea (1.27 has no draft field on create or edit): the title prefix it reads as work in progress,
  :data:`~dev_lab.dev._forge_records.DRAFT_PREFIX` -- the same ``WIP:``
  :func:`~dev_lab.dev._forge_records.pull_of` reads back as ``draft``.

Only a ready PR is reviewed (:mod:`dev_lab.dev.forgereview`, both the serve tick and the review job) or merged
(:func:`dev_lab.dev.forgemerge.judged` names :data:`WAITING`). Marking ready is a review trigger
(``ready_for_review`` in the workflows' types; the serve's next tick). A push after ready keeps the PR ready: a fix
push gets its round, and the serve's debounce (``quiet``) coalesces a burst of them.

A DRAFT NEVER STALLS SILENTLY -- a session that has not read this rule would not know to mark it ready:

* ``forge pr create`` prints the exact next step on stdout (:func:`opened_line`);
* a draft head carries ``tests/merge-ready`` ``pending`` naming the ready door (:func:`waiting`);
* a draft whose head is older than :data:`STALE_DRAFT` raises ONE ``integration`` alarm (:func:`alarms`, raised by
  the serve's integration step through :func:`dev_lab.dev.forgeservesteps.raise_once`, which keeps one issue per
  alarm, so it pages once), naming the PR, its author and session and the ready door; marking ready closes it.

``python -m dev_lab.dev.forge pr ready <N>`` / ``pr draft <N>`` (:func:`main`) move a PR between the two.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons.log import emit

from dev_lab.dev._forge_records import draft_title, ready_title
from dev_lab.dev.forgealarm import INTEGRATION, Alarm
from dev_lab.dev.forgecontexts import MERGE_READY_CONTEXT
from dev_lab.dev.forgepulls import pr_list
from dev_lab.dev.forgestatus import status_list, status_post
from dev_lab.dev.forgework import GITHUB, ForgeCallFailed, client_for
from dev_lab.dev.labsession import sessions

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client, PullRequest

__all__ = [
    'READY_DOOR', 'STALE_DRAFT', 'WAITING', 'alarms', 'main', 'mark_draft', 'mark_ready', 'opened_line', 'waiting',
]  # fmt: skip

#: The door that marks PR ``{n}`` ready.
READY_DOOR: Final = 'python -m dev_lab.dev.forge pr ready {n}'

#: What a draft head's ``tests/merge-ready`` says (``pending``), and what the merge decision names as missing.
WAITING: Final = 'draft: mark ready with `' + READY_DOOR + '` -- nothing reviews or merges a draft'

#: How long a draft's head may go without a push before the integrator is told it waits on its author.
STALE_DRAFT: Final = timedelta(hours=24)

_READY: Final = 'mutation($id: ID!) { markPullRequestReadyForReview(input: {pullRequestId: $id}) { clientMutationId } }'
_DRAFT: Final = 'mutation($id: ID!) { convertPullRequestToDraft(input: {pullRequestId: $id}) { clientMutationId } }'


def opened_line(pull: PullRequest) -> str:
    """The line ``forge pr create`` prints on stdout: what the PR is, and for a draft the exact next step."""
    if not pull.draft:
        return f'opened #{pull.number} ready for review'
    door = READY_DOOR.format(n=pull.number)
    return f'opened #{pull.number} as a DRAFT: nothing reviews or merges it until `{door}`'


def _graphql(client: Client, number: int, mutation: str) -> None:
    node = client.call('GET', f'{client.repo}/pulls/{number}')['node_id']
    answer = client.call('POST', '/graphql', {'query': mutation, 'variables': {'id': node}})
    if errors := (answer or {}).get('errors'):
        msg = f'#{number}: {errors[0].get("message", errors[0])}'
        raise ValueError(msg)


def mark_ready(client: Client, number: int) -> PullRequest:
    """Mark PR *number* ready for review: its review and merge may proceed. The PR as the forge holds it now."""
    if client.backend is GITHUB:
        _graphql(client, number, _READY)
    else:
        title = client.pr_view(number).title
        client.call('PATCH', f'{client.repo}/pulls/{number}', {'title': ready_title(title)})
    return client.pr_view(number)


def mark_draft(client: Client, number: int) -> PullRequest:
    """Move PR *number* back to draft: nothing reviews or merges it until it is marked ready again."""
    if client.backend is GITHUB:
        _graphql(client, number, _DRAFT)
    else:
        title = client.pr_view(number).title
        client.call('PATCH', f'{client.repo}/pulls/{number}', {'title': draft_title(title)})
    return client.pr_view(number)


def waiting(client: Client, pull: PullRequest) -> str | None:
    """Post :data:`WAITING` (``pending``) as *pull*'s draft head's ``tests/merge-ready``, once; the line or ``None``."""
    said = WAITING.format(n=pull.number)
    latest = next((one for one in status_list(client, pull.head_sha) if one.context == MERGE_READY_CONTEXT), None)
    if latest is not None and latest.state == 'pending' and latest.description and said.startswith(latest.description):
        return None
    status_post(client, pull.head_sha, context=MERGE_READY_CONTEXT, state='pending', description=said)
    return f'#{pull.number} {pull.head_sha[:12]}: {said}'


def _pushed(client: Client, sha: str) -> datetime:
    """When *sha* was committed, as the forge records it (its committer date: the closest the forge has to a push)."""
    path = f'{client.repo}/commits/{sha}' if client.backend is GITHUB else f'{client.repo}/git/commits/{sha}'
    return datetime.fromisoformat(client.call('GET', path)['commit']['committer']['date'])


def alarms(root: Path, client: Client, base: str, repo: str, *, now: datetime) -> list[Alarm]:
    """One ``integration`` alarm per open draft into *base* whose head is older than :data:`STALE_DRAFT`.

    Keyed by the head sha: :func:`~dev_lab.dev.forgeservesteps.raise_once` keeps one issue for it and pages once,
    and closes it once the PR is ready, pushed again or gone. Every draft head also gets :func:`waiting`.
    """
    out = []
    for pull in pr_list(client):
        if pull.base != base or not pull.draft or not pull.head_sha:
            continue
        waiting(client, pull)
        if now - _pushed(client, pull.head_sha) < STALE_DRAFT:
            continue
        who = ', '.join(sorted(sessions(root, f'origin/{base}', pull.head_sha))) or 'no Lab-Session trailer'
        door = READY_DOOR.format(n=pull.number)
        out.append(Alarm(
            INTEGRATION, repo, f'draft #{pull.number} idle {pull.head_sha[:12]}',
            f'#{pull.number} ({pull.title}) by {pull.author} [{who}] is a draft with no push for {STALE_DRAFT}: '
            f'nothing reviews or merges it. If its work is done, its author runs `{door}`; else it waits on them.',
        ))  # fmt: skip
    return out


def main(argv: Sequence[str], *, cwd: Path | None = None, client: Client | None = None) -> int:
    """``forge pr ready <N>`` / ``forge pr draft <N>``: exit 0 moved, 1 the forge refused."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge pr', description=__doc__.splitlines()[0])
    parser.add_argument('verb', choices=('ready', 'draft'))
    parser.add_argument('number', type=int)
    args = parser.parse_args(list(argv))
    client = client or client_for(Path.cwd() if cwd is None else cwd)
    try:
        pull = (mark_ready if args.verb == 'ready' else mark_draft)(client, args.number)
    except (ForgeCallFailed, ValueError) as refused:
        emit(f'[forge] pr {args.verb} #{args.number} refused: {refused}', err=True)
        return 1
    emit(f'#{pull.number} is {"a DRAFT" if pull.draft else "ready for review"}: {pull.title}')
    return 0
