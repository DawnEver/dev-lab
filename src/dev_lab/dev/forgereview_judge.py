"""REVIEW JUDGEMENT: each open finding is RE-JUDGED by an independent reviewer; a claim is ADJUDICATED, never obeyed.

User ruling 2026-10-31: humans take no part in daily maintenance, and an author never clears a review's block on its
own work. So:

* EVERY ROUND re-judges each open finding of the ledger against the new head (:func:`judge`): ``fixed`` (with the
  evidence), ``false-positive`` (with the code or test that proves it), or ``present``. The first two close it; the
  text is never merely carried over (:func:`dev_lab.dev.forgereview_rounds.advance`).
* ``forge review dispose <number> <id> --why`` records a CLAIM (:func:`claim`) and changes no status. The claim is
  ADJUDICATED (:func:`adjudicate`) by the same independent judge over just that finding, the claim and the code it
  cites: UPHELD closes the finding, REJECTED keeps it blocking, and the reason is posted either way.
* SEPARATION OF DUTIES: every claim and adjudication record names its :class:`Identity` (login, host, session). An
  adjudication by the claimant's own session is refused, and no round or adjudication run by a session that
  authored the head may post a review at all (:func:`self_review`): the status reaches ``success`` only from a
  reviewer that is not the head's author.

The SAME functions serve a PR and a PR-less head's ledger issue (:func:`dev_lab.dev.forgetakeover.ledger_of`): the
thread is a number either way. The judge is the method's (``[tool.dev_lab.review] judge``, the family's
:data:`FAMILY_JUDGE`: ai-lab's ``ai_lab.review.judge``), run on this host like the review command.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from dev_lab.dev.forgepulls import Marker, comment_upsert, marker
from dev_lab.dev.labsession import ENV as SESSION_ENV
from dev_lab.dev.principles import payload

if TYPE_CHECKING:
    from dev_lab.dev.forgereview_findings import Finding
    from dev_lab.dev.forgework import Client

__all__ = [
    'CLOSING',
    'OUTCOMES',
    'AdjudicationRefused',
    'Claim',
    'Identity',
    'Judge',
    'Verdict',
    'adjudication_text',
    'claim',
    'claims',
    'identity',
    'judge',
    'pending',
    'self_review',
    'upheld',
]

#: What a judge may say of one finding.
OUTCOMES: Final = ('fixed', 'false-positive', 'present')

#: The outcomes that close a finding.
CLOSING: Final = frozenset({'fixed', 'false-positive'})

#: The schema version of the judge's stdout this reader knows.
_JUDGE_VERSION: Final = 1

_MIN_WHY: Final = 12


class AdjudicationRefused(ValueError):
    """A claim or an adjudication this door will not record, and why."""


@dataclass(frozen=True)
class Identity:
    """Who acts: the forge login, the host, and the agent session (``LAB_SESSION``; ``''`` for the forge itself)."""

    login: str
    host: str
    session: str = ''

    def text(self) -> str:
        """``login@host`` and the session when there is one -- as every record names it."""
        return f'{self.login}@{self.host}' + (f' session {self.session}' if self.session else '')


def identity(client: Client, host: str, env: Mapping[str, str] | None = None) -> Identity:
    """The :class:`Identity` this process acts as on *client*'s forge."""
    return Identity(client.whoami(), host, (os.environ if env is None else env).get(SESSION_ENV, ''))


@dataclass(frozen=True)
class Verdict:
    """The judge's word on one finding: its outcome and the evidence it cites."""

    id: str
    outcome: str
    evidence: str


#: How a round or an adjudication asks the judge: ``(finding, claim)`` pairs in, one :class:`Verdict` per id out.
Judge = Callable[[Sequence[tuple['Finding', str]]], Mapping[str, Verdict]]


def judge(
    argv: Sequence[str], items: Sequence[tuple[Finding, str]], run: Callable[[Sequence[str], Path], str], root: Path,
    *, findings_field: str, principles_field: str,
) -> dict[str, Verdict]:  # fmt: skip
    """The judge command *argv* (its host values filled) over *items*; a finding it did not answer stays ``present``.

    *findings_field* and *principles_field* are the placeholders the command names its two files by.
    """
    if not items:
        return {}
    with tempfile.TemporaryDirectory() as scratch:
        given = Path(scratch) / 'findings.json'
        rows = [{**asdict(one), 'reviewers': list(one.reviewers), 'claim': why} for one, why in items]
        given.write_text(json.dumps({'findings': rows}, ensure_ascii=False), encoding='utf-8')
        principles = Path(scratch) / 'principles.json'
        principles.write_text(json.dumps(payload()), encoding='utf-8')
        filled = [arg.replace(findings_field, str(given)).replace(principles_field, str(principles)) for arg in argv]
        out = json.loads(run(filled, root))
    if out.get('schema_version') != _JUDGE_VERSION:
        msg = f'the judge printed schema_version {out.get("schema_version")!r}; this reader knows {_JUDGE_VERSION}'
        raise ValueError(msg)
    said = {
        row['id']: Verdict(row['id'], row['outcome'], str(row.get('evidence', '')))
        for row in out.get('verdicts', [])
        if row.get('outcome') in OUTCOMES
    }
    return {one.id: said.get(one.id, Verdict(one.id, 'present', 'not judged')) for one, _ in items}


# --- claims and adjudications: one keyed comment each, on the PR or the ledger issue -----------------------

