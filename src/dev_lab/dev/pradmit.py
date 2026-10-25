"""PR ADVICE: ONE-SESSION-ONE-PR and NO-STACKED-PRS, told where a PR is born -- never a refusal.

THE INTENT (user ruling 2026-10-25). A development agent focused on ONE task gathers all of its work on ONE PR;
the rule is that agent's guidance, and a PR is never what blocks the flow. So ``forge pr create`` always opens
the PR, and when the head shares a session with another open PR, or holds another open PR's unmerged commits,
it says so -- on stderr and as an ``Admission:`` line in the PR body -- naming the other PR and the remedy.
There is no refusal, so there is no split list and no door around one.

ONE-SESSION-ONE-PR. A session's commits carry its ``Lab-Session`` (:mod:`dev_lab.dev.labsession`). A head whose
commits share a session with ANOTHER open head is told that the session's work belongs on the branch it has.

NO-STACKED-PRS. A head holding a commit of another open head that integration does not hold is told it is
stacked (:func:`dev_lab.dev.trialmerge.shares_unmerged`, the one owner of the stack question): one stalled base
holds every PR stacked on it.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Final

from dev_lab.dev.forgepulls import pr_list
from dev_lab.dev.forgework import PullRequest
from dev_lab.dev.labsession import sessions
from dev_lab.dev.trialmerge import contains, rev, shares_unmerged

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = ['ADMISSION', 'advice', 'create_advice']

#: The PR-body line prefix each piece of advice is recorded under.
ADMISSION: Final = 'Admission'


def _label(pull: PullRequest) -> str:
    return f'#{pull.number} ({pull.head})' if pull.number else pull.head


def advice(root: Path, *, head: str, tip: str, others: Iterable[PullRequest]) -> tuple[str, ...]:
    """What *head* should know beside *others* (open heads) over integration *tip*; empty when nothing."""
    own = sessions(root, tip, head)
    said = []
    for other in others:
        if not other.head_sha or other.head_sha == head or contains(root, tip, other.head_sha):
            continue  # itself, or already in integration: nothing to tell
        if contains(root, head, other.head_sha):
            said.append(f'carries open PR {_label(other)} whole: landing this lands it')
        elif shares_unmerged(root, head, other.head_sha, tip):
            said.append(
                f'stacked on open PR {_label(other)} (NO-STACKED-PRS): it holds commits integration does not; '
                f'it lands only after {_label(other)}'
            )
        elif shared := sorted(own & sessions(root, tip, other.head_sha)):
            said.append(
                f'session {", ".join(shared)} also has open PR {_label(other)} (ONE-SESSION-ONE-PR): a focused '
                f'task gathers its work there -- git push origin HEAD:{other.head}'
            )
    return tuple(said)


def create_advice(root: Path, client: Client, *, head: str, base: str) -> tuple[str, ...]:
    """``forge pr create``'s advice for *head* into *base*, against the forge's open PRs."""
    tip = f'refs/remotes/origin/{base}'
    sha = rev(root, f'refs/remotes/origin/{head}') or rev(root, f'refs/heads/{head}')
    if rev(root, tip) is None or sha is None:
        return (f'origin/{base} or {head} is not here, so no session or stack was judged: fetch origin to see it',)
    others = [pull for pull in pr_list(client) if pull.head != head]
    unseen = [_label(pull) for pull in others if pull.head_sha and rev(root, pull.head_sha) is None]
    here = [pull for pull in others if not pull.head_sha or rev(root, pull.head_sha) is not None]
    said = advice(root, head=sha, tip=tip, others=here)
    if unseen:
        said += (f'the heads of open PRs {", ".join(unseen)} are not here and were not judged: fetch origin',)
    return said
