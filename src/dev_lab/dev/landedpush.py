"""NO-PUSH-ONTO-A-LANDED-PR: a push onto a branch whose PR the forge already merged or closed is refused.

The forge merges a REVIEWED head. A push that arrives after it lands on a branch whose PR into the integration
branch is merged or closed, so no PR will ever carry it: the PR reads "merged" while the branch's newest commit
is on no integration branch. Seen twice on 2026-11-02 (dev-lab #44's round-3 fix, re-landed as #52; a relock
push after motronics #5397 merged); only a manual ``merge-base --is-ancestor`` noticed.

So the ``landed-pr`` pre-push row asks the forge ONE question per branch the push creates or updates, the
integration branch and the trunk aside -- the newest PR of that head into the integration branch
(:func:`dev_lab.dev.forgepulls.pr_by_head`), never a listing of every closed PR: when it is merged or closed
(so no newer OPEN PR of that pair exists) the push is refused, the refusal naming
the remedy -- a new PR from the branch, or a new branch name. A deletion and a tag are not judged.

A DECLARED long-lived branch is reopened after each landing (user ruling 2026-11-07): a name in the repo's
``[tool.dev_lab.branchset] sessions`` (:func:`dev_lab.dev.branchset.declared_branchset`) is the ONE branch a
session keeps, so its next PR comes from the same name -- and a refusal there deadlocks, because the forge
cannot open a PR from a ref origin lacks. Its landed head therefore takes a push whose tip is NOT already an
ancestor of ``origin/<integration>`` (new work), and the hook prints a notice naming the ``forge pr create``
that carries it; a tip the integration branch already holds is refused as nothing new. An undeclared branch
keeps the refusal.

A forge that cannot be read refuses, as :func:`dev_lab.dev.breakglass.forge_unreviewed` does: a push needs the
forge, so a forge down for reads is down for the push too, and an unread answer is never a pass.
"""

from __future__ import annotations

import dataclasses
import shutil
import sys
from collections.abc import Callable, Collection, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.branchset import BranchSetNotDeclared, declared_branchset
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgepulls import ListingIncomplete, pr_by_head
from dev_lab.dev.forgework import client_for
from dev_lab.dev.lanepolicy import load_policy
from dev_lab.dev.refspec import pushed_refs

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client, PullRequest

__all__ = ['HOOK_ID', 'RULE', 'Verdict', 'judge', 'landed', 'main', 'refusals']

RULE: Final = 'NO-PUSH-ONTO-A-LANDED-PR'
#: The id this guard runs under in ``githooks/base.toml``.
HOOK_ID: Final = 'landed-pr'

_GIT: Final = shutil.which('git') or 'git'
_UNREADABLE: Final = (ForgeCallFailed, ListingIncomplete, OSError, ValueError)


def landed(newest: PullRequest | None) -> PullRequest | None:
    """*newest* -- the newest PR of a branch into the integration branch -- when the forge merged or closed it.

    An open newest PR carries the push; a newer open PR after a landed one is the newest, so it passes too.
    """
    return newest if newest is not None and newest.state != 'open' else None


def _refusal(pull: PullRequest, branch: str, base: str) -> str:
    how = 'merged' if pull.merged else 'closed'
    return (
        f'{RULE}: {branch} is the head of PR #{pull.number} into {base}, which the forge {how}, and no open PR has '
        f'it; this push would reach no integration branch. Open a new PR from it (`python -m dev_lab.dev.forge '
        f'pr create --head {branch} --base {base} --title ...`), or push the commits to a new branch name'
    )


def _reopen_notice(pull: PullRequest, branch: str, base: str) -> str:
    return (
        f'{branch} is a declared long-lived branch whose PR #{pull.number} into {base} landed; this push carries '
        f'new work, so open its next PR now: `python -m dev_lab.dev.forge pr create --head {branch} --base {base} '
        '--title ...`'
    )


def _nothing_new(pull: PullRequest, branch: str, base: str) -> str:
    return (
        f'{RULE}: {branch} is a declared long-lived branch whose PR #{pull.number} into {base} landed, and the '
        f'pushed tip is already in origin/{base}: nothing new to carry. Commit the new work, then push'
    )


