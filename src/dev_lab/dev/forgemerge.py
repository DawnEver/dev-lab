"""INTEGRATION-TAKES-ONLY-FORGE-MERGES: the forge merges a reviewed, safe, clean PR into integration, server side.

User ruling 2026-10-19: every change is a short-lived branch returning by a PR to the integration branch,
which takes ONLY server-side merges. THE TEST PARTS GATE THAT MERGE (user ruling 2026-11-04, superseding
2026-10-29's "parts never gate", after dev-lab#78 merged with ``tests/base`` FAILED and reddened integration): every
part the head needs stands PASS (:func:`dev_lab.dev.platformparts.standing`, the reading promotion uses at scope full
in :func:`dev_lab.dev.integrate.promote`); absent or pending waits, FAIL refuses -- every HOSTED part: a hand part
(:func:`~dev_lab.dev.forgemergewaits.hand_parts`, user ruling 2026-11-10) is named and tested later, never waited
on. Opted into by declaring ``[tool.dev_lab.integrator] pr_merges_since = "<sha>"``; from then on the integration
tick (:func:`dev_lab.dev.forgeintegration.tick`) asks :func:`decide` of each open PR into integration and, when
nothing is missing, asks the forge to merge it (:func:`dev_lab.dev.forgemergecall.merge`). A client push adding a
commit to the branch is refused at pre-push (:mod:`dev_lab.dev.sessionbranch`, P5).

THIS MODULE DECIDES; it writes nothing. The status readings are :mod:`dev_lab.dev.forgemergewaits`, the forge's
merge calls :mod:`dev_lab.dev.forgemergecall`, and posting the decision (``forge merge ready``)
:mod:`dev_lab.dev.forgemergeready`.

ONE DECISION ON BOTH FORGES (user ruling 2026-10-29); only who MERGES differs. :func:`judged` reads a PR's head and
decides; a workflow job runs ``forge merge ready [--pr <N>]`` (:func:`dev_lab.dev.forgemergeready.ready`; no
number: every open PR into integration), which posts the decision as ONE status,
:data:`~dev_lab.dev.forgecontexts.MERGE_READY_CONTEXT`, and on ``success`` asks the forge to merge that head itself
(:func:`~dev_lab.dev.forgemergecall.merge`, as the job's own token). WHO merges is the family's binding of
``merge`` (:mod:`dev_lab.dev.roles`, D73): bound to ``ci``, that job merges (GitHub's ``ci.yml`` and merge tick,
Gitea's ``merge.yml`` on the light runner) and the serve tick only says the decision; bound to an ``hpc`` executor,
its serve tick merges on the same :func:`judged`.
GitHub still enforces the branch's required checks on that merge; one still pending refuses it, and the native
auto-merge ``forge pr create`` enabled merges once they are green. GitHub refuses to enable auto-merge on a PR
that is already mergeable (dev-lab#15), which is why the job that posts ready merges rather than waiting on it.
The PR base is :attr:`~dev_lab.dev.lanepolicy.Policy.integration`.

A PR IS MERGED WHEN, and only when, read from the object store and the forge (a repo declaring
``[tool.dev_lab.integrator] merge_checks`` -- one no serve host serves, user ruling 2026-11-12 -- reads its declared
checks standing ``success`` (:func:`~dev_lab.dev.forgemergewaits.checks_wait`) IN PLACE of the first, fourth and
fifth conditions, which a serve host posts):

* its head's HOSTED test parts all stand PASS (:func:`~dev_lab.dev.forgemergewaits.parts_wait`); a hand part is
  named, never waited on (:func:`~dev_lab.dev.forgemergewaits.hand_parts`, user ruling 2026-11-10);
* its review is ADVISORY and never a condition (user rulings 2026-11-11/12, both forges): the review still runs at
  the PR's first merge-ready head (:mod:`dev_lab.dev.reviewturn`) and posts its comment and ``tests/review``; a head
  whose review is not a forge-posted ``success`` (:func:`dev_lab.dev.forgereview_gate.review_gate`) merges WARNED --
  the decision names why, and the merged PR gets a comment saying so. A review that did not run and left its
  recorded cause (:func:`dev_lab.dev.reviewcap.unreviewed_waiver`) carries ``Unreviewed: ...`` into the commit message;
* it is an INTERNAL PR (:func:`external`, user ruling 2026-11-05): a fork's, or a non-writer's, is never merged by
  the forge -- ``tests/merge-ready`` stays ``pending`` :data:`EXTERNAL`;
* its head's ``tests/security`` stands ``success`` (:mod:`dev_lab.dev.forgesecurity`): ``failure`` names the
  findings, ``error`` is a scan that gave no answer, and both wait;
* its head's push-row GATES stand ``success`` (:func:`dev_lab.dev.forgeheadgate.gates_wait`: ``session-branch``,
  user ruling 2026-11-07) -- the same judge the pre-push row calls, posted by the forge, so a consumer's stale hook
  never disarms it; absent, ``error`` or ``failure`` waits. ``pr-current`` and ``lock/lag`` are ALARMS, never waited
  on (W5, dev-lab#644): a stale head is judged by the trial merge below, at merge time;
* its head merges into ``origin/<integration>`` with no conflict (it contains integration, or the
  three-way merge is clean -- :func:`dev_lab.dev.trialmerge.trial`);
* the merge commit the forge will write passes the merge audit
  (:func:`dev_lab.dev.mergeaudit.judge`, the same judgment the commit-msg hook makes) -- its message
  names the branch (``Merged-Branch:``), so INTEGRATION-IS-MERGES-ONLY holds of it too;
* every commit its head adds over integration passes the repo's OWN declared message row -- the pre-push row
  running ``cz-push-range``, run here on the range ``origin/<integration>..<head>`` with that row's env in its
  ``--merge-decision`` mode -- commits the base already holds are history, the PR's own are all judged, none
  exempt (:func:`message_wait`). A worktree with no venv skips that row at commit and push, so the
  merge is the one place no client can skip it; a repo declaring no such row is not judged on messages;
* a head that adds a crate (a ``Cargo.toml``) carries a measured ``Port-Measured:`` trailer
  (:func:`dev_lab.dev.portmeasure.unmeasured`, MEASURE-BEFORE-PORTING);
* every merge commit its head adds over integration declares each file its parents conflict on
  (:func:`dev_lab.dev.mergeresolution.unresolved`, MERGE-RESOLUTION-DECLARED) -- the one place no client and no
  web-UI merge can skip it.

Otherwise the PR stays open and the missing conditions are said in its one integration comment. The merge
is a MERGE COMMIT (``Do: merge``, never squash or rebase), pinned to the judged head (``head_commit_id``: a
head that moved since is refused by the forge, and judged afresh next tick). A head in a declared ephemeral
namespace is deleted by the forge with the merge.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from dev_lab.dev.failprint import Fingerprints, new_subjects, refusal
from dev_lab.dev.forgecontexts import MERGE_READY_CONTEXT
from dev_lab.dev.forgedraft import WAITING
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgeheadgate import alarms_said
from dev_lab.dev.forgehold import HELD, is_held
from dev_lab.dev.forgemergewaits import hand_note, off_record, recorded_as_ran, red_checks, status_waits
from dev_lab.dev.forgemessages import MESSAGES_NOT_DECLARED, message_row, message_wait
from dev_lab.dev.forgereview_declared import load_review
from dev_lab.dev.forgereview_gate import review_gate
from dev_lab.dev.forgestatus import fingerprints_at, status_list
from dev_lab.dev.mergeaudit import MergeAuditError, judge
from dev_lab.dev.mergeresolution import unresolved
from dev_lab.dev.portmeasure import unmeasured
from dev_lab.dev.reviewcap import unreviewed_waiver
from dev_lab.dev.roles import REVIEW, TESTS, Unbound, roles_at
from dev_lab.dev.sessionbranch import MERGED_BRANCH
from dev_lab.dev.trialmerge import trial

if TYPE_CHECKING:
    from dev_lab.dev.forgestatus import CommitStatus
    from dev_lab.dev.forgework import Client, PullRequest
    from dev_lab.dev.lanepolicy import Policy
    from dev_lab.dev.reviewgate import Reviewed

__all__ = [
    'EXTERNAL',
    'FORGE_PULL',
    'Decision',
    'decide',
    'external',
    'hidden_reds',
    'judged',
    'merge_message',
]  # fmt: skip

#: The merge decision's ``pending`` line for a PR the forge never merges (:func:`external`).
EXTERNAL: Final = 'external PR: a maintainer merges it'

#: The trailer naming the pull request a forge merge closed.
FORGE_PULL: Final = 'Forge-Pull'


@dataclass(frozen=True)
class Decision:
    """Whether one PR may be merged now: what is missing (nothing, when it may), and the message it merges with."""

    others: tuple[str, ...]  # every missing condition; the review is never one (advisory)
    message: str
    review: str | None = None  # why the head is not reviewed, REPORTED; ``None``: it is (reviewturn asks for it)
    unreviewed: str = ''  # the unreviewed warning (:mod:`dev_lab.dev.reviewcap`) when the review was waived
    notes: tuple[str, ...] = ()
    waiting: bool = False  # every missing condition is a check not yet terminal: posted ``pending``, not ``failure``

    @property
    def missing(self) -> tuple[str, ...]:
        """Every missing condition: never the review, which is advisory (user rulings 2026-11-11/12)."""
        return self.others

    @property
    def ready(self) -> bool:
        """Whether nothing is missing."""
        return not self.missing


def merge_message(branch: str, number: int, policy: Policy) -> str:
    """The merge commit's message: a conventional subject, then the ``Merged-Branch``/``Forge-Pull`` trailers."""
    return (
        f'chore(merge): {branch} into {policy.integration} (#{number})\n\n'
        f'{MERGED_BRANCH}: {branch}\n{FORGE_PULL}: {number}\n'
    )


