"""NO-PUSH-ONTO-A-CLOSED-PR: a push onto a branch whose PR the forge closed UNMERGED is refused.

A PR closed without merging was refused work: nothing reopens it, so a push onto its branch reaches no
integration branch while the branch reads as handled. A branch whose PR MERGED is different: the forge opens a
continuation PR from it (LANDED-BRANCH-CONTINUES, :mod:`dev_lab.dev.prcontinue`, user ruling 2026-11-07), so that
push is carried and passes here.

So the ``closed-pr`` pre-push row asks the forge ONE question per branch the push creates or updates, the
integration branch and the trunk aside -- the newest PR of that head into the integration branch
(:func:`dev_lab.dev.forgepulls.pr_by_head`), never a listing of every closed PR: when it is closed and not merged
(so no newer OPEN PR of that pair exists) the push is refused, the refusal naming the remedy -- a new PR from the
branch, or a new branch name. A deletion and a tag are not judged.

A forge that cannot be read refuses: a push needs the forge, so a forge down for reads is down for the push too,
and an unread answer is never a pass.
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgepulls import ListingIncomplete, pr_by_head
from dev_lab.dev.forgework import client_for
from dev_lab.dev.lanepolicy import load_policy
from dev_lab.dev.refspec import pushed_refs

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client, PullRequest

__all__ = ['HOOK_ID', 'RULE', 'closed_unmerged', 'main', 'refusals']

RULE: Final = 'NO-PUSH-ONTO-A-CLOSED-PR'
#: The id this guard runs under in ``githooks/base.toml``.
HOOK_ID: Final = 'closed-pr'

_GIT: Final = shutil.which('git') or 'git'
_UNREADABLE: Final = (ForgeCallFailed, ListingIncomplete, OSError, ValueError)


def closed_unmerged(newest: PullRequest | None) -> PullRequest | None:
    """*newest* -- the newest PR of a branch into the integration branch -- when the forge closed it unmerged.

    An open newest PR carries the push; a merged one is continued by the forge; neither is returned.
    """
    return newest if newest is not None and newest.state != 'open' and not newest.merged else None


def _refusal(pull: PullRequest, branch: str, base: str) -> str:
    return (
        f'{RULE}: {branch} is the head of PR #{pull.number} into {base}, which the forge closed unmerged, and no open '
        f'PR has it; this push would reach no integration branch. Open a new PR from it (`python -m dev_lab.dev.forge '
        f'pr create --head {branch} --base {base} --title ...`), or push the commits to a new branch name'
    )


def refusals(
    root: Path, lines: str, *, integration: str = '', trunk: str = '', client: Callable[[], Client] | None = None
) -> list[str]:
    """Every refusal for the push *lines* describe; *integration* and *trunk* default to *root*'s declaration."""
    if not integration:
        policy = load_policy(root)
        integration, trunk = policy.integration, policy.trunk
    branches = [
        ref.branch
        for ref in pushed_refs(lines.splitlines())
        if ref.branch and not ref.deleted and ref.branch not in {integration, trunk}
    ]
    if not branches:
        return []
    try:
        forge = client_for(root) if client is None else client()
        newest = {branch: pr_by_head(forge, branch, integration) for branch in branches}
    except _UNREADABLE as failed:
        return [
            (
                f'{RULE}: the forge cannot be read ({type(failed).__name__}: {failed}), so whether '
                f'{", ".join(branches)} was closed unmerged is unknown; a push needs the forge -- push again once it '
                'answers'
            )
        ]
    return [
        _refusal(pull, branch, integration)
        for branch in branches
        if (pull := closed_unmerged(newest[branch])) is not None
    ]


def main(argv: Sequence[str] | None = None) -> int:
    """The pre-push hook: git's ref lines on stdin; exit 1 refuses, 0 publishes."""
    del argv  # git passes the remote name and url; the forge is origin's
    top = _door.run(
        [_GIT, 'rev-parse', '--show-toplevel'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
        timeout=60,
    ).stdout.strip()
    root = Path(top or Path.cwd())
    stdin = '' if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read()
    try:
        found = refusals(root, stdin)
    except (OSError, ValueError) as failed:
        found = [f'{RULE}: {root} declares no readable integrator, so the push cannot be judged: {failed}']
    if found:
        emit('\n'.join(['', *(f'  REFUSED: {line}' for line in found), '']), err=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