@dataclasses.dataclass(frozen=True)
class Verdict:
    """What the push earns: *refusals* stop it; *notices* tell the pusher what to do once it lands on origin."""

    refusals: list[str]
    notices: list[str]


def _integrated_in(root: Path, integration: str) -> Callable[[str], bool]:
    """Whether a sha is an ancestor of ``origin/<integration>``; git that cannot answer raises OSError."""

    def integrated(sha: str) -> bool:
        done = _door.run(
            [_GIT, 'merge-base', '--is-ancestor', sha, f'refs/remotes/origin/{integration}'],
            cwd=root,
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=False,
            timeout=60,
        )
        if done.returncode not in {0, 1}:
            msg = f'git merge-base --is-ancestor {sha} origin/{integration}: {done.stderr.strip()}'
            raise OSError(msg)
        return done.returncode == 0

    return integrated


def _sessions_of(root: Path) -> frozenset[str]:
    try:
        return declared_branchset(root).sessions
    except BranchSetNotDeclared:
        return frozenset()


def judge(
    root: Path,
    lines: str,
    *,
    integration: str = '',
    trunk: str = '',
    client: Callable[[], Client] | None = None,
    sessions: Collection[str] | None = None,
    integrated: Callable[[str], bool] | None = None,
) -> Verdict:
    """The verdict on the push *lines* describe.

    *integration*, *trunk* and *sessions* default to *root*'s declarations; *integrated* (is a sha already in
    ``origin/<integration>``) to git in *root*.
    """
    if not integration:
        policy = load_policy(root)
        integration, trunk = policy.integration, policy.trunk
    tips = {
        ref.branch: ref.local_sha
        for ref in pushed_refs(lines.splitlines())
        if ref.branch and not ref.deleted and ref.branch not in {integration, trunk}
    }
    branches = list(tips)
    if not branches:
        return Verdict([], [])
    try:
        forge = client_for(root) if client is None else client()
        newest = {branch: pr_by_head(forge, branch, integration) for branch in branches}
    except _UNREADABLE as failed:
        return Verdict(
            [
                (
                    f'{RULE}: the forge cannot be read ({type(failed).__name__}: {failed}), so whether '
                    f'{", ".join(branches)} already landed is unknown; a push needs the forge -- push again once it '
                    'answers'
                )
            ],
            [],
        )
    long_lived = _sessions_of(root) if sessions is None else frozenset(sessions)
    is_integrated = _integrated_in(root, integration) if integrated is None else integrated
    found: list[str] = []
    notices: list[str] = []
    for branch in branches:
        pull = landed(newest[branch])
        if pull is None:
            continue
        if branch not in long_lived:
            found.append(_refusal(pull, branch, integration))
            continue
        try:
            already = is_integrated(tips[branch])
        except OSError as failed:
            found.append(f'{RULE}: whether {branch} carries new work is unknown ({failed}); fetch, then push again')
            continue
        if already:
            found.append(_nothing_new(pull, branch, integration))
        else:
            notices.append(_reopen_notice(pull, branch, integration))
    return Verdict(found, notices)


def refusals(
    root: Path, lines: str, *, integration: str = '', trunk: str = '', client: Callable[[], Client] | None = None
) -> list[str]:
    """Every refusal for the push *lines* describe; *integration* and *trunk* default to *root*'s declaration."""
    return judge(root, lines, integration=integration, trunk=trunk, client=client).refusals


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
        verdict = judge(root, stdin)
    except (OSError, ValueError) as failed:
        verdict = Verdict(
            [f'{RULE}: {root} declares no readable integrator, so the push cannot be judged: {failed}'], []
        )
    found = verdict.refusals
    if verdict.notices and not found:
        emit('\n'.join(['', *(f'  NEXT: {line}' for line in verdict.notices), '']), err=True)
    if found:
        emit('\n'.join(['', *(f'  REFUSED: {line}' for line in found), '']), err=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