def decide(
    root: Path,
    policy: Policy,
    *,
    branch: str,
    number: int,
    head: str,
    statuses: Sequence[CommitStatus],
    reviewed: Reviewed,
    waiver: str | None = None,
    record: str = '',
) -> Decision:
    """What PR *number* (*branch* at *head*) lacks to be merged into ``origin/<integration>``; writes nothing.

    *waiver* (:func:`dev_lab.dev.reviewcap.unreviewed_waiver`) waives the review condition alone, and the message and
    the decision carry it. *record* is the PR body: a red test part it puts on record (``Red-On-Record:``) reads
    as ran (RED-INTEGRATION-MERGES); every other red still waits, named with that door.
    """
    unrecorded = off_record(statuses, record)
    statuses = recorded_as_ran(statuses, record)
    into = policy.integration
    base = f'refs/remotes/origin/{into}'
    message = merge_message(branch, number, policy)
    missing: list[str] = []
    try:  # a review config that cannot review is named here, never silently mergeable
        load_review(root)
    except ValueError as config:
        missing.append(f'its review config: {config}')
    waived = ''
    if (unreviewed := reviewed(statuses)) is not None and waiver:  # waived: satisfied, warned
        waived, unreviewed = waiver, None
        title, _, trailers = message.partition('\n\n')
        message = f'{title}\n\n{waiver}\n\n{trailers}'
    try:
        waits = status_waits(policy, head, statuses, tests=roles_at(root).kind(TESTS))
    except Unbound as undeclared:  # a malformed producer is named, never merged
        waits = [f'its producer: {undeclared}']
    missing += waits + unrecorded
    tried = trial(root, base, head)
    if not tried.clean:
        files = ', '.join(f'`{name}`' for name in tried.conflicts)
        missing.append(
            f'a clean merge: it conflicts with `{into}` in {files} -- merge `{into}` '
            f'into the branch (python -m dev_lab.dev.forge sync) and push it'
        )
    else:
        try:
            problems = judge(root, [base, head], tried.tree, message, roots=policy.test_roots, label=f'#{number}')
        except MergeAuditError as error:
            problems = (str(error),)
        missing += [f'a merge the audit passes: {problem}' for problem in problems]
    if (off := message_wait(root, base, head)) is not None:
        missing.append(f'conventional commit messages: {off}')
    try:
        port = unmeasured(root, base, head)
    except ValueError as unread:
        port = f'its port record cannot be read: {unread}'
    if port is not None:
        missing.append(f'a measured port: {port}')
    try:
        undeclared = unresolved(root, base, head)
    except MergeAuditError as error:
        undeclared = (('?', (str(error),)),)
    missing += [
        f'merge {sha[:12]} declaring its resolution (MERGE-RESOLUTION-DECLARED): {"; ".join(problems)} -- a merge '
        f'message cannot be amended, so redo that merge with one `<path>: <class> -- <why>` line per conflicted '
        f'file and push the redone branch'
        for sha, problems in undeclared
    ]
    waiting = len(missing) == len(waits) and not red_checks(statuses)  # the review is never in missing
    return Decision(tuple(missing), message, unreviewed, waived, _notes(root, statuses), waiting)


