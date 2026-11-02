"""NO-PUSH-ONTO-A-LANDED-PR: a push onto a branch whose PR the forge already merged or closed is refused.

The forge merges a REVIEWED head. A push that arrives after it lands on a branch whose PR into the integration
branch is merged or closed, so no PR will ever carry it: the PR reads "merged" while the branch's newest commit
is on no integration branch. Seen twice on 2026-11-02 (dev-lab #44's round-3 fix, re-landed as #52; a relock
push after motronics #5397 merged); only a manual ``merge-base --is-ancestor`` noticed.

So the ``landed-pr`` pre-push row reads the forge's PRs (:func:`dev_lab.dev.forgepulls.pr_list`) for every
branch the push creates or updates, the integration branch and the trunk aside: a branch whose PR into the
integration branch is merged or closed, and that no OPEN PR has as its head, is refused, the refusal naming
the remedy -- a new PR from the branch, or a new branch name. A deletion and a tag are not judged.

A forge that cannot be read refuses, as :func:`dev_lab.dev.breakglass.forge_unreviewed` does: a push needs the
forge, so a forge down for reads is down for the push too, and an unread answer is never a pass.
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
from dev_lab.dev.forgepulls import ListingIncomplete, pr_list
from dev_lab.dev.lanepolicy import load_policy
from dev_lab.dev.refspec import pushed_refs

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client, PullRequest

__all__ = ['HOOK_ID', 'RULE', 'landed', 'main', 'refusals']

RULE: Final = 'NO-PUSH-ONTO-A-LANDED-PR'
#: The id this guard runs under in ``githooks/base.toml``.
HOOK_ID: Final = 'landed-pr'

_GIT: Final = shutil.which('git') or 'git'
_UNREADABLE: Final = (ForgeCallFailed, ListingIncomplete, OSError, ValueError)


def landed(
    open_pulls: Sequence[PullRequest], shut: Sequence[PullRequest], branch: str, base: str
) -> PullRequest | None:
    """The newest merged or closed PR of *branch* into *base*, unless an OPEN PR has *branch* as its head."""
    if any(pull.head == branch for pull in open_pulls):
        return None
    found = [pull for pull in shut if pull.head == branch and pull.base == base]
    return max(found, key=lambda pull: pull.number) if found else None


def _refusal(pull: PullRequest, branch: str, base: str) -> str:
    how = 'merged' if pull.merged else 'closed'
    return (
        f'{RULE}: {branch} is the head of PR #{pull.number} into {base}, which the forge {how}, and no open PR has '
        f'it; this push would reach no integration branch. Open a new PR from it (`python -m dev_lab.dev.forge '
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
        if client is None:
            from dev_lab.dev.forgework import client_for  # noqa: PLC0415 (a network leaf, read only when judged)

            forge = client_for(root)
        else:
            forge = client()
        open_pulls = pr_list(forge)
        unopened = [b for b in branches if not any(pull.head == b for pull in open_pulls)]
        shut = pr_list(forge, state='closed') if unopened else ()
    except _UNREADABLE as failed:
        return [
            (
                f'{RULE}: the forge cannot be read ({type(failed).__name__}: {failed}), so whether '
                f'{", ".join(branches)} already landed is unknown; a push needs the forge -- push again once it '
                'answers'
            )
        ]
    return [
        _refusal(pull, branch, integration)
        for branch in branches
        if (pull := landed(open_pulls, shut, branch, integration)) is not None
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
