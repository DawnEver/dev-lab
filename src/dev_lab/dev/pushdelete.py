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
passes it with no exemption. The one lossy delete that passes is the user's order: ``branchprune discard`` holds a
grant for exactly that branch at that sha while its push runs (:func:`dev_lab.dev.deletejudge.granted`), and a
refusal whose branch carries a root of its own names that door.
A tag on origin holds nothing (user ruling D22: "no tags -- merge or delete, never an
archive tag"): a branch with unlanded work is MERGED through a PR, or LANDED by a declared ``git merge -s ours`` PR,
and then deleted. A branch the policy declares DERIVED (decision D23, ``[tool.dev_lab.integrator] derived``) is
regenerated whole by its producer and goes.

FAILS CLOSED (:data:`UNJUDGED`): a repo declaring no integration branch (or a malformed ``derived`` row), a failed
fetch or an unreadable forge refuses naming the cause and the retry, never passes unjudged. A tag deletion is not
a branch and is not judged here; a deletion of a ref the remote does not hold drops nothing.
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.branchdelete import second_root
from dev_lab.dev.deletejudge import Verdict, granted, judge
from dev_lab.dev.disclosure import details_for
from dev_lab.dev.forge import fetch_origin
from dev_lab.dev.forgeclient import client_for
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgepulls import ListingIncomplete, pr_list
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


def _door_for(verdict: Verdict) -> str:
    branch = verdict.branch
    door = f'{_python()} -m dev_lab.dev.branchprune delete {branch}'
    if verdict.lost:
        return (
            f'MERGE what is still wanted through a PR, or LAND the branch with a declared `git merge -s ours` PR '
            f'into a pr/ branch, then {door}{second_root(verdict)}'
        )
    return f'{door} -- it fetches afresh and names what holds the branch, or why it stays'


def _retry(what: str) -> str:
    return f'push again once {what} answers ({_python()} -m dev_lab.dev.netverb -- git push ... retries it)'


def refusals(
    root: Path,
    lines: str,
    *,
    client: Callable[[], Client] | None = None,
    fetch: Callable[[Path], None] = fetch_origin,
) -> list[str]:
    """Every refusal for the branch deletions git's pre-push *lines* carry; none when the push deletes no branch."""
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
        cause = f'{named}: the delete cannot be judged -- its [tool.dev_lab.integrator] is unreadable: {failed}'
        return [_refusal(UNJUDGED, cause, 'fix the declaration the line above names, then push again')]
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
    verdicts = (judge(root, policy, branch, sha, open_heads=heads, gone=gone) for branch, sha in gone.items())
    kept = [one for one in verdicts if one.refused and not (one.lost and granted(root, one.branch, one.sha))]
    return [_refusal(RULE, one.refused, _door_for(one)) for one in kept]


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
    found = refusals(Path(top or Path.cwd()), stdin)
    if found:
        emit('\n'.join(found), err=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