def _notes(root: Path, statuses: Sequence[CommitStatus]) -> tuple[str, ...]:
    """What the decision says without waiting on it: an undeclared message row, the hand parts and the alarms."""
    unjudged = () if message_row(root) is not None else (MESSAGES_NOT_DECLARED,)
    alarmed = alarms_said(statuses)
    alarm = f'alarms, never a merge condition: {alarmed}' if alarmed else None
    return (*unjudged, *filter(None, [hand_note(statuses), alarm]))


def external(client: Client, pull: PullRequest) -> bool:
    """Whether *pull* is an EXTERNAL contributor's, which the forge never merges (user ruling 2026-11-05).

    Only a forge that vets authors has one (:attr:`~dev_lab.dev._forgebackends.Backend.vets_authors`, GitHub): a
    fork's head, or an author it does not trust (:meth:`~dev_lab.dev.forgework.Client.trusts`). Gitea is private,
    so nothing on it is external (user ruling 2026-11-06). It is still tested and reviewed; a human merges it.
    """
    return client.backend.vets_authors and (pull.fork or not client.trusts(pull.author))


def hidden_reds(
    read: Callable[[str], Fingerprints], head: str, base: str, statuses: Sequence[CommitStatus]
) -> str | None:
    """Why *head*'s reds name subjects *base*'s tip does not carry under the same test (D13), or ``None``.

    *read* is a ref's fingerprints (:func:`dev_lab.dev.forgestatus.fingerprints_at`); the break-glass admission
    asks this too. A head with no red reads no record, and one whose reds name no subject reads no base.
    Pass-to-fail is not judged here: a red the base lacks is its own wait.
    """
    if all(status.state == 'success' for status in statuses):
        return None
    try:
        mine = read(head)
        if not any(subjects for nodes in mine.values() for subjects in nodes.values()):
            return None
        return refusal(new_subjects(mine, read(base)))
    except (ForgeCallFailed, ValueError, KeyError, TypeError) as failed:
        return f'its failure fingerprints against {base} cannot be read ({failed}); the forge must answer first'


