"""LANDED-BRANCH-CONTINUES: ONE review record per branch, accumulating across its PRs.

User-approved design 2026-11-07: review KNOWLEDGE is reused, the merged PR OBJECT never is. A merged PR stays the
immutable record of what was reviewed and tested at its head; a push onto its branch is carried by a continuation PR
(:mod:`dev_lab.dev.prcontinue`). What the branch's reviews found must outlive any one of its PRs, so it lives here.

THE RECORD is one forge issue per branch, titled :data:`RECORD_TITLE`, found by its hidden
``Marker.BRANCH_REVIEW`` line keyed by the branch and closed at birth (it is state, never a work item). Its body
holds a versioned JSON line naming:

* ``prs`` -- every PR of the branch into integration, oldest first: the CHAIN. A PR's predecessor is the one
  before it; the predecessor's head is the LAST LANDED HEAD, which a continuation's review scope starts at
  (:func:`dev_lab.dev.forgereview_scope.review_base`).
* ``dispositions`` -- every carried finding a session RESOLVED or DEFERRED with its reason
  (``forge review carry``, :func:`dispose`), and in which PR.

THE FINDINGS THEMSELVES ARE NOT COPIED: each PR's own review ledger
(:func:`dev_lab.dev.forgereview_advice.record_of`) is their one source, read off every predecessor in the chain.
A predecessor's finding with no disposition is OPEN (:attr:`Carried.open`): the continuation's reviewer is handed
it as context, the deferred and resolved ones as already disposed, and an open one holds ``tests/review`` at
``failure`` (:func:`dev_lab.dev.forgereview_advice.verdict`) until it is resolved or deferred.

A record is read only from an issue whose author the forge trusts (this client's login, its Actions login, or a
writer :meth:`~dev_lab.dev.forgework.Client.trusts`): an issue anyone else opens that merely looks like one is not.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace
from typing import TYPE_CHECKING, Any, Final

from dev_lab.dev.forgepulls import Marker, issues, marker
from dev_lab.dev.forgereview_advice import CARRY_DOOR, record_of, trusted_bodies

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from dev_lab.dev.forgereview_findings import Finding
    from dev_lab.dev.forgework import Client, PullRequest

__all__ = [
    'RECORD_TITLE',
    'RECORD_VERSION',
    'STATES',
    'BranchRecord',
    'Carried',
    'CarryRefused',
    'Disposition',
    'carried_after',
    'carried_for',
    'chained',
    'context',
    'dispose',
    'read_record',
    'write_record',
]  # fmt: skip

#: The record's format version; a record of another version is refused, never guessed at.
RECORD_VERSION: Final = 1

#: The record issue's title; ``{branch}`` filled.
RECORD_TITLE: Final = 'review record: {branch}'

#: How a carried finding is disposed of: fixed in the continuation, or deferred with a reason.
STATES: Final = ('resolved', 'deferred')

_LINE: Final = re.compile(r'<!-- branch-review (?P<json>\{.*?\}) -->', re.DOTALL)


class CarryRefused(ValueError):
    """A disposition the record cannot take: an unknown finding, a deferral with no reason, or not a continuation."""


@dataclass(frozen=True)
class Disposition:
    """What became of one carried finding: *state* (:data:`STATES`), why, and in which PR."""

    id: str
    state: str
    reason: str
    pr: int


@dataclass(frozen=True)
class BranchRecord:
    """A branch's review record: its PRs oldest first, its dispositions, and the issue holding it (0: none yet)."""

    branch: str
    prs: tuple[int, ...] = ()
    dispositions: tuple[Disposition, ...] = ()
    issue: int = 0

    def predecessors(self, number: int) -> tuple[int, ...]:
        """Every PR of the chain before *number*; none when *number* is not in it (not a continuation)."""
        return self.prs[: self.prs.index(number)] if number in self.prs else ()

    def body(self) -> str:
        """The issue body: the marker, what it is, and the JSON line (``>`` escaped so it cannot close the comment)."""
        doc = {
            'version': RECORD_VERSION, 'branch': self.branch, 'prs': list(self.prs),
            'dispositions': [asdict(one) for one in self.dispositions],
        }  # fmt: skip
        text = json.dumps(doc, ensure_ascii=False).replace('>', '\\u003e')
        chain = ' -> '.join(f'#{n}' for n in self.prs) or 'none yet'
        rows = [f'- `{one.id}` {one.state} in #{one.pr}: {one.reason or "-"}' for one in self.dispositions]
        return '\n\n'.join([
            marker(Marker.BRANCH_REVIEW, self.branch),
            f'The review record of `{self.branch}` across its PRs (LANDED-BRANCH-CONTINUES): state, not a work item.',
            f'PRs, oldest first: {chain}',
            '\n'.join(['Dispositions of carried findings:', *rows]) if rows else 'No carried finding disposed of.',
            f'<!-- branch-review {text} -->',
        ])  # fmt: skip


def _trusted(client: Client, author: str) -> bool:
    return author in {client.whoami(), client.backend.actions_login} or client.trusts(author)


def _parsed(branch: str, raw: Mapping[str, Any]) -> BranchRecord:
    found = _LINE.search(raw.get('body') or '')
    if found is None:
        return BranchRecord(branch, issue=int(raw['number']))
    doc = json.loads(found['json'])
    if doc.get('version') != RECORD_VERSION:
        msg = f'a branch review record of version {doc.get("version")!r}; this reader knows {RECORD_VERSION}'
        raise ValueError(msg)
    rows = tuple(Disposition(**row) for row in doc.get('dispositions', ()))
    return BranchRecord(branch, tuple(int(n) for n in doc.get('prs', ())), rows, int(raw['number']))


