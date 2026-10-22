"""PR ADMISSION: ONE-SESSION-ONE-PR and NO-STACKED-PRS, judged where a PR is born.

ONE-SESSION-ONE-PR. A session's commits carry its ``Lab-Session`` (:mod:`dev_lab.dev.labsession`, stamped from
the launcher's id). A head whose commits share a session with ANOTHER open head is refused: the session's work
belongs on the branch it already has, and the remedy names that branch. Judged at ``forge pr create`` against the
forge's open PRs, and at the pre-push of a NEW ``pr/*`` branch against the last fetch's unmerged
``origin/pr/*`` heads (a pre-push hook makes no network call). A split is admitted only for a session in
:data:`SPLITS`, each with its reason, under a ceiling pinned by its test that only falls; there is no switch.

NO-STACKED-PRS. A head holding a commit of another open head that integration does not hold is refused at
``forge pr create`` (:func:`dev_lab.dev.trialmerge.shares_unmerged`, the one owner of the stack question):
one stalled base would hold every PR stacked on it. Every PR is cut from and targets the integration branch.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.branchset_push import pushed_refs
from dev_lab.dev.forge import _GIT, _GIT_TIMEOUT_S
from dev_lab.dev.forgepulls import pr_list
from dev_lab.dev.forgework import PullRequest
from dev_lab.dev.labsession import TRAILER, sessions
from dev_lab.dev.lanepolicy import Policy, load_policy
from dev_lab.dev.trialmerge import contains, rev, shares_unmerged

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = ['ALLOWED', 'PREFIX', 'REFUSED', 'SPLITS', 'create_refusal', 'main', 'push_refusal', 'refusal']

ALLOWED: Final = 0
REFUSED: Final = 1

#: The branch prefix whose creation is judged at push.
PREFIX: Final = 'pr/'

#: The declared exceptions to ONE-SESSION-ONE-PR: ``(session id, why it is split)``. Counted and pinned by
#: ``tests/test_dev_pradmit.py``; a freed entry lowers the pin in the same commit.
SPLITS: tuple[tuple[str, str], ...] = ()


def _label(pull: PullRequest) -> str:
    return f'#{pull.number} ({pull.head})' if pull.number else pull.head


def refusal(root: Path, *, head: str, tip: str, others: Iterable[PullRequest]) -> str | None:
    """Why *head* may not be a PR beside *others* (open heads) over integration *tip*; ``None`` when it may."""
    split = {session for session, _reason in SPLITS}
    own = sessions(root, tip, head) - split
    for other in others:
        if not other.head_sha or other.head_sha == head:
            continue
        if shares_unmerged(root, head, other.head_sha, tip):
            return (
                f'this head is stacked on open PR {_label(other)}: it holds commits integration does not.\n'
                f'  REMEDY: wait for {_label(other)} to merge and cut again from integration, or fold this work '
                f'into {other.head}.'
            )
        if shared := sorted(own & sessions(root, tip, other.head_sha)):
            return (
                f'session {", ".join(shared)} already has open PR {_label(other)} (ONE-SESSION-ONE-PR).\n'
                f'  REMEDY: push these commits onto {other.head} -- git push origin HEAD:{other.head}.'
            )
    return None


def create_refusal(root: Path, client: Client, *, head: str, base: str) -> str | None:
    """``forge pr create``'s admission of *head* into *base*, against the forge's open PRs; ``None`` admits."""
    tip = f'refs/remotes/origin/{base}'
    sha = rev(root, f'refs/remotes/origin/{head}') or rev(root, f'refs/heads/{head}')
    if rev(root, tip) is None or sha is None:
        return f'origin/{base} or {head} is not here: fetch origin, then create the PR again.'
    others = [pull for pull in pr_list(client) if pull.head != head]
    if missing := [_label(pull) for pull in others if pull.head_sha and rev(root, pull.head_sha) is None]:
        return f'the heads of open PRs {", ".join(missing)} are not here: fetch origin, then create the PR again.'
    return refusal(root, head=sha, tip=tip, others=others)


def _origin_heads(root: Path, tip: str) -> list[PullRequest]:
    """Every ``origin/pr/*`` head of the last fetch that integration *tip* does not hold: an open head."""
    done = _door.run(
        [_GIT, '-C', str(root), 'for-each-ref', '--format=%(refname:strip=3) %(objectname)',
         f'refs/remotes/origin/{PREFIX}'],
        capture_output=True, text=True, encoding='utf-8', timeout=_GIT_TIMEOUT_S, check=False,
    )  # fmt: skip
    pairs = (line.split() for line in done.stdout.splitlines() if line.strip())
    return [
        PullRequest(0, branch, 'open', '', '', '', branch, '', head_sha=sha)
        for branch, sha in pairs
        if not contains(root, tip, sha)
    ]


def push_refusal(root: Path, *, lines: Iterable[str] = (), policy: Policy | None = None) -> tuple[int, str]:
    """The pre-push verdict: a NEW ``pr/*`` branch sharing a session with an unmerged ``origin/pr/*`` is refused."""
    born = [
        ref for ref in pushed_refs(lines) if ref.created and not ref.deleted and (ref.branch or '').startswith(PREFIX)
    ]
    if not born:
        return ALLOWED, ''
    policy = load_policy(root) if policy is None else policy
    tip = f'refs/remotes/origin/{policy.integration}'
    if rev(root, tip) is None:
        return ALLOWED, ''  # no integration branch here: no PR into it to share a session with
    for ref in born:
        others = [head for head in _origin_heads(root, tip) if head.head != ref.branch]
        own = sessions(root, tip, ref.local_sha) - {session for session, _reason in SPLITS}
        for other in others:
            if shared := sorted(own & sessions(root, tip, other.head_sha)):
                return REFUSED, (
                    f'[pr-admit] REFUSED -- new {ref.branch} carries {TRAILER} {", ".join(shared)}, which '
                    f'unmerged {other.head} already carries (ONE-SESSION-ONE-PR).\n'
                    f'[pr-admit]   REMEDY: push onto {other.head} instead -- git push origin HEAD:{other.head}.\n'
                )
    return ALLOWED, ''


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m dev_lab.dev.pradmit [ROOT]`` -- the pre-push entry point, refspec lines on stdin."""
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(args[0]) if args else Path.cwd()
    lines = () if sys.stdin.isatty() else tuple(sys.stdin.read().splitlines())
    code, text = push_refusal(root, lines=lines)
    if text:
        emit(text, err=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
