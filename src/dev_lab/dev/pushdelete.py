"""LOSSLESS-DELETE at pre-push: every branch a push deletes is judged, however the push was spelled.

MEASURED 2026-11-17: a session assembled its refspecs at run time (``refs=$(printf ':refs/heads/pr/%s ' ...)``,
then ``git push origin $refs``) and deleted nine origin branches holding unlanded commits. The deny row
``PUSH-REMOTE-DELETE`` reads the command's TEXT, so a variable, ``xargs``, ``eval`` or a script passes it; it stays the
early refusal, and text cannot be the guarantee. Git's own pre-push ref lines can: a deletion is a line whose local
sha is all zeros, whatever spelled it.

So the base ``lossless-delete`` row (``githooks/base.toml``) judges each deleted ``refs/heads/`` line with the one
judgement the door makes (:func:`dev_lab.dev.deletejudge.judge`), of the sha the line names as the remote's -- after
``git fetch --prune origin``, so a branch origin no longer holds holds nothing, and against the open PR heads the
forge lists. Branches the same push deletes hold nothing for each other. A refused branch is refused under
:data:`RULE` naming the door, ``branchprune delete <branch>``; that door pushes its delete through this same hook and
passes it with no exemption, an approved tag-held delete handing the user's words on as
:data:`~dev_lab.dev.deletejudge.APPROVED_ENV`.

FAILS CLOSED (:data:`UNJUDGED`): a repo declaring no integration branch, a failed fetch, an unreadable forge or tag
listing refuses naming the cause and the retry, never passes unjudged. A tag deletion is not a branch and is not
judged here (``branchprune delete-tag`` is its door); a deletion of a ref the remote does not hold drops nothing.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.deletejudge import APPROVED_ENV, held_by_tag, judge, remote_tags
from dev_lab.dev.disclosure import details_for
from dev_lab.dev.forge import fetch_origin
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgepulls import ListingIncomplete, pr_list
from dev_lab.dev.forgework import client_for
from dev_lab.dev.lanepolicy import load_policy
from dev_lab.dev.refspec import pushed_refs

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = ['HOOK_ID', 'RULE', 'UNJUDGED', 'main', 'refusals']

#: A deleted branch whose content is held nowhere else, or that is never deleted (integration, trunk, open PR head).
RULE: Final = 'LOSSLESS-DELETE'
#: A delete that could not be judged: no integration branch declared, origin or the forge unreadable.
UNJUDGED: Final = 'LOSSLESS-DELETE-UNJUDGED'
#: The id this guard runs under in ``githooks/base.toml``.
HOOK_ID: Final = 'lossless-delete'

_GIT: Final = shutil.which('git') or 'git'
_ZERO: Final = '0' * 40
_UNREADABLE: Final = (ForgeCallFailed, ListingIncomplete, OSError, ValueError)


def _python() -> str:
    return Path(sys.executable).as_posix()


def _refusal(rule: str, cause: str, door: str) -> str:
    """``<rule>: <cause>``, ``Door: <door>`` on a line of its own, then the ``details:`` pointer."""
    return f'{rule}: {" ".join(cause.split())}\nDoor: {door}\n{details_for(rule)}'


def _door_for(branch: str, *, lost: bool) -> str:
    door = f'{_python()} -m dev_lab.dev.branchprune delete {branch}'
    if lost:
        return f'{door} -- land its commits first, or tag its tip on origin and add --approved "<the user`s words>"'
    return f'{door} -- it fetches afresh and names what holds the branch, or why it stays'


def _retry(what: str) -> str:
    return f'push again once {what} answers ({_python()} -m dev_lab.dev.netverb -- git push ... retries it)'


def refusals(
    root: Path,
    lines: str,
    *,
    client: Callable[[], Client] | None = None,
    fetch: Callable[[Path], None] = fetch_origin,
    approved: str = '',
) -> list[str]:
    """Every refusal for the branch deletions git's pre-push *lines* carry; none when the push deletes no branch.

    *approved* is the user's words a tag-held delete was approved with (:data:`~dev_lab.dev.deletejudge.APPROVED_ENV`).
    """
    gone = {
        ref.branch: ref.remote_sha
        for ref in pushed_refs(lines.splitlines())
        if ref.deleted and ref.branch and ref.remote_sha != _ZERO
    }
    if not gone:
        return []
    named = ', '.join(gone)
    try:
        policy = load_policy(root)
    except (OSError, ValueError) as failed:
        cause = f'{named}: the delete cannot be judged -- this repo {failed}'
        return [_refusal(UNJUDGED, cause, 'declare it as the line above says, then push again')]
    try:
        fetch(root)
    except OSError as failed:
        cause = f'{named}: the fetch of origin failed, so nothing is judged: {failed}'
        return [_refusal(UNJUDGED, cause, _retry('origin'))]
    try:
        heads = {pr.head: pr.number for pr in pr_list(client_for(root) if client is None else client())}
    except _UNREADABLE as failed:
        cause = f'the forge cannot be read ({type(failed).__name__}: {failed}), so whether {named} is an open PR head'
        return [_refusal(UNJUDGED, f'{cause} is unknown', _retry('the forge'))]
    tags: dict[str, str] | None = None
    found: list[str] = []
    for branch, sha in gone.items():
        verdict = judge(root, policy, branch, sha, open_heads=heads, gone=gone)
        if verdict.lost and approved:
            try:
                tags = remote_tags(root) if tags is None else tags
            except OSError as failed:
                return [_refusal(UNJUDGED, f'the tags on origin cannot be read: {failed}', _retry('origin'))]
            verdict = held_by_tag(root, verdict, tags, approved)
        if verdict.refused:
            found.append(_refusal(RULE, verdict.refused, _door_for(branch, lost=bool(verdict.lost))))
    return found


def main(argv: Sequence[str] | None = None) -> int:
    """The pre-push hook: git's ref lines on stdin; exit 1 refuses, 0 publishes."""
    del argv  # the runner hands git's remote url as an env variable; the judgement is origin's
    top = _door.run(
        [_GIT, 'rev-parse', '--show-toplevel'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
        timeout=60,
    ).stdout.strip()
    stdin = '' if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read()
    found = refusals(Path(top or Path.cwd()), stdin, approved=os.environ.get(APPROVED_ENV, '').strip())
    if found:
        emit('\n'.join(found), err=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