def read_record(client: Client, branch: str) -> BranchRecord:
    """*branch*'s record, off the one trusted issue carrying its marker; an empty one when none exists yet."""
    line = marker(Marker.BRANCH_REVIEW, branch)
    for raw in issues(client):
        if line in (raw.get('body') or '').split('\n') and _trusted(client, (raw.get('user') or {}).get('login', '')):
            return _parsed(branch, raw)
    return BranchRecord(branch)


def write_record(client: Client, record: BranchRecord) -> BranchRecord:
    """Write *record* into its issue (opened, then closed, when it has none); the record as held now."""
    if record.issue:
        client.issue_edit(record.issue, record.body())
        return record
    made = client.issue_create(RECORD_TITLE.format(branch=record.branch), record.body())
    client.issue_close(made.number)
    return replace(record, issue=made.number)


def chained(client: Client, branch: str, *numbers: int) -> BranchRecord:
    """*branch*'s record with *numbers* appended to its chain (each once, in order), written when it changed."""
    record = read_record(client, branch)
    grown = (*record.prs, *(n for n in dict.fromkeys(numbers) if n not in record.prs))
    return record if grown == record.prs else write_record(client, replace(record, prs=grown))


@dataclass(frozen=True)
class Carried:
    """What a continuation carries: its predecessor, the last landed head, and the predecessors' findings."""

    continues: int
    since: str  # the predecessor's head: the last landed head of the branch, where the review's scope starts
    open: tuple[Finding, ...] = ()
    settled: tuple[tuple[Finding, Disposition], ...] = ()


def _findings(client: Client, numbers: Iterable[int], reviewers: Iterable[str]) -> dict[str, Finding]:
    """``{id: finding}`` over the review ledgers of *numbers*, oldest first, so a later PR's finding wins."""
    out: dict[str, Finding] = {}
    for number in numbers:
        found = record_of(trusted_bodies(client, number, reviewers))
        out |= {one.id: one for one in (found.findings if found is not None else ())}
    return out


def carried_for(client: Client, pull: PullRequest, reviewers: Iterable[str] = ()) -> Carried | None:
    """What *pull* carries from its branch's earlier PRs; ``None`` when it continues none."""
    record = read_record(client, pull.head)
    return carried_after(client, record, record.predecessors(pull.number), reviewers)


def carried_after(
    client: Client, record: BranchRecord, before: Sequence[int], reviewers: Iterable[str] = ()
) -> Carried | None:
    """What a PR after *before* (its branch's earlier PRs in *record*, oldest first) carries; ``None`` for none."""
    if not before:
        return None
    every = _findings(client, before, tuple(reviewers))
    disposed = {one.id: one for one in record.dispositions}
    since = client.pr_view(before[-1]).head_sha
    return Carried(
        before[-1],
        since,
        tuple(one for key, one in every.items() if key not in disposed),
        tuple((one, disposed[key]) for key, one in every.items() if key in disposed),
    )


def context(carried: Carried) -> str:
    """The markdown a continuation's body and its reviewer read: the carried findings, open ones first."""
    head = f'Carried from #{carried.continues} (landed at `{carried.since[:12]}`):'
    rows = [f'- **open** `{one.id}` {one.severity} `{one.file}` -- {one.summary}' for one in carried.open]
    rows += [
        f'- {how.state} in #{how.pr} `{one.id}` `{one.file}` -- {one.summary}{f" ({how.reason})" if how.reason else ""}'
        for one, how in carried.settled
    ]
    if not rows:
        return f'{head} no findings.'
    door = CARRY_DOOR.format(pr='<this PR>')
    return '\n'.join([f'{head} every open one is resolved or deferred before merge -- `{door}`', *rows])


def dispose(
    client: Client, pull: PullRequest, finding: str, *, state: str, reason: str, reviewers: Iterable[str] = ()
) -> str:
    """Record *finding* (a carried id) as *state* in *pull*, the continuation; the line said.

    Raises:
        CarryRefused: *pull* continues no PR, *finding* is not carried, *state* is unknown, or a deferral has no
            reason.

    """
    if state not in STATES:
        msg = f'{state!r} is not a disposition; one of {", ".join(STATES)}'
        raise CarryRefused(msg)
    if state == 'deferred' and not reason.strip():
        msg = f'deferring {finding} needs a reason: an open finding is never deferred silently'
        raise CarryRefused(msg)
    carried = carried_for(client, pull, reviewers)
    if carried is None:
        msg = f'#{pull.number} continues no landed PR of {pull.head}: it carries no finding'
        raise CarryRefused(msg)
    known = {one.id for one in carried.open} | {one.id for one, _ in carried.settled}
    if finding not in known:
        msg = f'{finding} is not a finding #{pull.number} carries ({", ".join(sorted(known)) or "none"})'
        raise CarryRefused(msg)
    record = read_record(client, pull.head)
    kept = tuple(one for one in record.dispositions if one.id != finding)
    made = Disposition(finding, state, reason.strip(), pull.number)
    write_record(client, replace(record, dispositions=(*kept, made)))
    return f'#{pull.number}: {finding} {state}{f" -- {reason.strip()}" if reason.strip() else ""}'