_CLAIM: Final = re.compile(
    re.escape(marker(Marker.CLAIM, 'KEY')).replace('KEY', r'(?P<key>\S+)')
    + r'\n\*\*Claim\*\* `(?P<id>[^`]+)` by (?P<login>\S+)@(?P<host>\S+?)(?: session (?P<session>\S+))?: (?P<why>.+)$',
    re.MULTILINE,
)
_ADJUDICATED: Final = re.compile(
    re.escape(marker(Marker.ADJUDICATION, 'KEY')).replace('KEY', r'(?P<key>\S+)')
    + r'\n\*\*Adjudicated\*\* `(?P<id>[^`]+)` (?P<ruling>upheld|rejected) \(claim (?P<digest>[0-9a-f]{12})\)'
    r' by (?P<by>[^:]+): (?P<evidence>.+)$',
    re.MULTILINE,
)


@dataclass(frozen=True)
class Claim:
    """An author's argument that a finding is not a defect: who made it, and why."""

    id: str
    why: str
    by: Identity

    @property
    def digest(self) -> str:
        """The claim's identity in its adjudication: a re-worded claim is a new claim, adjudicated anew."""
        return hashlib.sha256(f'{self.id}\n{self.why}'.encode()).hexdigest()[:12]


def claims(bodies: Sequence[str]) -> dict[str, Claim]:
    """``{finding id: its newest claim}`` the thread *bodies* (oldest first) carry."""
    out: dict[str, Claim] = {}
    for body in bodies:
        if (found := _CLAIM.search(body)) is not None and found['key'] == found['id']:
            who = Identity(found['login'], found['host'], found['session'] or '')
            out[found['id']] = Claim(found['id'], found['why'], who)
    return out


def _adjudications(bodies: Sequence[str]) -> dict[str, re.Match[str]]:
    return {
        found['id']: found
        for body in bodies
        if (found := _ADJUDICATED.search(body)) is not None and found['key'] == found['id']
    }


def upheld(bodies: Sequence[str]) -> dict[str, str]:
    """``{finding id: evidence}`` of every claim an independent adjudicator UPHELD: those findings are closed."""
    return {fid: found['evidence'] for fid, found in _adjudications(bodies).items() if found['ruling'] == 'upheld'}


def pending(bodies: Sequence[str]) -> dict[str, Claim]:
    """The claims no adjudication answers yet (a re-worded claim is pending again)."""
    done = _adjudications(bodies)
    return {fid: one for fid, one in claims(bodies).items() if fid not in done or done[fid]['digest'] != one.digest}


def claim(client: Client, number: int, finding_id: str, why: str, *, by: Identity, open_ids: Sequence[str]) -> str:
    """Record *by*'s claim against *finding_id* on thread *number*; NO status changes. The line said."""
    if len(why.strip()) < _MIN_WHY:
        msg = f'a claim needs its argument: --why "<at least {_MIN_WHY} characters>"'
        raise AdjudicationRefused(msg)
    if finding_id not in open_ids:
        msg = f'{finding_id} is not open on #{number} (open: {", ".join(open_ids) or "none"})'
        raise AdjudicationRefused(msg)
    text = f'**Claim** `{finding_id}` by {by.text()}: {" ".join(why.split())}'
    comment_upsert(client, number, kind=Marker.CLAIM, key=finding_id, text=text)
    return f'#{number}: claim on {finding_id} recorded by {by.text()}; an independent reviewer adjudicates it'


def adjudication_text(one: Claim, verdict: Verdict, adjudicator: Identity) -> str:
    """The body of an adjudication comment (after its marker): the ruling, both parties, and the evidence."""
    ruling = 'upheld' if verdict.outcome in CLOSING else 'rejected'
    evidence = ' '.join(f'{verdict.outcome}: {verdict.evidence} (claimed by {one.by.text()})'.split())
    return f'**Adjudicated** `{one.id}` {ruling} (claim {one.digest}) by {adjudicator.text()}: {evidence}'


def self_review(reviewer: Identity, authors: frozenset[str], what: str) -> None:
    """Refuse when *reviewer*'s session authored the head under review: an author never clears its own block."""
    if reviewer.session and reviewer.session in authors:
        msg = (
            f'{what}: session {reviewer.session} authored this head, so it may not review it or rule on its claims; '
            'the forge, or another session, does'
        )
        raise AdjudicationRefused(msg)


def adjudicate(
    client: Client, number: int, open_findings: Sequence[Finding], bodies: Sequence[str], *, judged: Judge,
    adjudicator: Identity, authors: frozenset[str],
) -> list[str]:  # fmt: skip
    """Adjudicate every pending claim on thread *number* against its open finding; one comment each. The lines said.

    Refused outright when *adjudicator* authored the head; a claim the adjudicator's own session made is refused
    by name and left pending for another reviewer.
    """
    self_review(adjudicator, authors, f'adjudicating #{number}')
    findings = {one.id: one for one in open_findings}
    asked = {fid: one for fid, one in pending(bodies).items() if fid in findings}
    lines, items = [], []
    for fid, one in asked.items():
        if adjudicator.session and one.by.session == adjudicator.session:
            lines.append(f'#{number} {fid}: refused -- the claimant session {one.by.session} may not adjudicate it')
            continue
        items.append((findings[fid], one.why))
    for fid, verdict in judged(items).items():
        text = adjudication_text(asked[fid], verdict, adjudicator)
        comment_upsert(client, number, kind=Marker.ADJUDICATION, key=fid, text=text)
        lines.append(f'#{number} {fid}: {text.split("`", 2)[2].split(" by ", 1)[0].strip()}')
    return lines
