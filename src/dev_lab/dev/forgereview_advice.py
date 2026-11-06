"""PR-REVIEW-IS-ONE-SHOT-ADVICE: a PR's review is ONE independent acceptance check, and its findings are advice.

User rulings 2026-11-06: "Our PR review should only be a small-scale independent acceptance check with suggestions"
and "one session maintains one task, one PR". So:

* A PR is reviewed ONCE, at its first ready head (:mod:`dev_lab.dev.forgereview`). A fix push, a sync with
  integration, or any later head is NOT reviewed again: the review stands, recorded as a :class:`Record` in its one
  comment (a hidden ``review-ledger`` line). It is reviewed again only when the PR's own change has grown
  :data:`~dev_lab.dev.forgereview.REVIEW_AGAIN_GROWTH` times since, or when a session asks (``forge review again``).
* EVERY FINDING IS ADVICE except a SECURITY finding (:attr:`~dev_lab.dev.forgereview_findings.Finding.blocking`):
  ``tests/review`` is ``success`` once the review has run, its description counting the advice by severity. An
  open security finding is ``failure`` naming it; the author fixes it and asks for the review again.
* The comment opens with what the PR does (:mod:`dev_lab.dev.forgereview_summary`), then the verdict, the context,
  the code the budget left unread, and the findings. Acting on advice is the author's call, inside the same PR:
  a PR is never split for its review.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Final

from dev_lab.dev._forgebackends import GITEA
from dev_lab.dev.forgepulls import Marker, comment_list, comment_upsert, marker
from dev_lab.dev.forgereview_findings import SEVERITIES, Finding, Findings
from dev_lab.dev.forgereview_identity import ruling, self_review
from dev_lab.dev.forgereview_summary import context_summary, repo_url, what_it_does
from dev_lab.dev.reviewbudget import raise_record
from dev_lab.dev.reviewgate import post_review

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

    from dev_lab.dev._forgebackends import Backend
    from dev_lab.dev.forgereview_identity import Identity
    from dev_lab.dev.forgework import Client, PullRequest

__all__ = [
    'AGAIN_DOOR',
    'LEDGER_VERSION',
    'ONE_SHOT',
    'Record',
    'post_review_comment',
    'record_of',
    'recorded_usd',
    'render',
    'review_record',
    'trusted_bodies',
    'verdict',
]  # fmt: skip

#: The record's format version; a record of another version is refused, never guessed at.
LEDGER_VERSION: Final = 1

#: The door a session asks for the PR to be reviewed again through (a security finding fixed); ``{pr}`` filled.
AGAIN_DOOR: Final = 'python -m dev_lab.dev.forge review again {pr}'

#: The rule every review comment states: what the review is, and what it never asks for.
ONE_SHOT: Final = (
    'This review is a one-shot independent acceptance check: its findings are advice, and only a security finding '
    'holds the merge. One session, one task, one PR -- act on the advice in this PR, never split it for the review.'
)

_LEDGER: Final = re.compile(r'<!-- review-ledger (?P<json>\{.*?\}) -->', re.DOTALL)
_REVIEW: Final = re.compile(re.escape(marker(Marker.REVIEW, 'SHA')).replace('SHA', '[0-9a-f]{7,40}'))
_DESCRIPTION: Final = 240  # a commit-status description is short


@dataclass(frozen=True)
class Record:
    """One review's record: the head it reviewed, its findings, what it spent, and the PR's code bytes then."""

    head: str
    findings: tuple[Finding, ...] = ()
    usd: float = 0.0  # what this review spent, measured on the host that ran it (:func:`recorded_usd` sums them)
    size: int = 0  # the PR's own reviewable code bytes at *head*: what growth is measured against; 0 unknown

    def line(self) -> str:
        """The hidden comment line that records this review (``>`` escaped, so the JSON cannot close the comment)."""
        doc = {
            'version': LEDGER_VERSION, 'head': self.head, 'open': [asdict(one) for one in self.findings],
            'usd': self.usd, 'size': self.size,
        }  # fmt: skip
        text = json.dumps(doc, ensure_ascii=False).replace('>', '\\u003e')
        return f'<!-- review-ledger {text} -->'


def trusted_bodies(client: Client, number: int, reviewers: Iterable[str] = ()) -> list[str]:
    """PR *number*'s comment bodies (oldest first) the forge records as written by THIS client's login.

    A review record is state the forge writes; a comment anyone else writes that merely LOOKS like one is never
    read as one. On GitHub the review is written by the workflow job token, so the forge's ``actions_login`` is
    trusted too. A record posted by another review producer is read only from a DECLARED reviewer login
    (*reviewers*, the base's ``[tool.dev_lab.review] reviewers``), and contributes its marker and record alone
    (:func:`review_record`). A cap RAISE (:func:`~dev_lab.dev.reviewbudget.raise_record`) is read from its author
    only when the forge trusts that author (:meth:`Client.trusts`).
    """
    trusted = {client.whoami(), client.backend.actions_login}
    producers = set(reviewers) - trusted
    out = []
    for comment in comment_list(client, number):
        if comment.author in trusted:
            out.append(comment.body)
        elif ((record := raise_record(comment.body, comment.author)) and client.trusts(comment.author)) or (
            comment.author in producers and (record := review_record(comment.body))
        ):
            out.append(record)
    return out


def review_record(body: str) -> str | None:
    """The record alone in a ``Marker.REVIEW`` comment *body*: its marker line and its ledger line, else ``None``."""
    first = body.split('\n', 1)[0].strip()
    if not _REVIEW.fullmatch(first) or (match := _LEDGER.search(body)) is None:
        return None
    return f'{first}\n{match.group(0)}'


def _doc(text: str) -> dict[str, Any]:
    found = json.loads(text)
    if found.get('version') != LEDGER_VERSION:
        msg = f'a review record of version {found.get("version")!r}; this reader knows {LEDGER_VERSION}'
        raise ValueError(msg)
    return found


def record_of(bodies: Iterable[str]) -> Record | None:
    """The newest review :class:`Record` the PR comment *bodies* (oldest first) carry, else ``None``."""
    found = None
    for body in bodies:
        if (match := _LEDGER.search(body)) is not None:
            found = _doc(match['json'])
    if found is None:
        return None
    rows = tuple(Finding(**{**row, 'reviewers': tuple(row.get('reviewers', ()))}) for row in found['open'])
    return Record(found['head'], rows, float(found.get('usd', 0.0)), int(found.get('size', 0)))


def recorded_usd(bodies: Iterable[str]) -> float:
    """What the PR's recorded reviews spent: each head's newest record in *bodies*, summed over heads.

    The ONE source of a PR's spend (review spend 2026-11-03): every host's review lands on the PR, so a host reads
    what the others spent, never its own local ledger alone.
    """
    per_head: dict[str, float] = {}
    for body in bodies:
        for match in _LEDGER.finditer(body):
            found = _doc(match['json'])
            per_head[found['head']] = float(found.get('usd', 0.0))
    return sum(per_head.values())


def verdict(record: Record, number: int) -> tuple[str, str]:
    """The ``(state, description)`` of ``tests/review`` for *record*: ``failure`` only on a security finding."""
    held = [one.id for one in record.findings if one.blocking]
    if held:
        door = AGAIN_DOOR.format(pr=number)
        return 'failure', f'security finding(s) {", ".join(held)}: fix them, then {door}'
    counts = ', '.join(f'{sum(one.severity == level for one in record.findings)} {level}' for level in SEVERITIES)
    return 'success', f'reviewed {record.head[:12]}: advice {counts}; none blocks'


def _row(one: Finding) -> str:
    tags = f'**{one.severity}**{" **security**" if one.security else ""}'
    by = f'; by {", ".join(one.reviewers)}' if one.reviewers else ''
    lines = [f'- {tags} `{one.file}` -- {one.summary} (`{one.id}`, rule `{one.rule}`{by})']
    lines.append(f'  - anchor: `{one.anchor.strip()}`')
    if one.suggestion:
        lines.append(f'  - suggestion: {one.suggestion}')
    return '\n'.join(lines)


def render(
    record: Record, *, number: int, reviewed: str, found: Findings, summary: str = '', outside: int = 0,
    unread: Sequence[str] = (), repo: str = '', backend: Backend = GITEA,
) -> str:  # fmt: skip
    """The review's one PR comment: what the PR does, the verdict, the context, what was not read, the findings.

    *repo* is the web root the summary's cites link into, in *backend*'s forms.
    """
    state, said = verdict(record, number)
    does = what_it_does(found.summary, repo, record.head, backend)
    head = f'**Review** of `{record.head[:12]}` over `{reviewed}`'
    parts = [*([does] if does else []), f'{head}\n\n`tests/review` {state}: {said}\n\n{ONE_SHOT}']
    if summary:
        parts.append(summary)
    if outside:
        parts.append(f'{outside} non-code file(s) outside the review scope (prose, data, locks): not read')
    if unread:
        parts.append(f'Past the review budget, not read ({len(unread)}): ' + ', '.join(f'`{p}`' for p in unread))
    who = ', '.join(f'`{one.name}` ({one.provider or "-"}): {one.status}' for one in found.reviewers) or 'none'
    parts.append(f'Reviewers: {who}')
    order = sorted(record.findings, key=lambda one: SEVERITIES.index(one.severity))
    sections = (
        ('Security (holds the merge)', [_row(one) for one in order if one.blocking]),
        ('Advice', [_row(one) for one in order if not one.blocking]),
    )
    parts += [f'### {title}\n' + '\n'.join(rows) for title, rows in sections if rows]
    if not record.findings:
        parts.append('No findings.')
    parts.append(record.line())
    return '\n\n'.join(parts)


def post_review_comment(
    root: Path, client: Client, pull: PullRequest, reviewed: str, *, found: Findings, reviewer: Identity,
    authors: frozenset[str], by: str = 'review', outside: int = 0, unread: Sequence[str] = (), usd: float = 0.0,
    size: int = 0, advisory: bool = False,
) -> str:  # fmt: skip
    """Post *pull*'s review: its comment and ``tests/review``; the line said.

    *reviewer* may not be a session in *authors* (the head's). *by* names who reviewed, for the status. *outside*
    counts the changed files that are not code, *unread* the code past the budget, both said in the comment. *usd*
    and *size* are recorded. Only the forge (:func:`ruling`) posts the status; an
    *advisory* review (the takeover door, D11) posts the comment alone, and says so.
    """
    if not advisory:
        ruling(reviewer, f'reviewing #{pull.number}')
    self_review(reviewer, authors, f'reviewing #{pull.number}')
    head = pull.head_sha
    record = Record(head, found.findings, usd, size)
    text = render(record, number=pull.number, reviewed=reviewed, found=found,
                  summary=context_summary(root, reviewed, pull.body), outside=outside, unread=unread,
                  repo=repo_url(pull.url), backend=client.backend)  # fmt: skip
    if advisory:
        text += f"\n\n**Takeover** by {reviewer.text()}: a session's review -- it posts no status."
    _, comment = comment_upsert(client, pull.number, kind=Marker.REVIEW, key=head, text=text)
    state, said = verdict(record, pull.number)
    if advisory:
        return f'#{pull.number} {head[:12]}: {by}, advisory (no status): {said}'
    post_review(client, head, state=state, target_url=comment.url if comment else '',
                description=f'{by}: {said}'[:_DESCRIPTION])  # fmt: skip
    return f'#{pull.number} {head[:12]}: {by}, {state}: {said}'