def judged(root: Path, client: Client, policy: Policy, *, branch: str, number: int, head: str) -> Decision:
    """:func:`decide` on PR *number*'s *head* as the forge holds it now: its statuses."""
    statuses = [one for one in status_list(client, head) if one.context != MERGE_READY_CONTEXT]
    try:
        reviewed = review_gate(client, base=policy.integration, by=roles_at(root).kind(REVIEW))
    except ValueError as config:  # a declaration that cannot gate is this PR's wait, never the tick's crash

        def reviewed(_statuses: Sequence[CommitStatus], why: str = str(config)) -> str:
            return f'the review gate cannot be read: {why}'

    waiver = unreviewed_waiver(client, number, base=policy.integration)
    pull = client.pr_view(number)
    found = decide(
        root,
        policy,
        branch=branch,
        number=number,
        head=head,
        statuses=statuses,
        reviewed=reviewed,
        waiver=waiver,
        record=pull.body,
    )
    others = found.others
    if (
        hidden := hidden_reds(lambda ref: fingerprints_at(client, ref), head, policy.integration, statuses)
    ) is not None:
        others = (hidden, *others)
    if external(client, pull):  # INTERNAL-ONLY (2026-11-05): never merged by the forge, whatever else is green
        others = (EXTERNAL, *others)
    if pull.draft:  # DRAFT-UNTIL-READY (D53): a draft never lands, whatever else is green
        others = (WAITING.format(n=number), *others)
    if is_held(pull.labels):  # HOLD: a held PR never lands, on a forge that refuses its draft too
        others = (HELD.format(n=number), *others)
    waiting = found.waiting and len(others) == len(found.others)
    return Decision(others, found.message, found.review, found.unreviewed, found.notes, waiting)
