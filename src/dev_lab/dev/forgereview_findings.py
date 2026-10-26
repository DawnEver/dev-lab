"""The findings JSON a declared review command prints: read at a KNOWN ``schema_version`` only, else refused by name.

The format is the sharp-review method's findings output (``findings-output.schema.json``, owned by ai-lab's
packaged method, not here): one review run's merged result -- the range, the profiles that ran, every planned
reviewer with its status, and the deduplicated findings, each TAGGED (``severity``, ``security``, ``rule``) under
an id stable across rounds (a hash of rule, file and anchor line). This reader checks what the forge relies on (the
version, the required fields, the closed vocabularies) and builds frozen records; it never guesses at a
version it does not know (:class:`UnknownSchemaVersion`), because a renamed field or a new status is exactly
what a reader of the old version would misread.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    'REVIEWER_STATUSES',
    'SCHEMA_VERSIONS',
    'SEVERITIES',
    'Finding',
    'Findings',
    'FindingsInvalid',
    'Reviewer',
    'UnknownSchemaVersion',
    'merge_outputs',
    'parse_findings',
]  # fmt: skip

#: The ``schema_version`` values this reader knows.
SCHEMA_VERSIONS: Final = frozenset({3})

#: A reviewer's status: ``ok`` contributed findings; the rest name why it did not.
REVIEWER_STATUSES: Final = frozenset(
    {'ok', 'exhausted', 'auth', 'rate_limit', 'timeout', 'unsupported', 'unavailable', 'skipped'}
)

#: A finding's severity, most severe first: ``HIGH`` blocks the merge, the rest never do.
SEVERITIES: Final = ('HIGH', 'MEDIUM', 'LOW')

_TOP: Final = ('schema_version', 'range', 'profiles', 'reviewers', 'findings')
_REVIEWER: Final = ('name', 'provider', 'status', 'dropped_findings')
_FINDING: Final = (
    'id', 'severity', 'security', 'rule', 'file', 'anchor', 'summary', 'category', 'status', 'suggestion', 'detail',
    'confidence', 'reviewers',
)  # fmt: skip


class FindingsInvalid(ValueError):
    """The command's output is not the findings JSON: what is wrong is named."""


class UnknownSchemaVersion(FindingsInvalid):
    """The output declares a ``schema_version`` this reader does not know; it is refused, never guessed at."""


@dataclass(frozen=True)
class Reviewer:
    """One planned reviewer: its profile key, the provider that ran it (or could not), its status."""

    name: str
    provider: str | None
    status: str
    dropped_findings: int


@dataclass(frozen=True)
class Finding:
    """One deduplicated, tagged finding and the reviewers (``name@provider``) that reported it.

    *id* is stable across rounds: the same rule, file and anchor line is the same finding.
    """

    id: str
    severity: str
    security: bool
    rule: str
    file: str
    anchor: str
    summary: str
    category: str
    suggestion: str = ''
    detail: str = ''
    confidence: str = ''
    reviewers: tuple[str, ...] = ()

    @property
    def blocking(self) -> bool:
        """Whether, while open, it blocks the merge: a ``HIGH`` or a security finding."""
        return self.severity == 'HIGH' or self.security


@dataclass(frozen=True)
class Findings:
    """One review run's merged result."""

    schema_version: int
    range: str
    profiles: tuple[str, ...]
    reviewers: tuple[Reviewer, ...]
    findings: tuple[Finding, ...]


def _fields(row: object, required: tuple[str, ...], where: str) -> dict[str, Any]:
    if not isinstance(row, dict):
        msg = f'{where} is not a JSON object'
        raise FindingsInvalid(msg)
    if missing := [key for key in required if key not in row]:
        msg = f'{where} lacks {missing}'
        raise FindingsInvalid(msg)
    return row


def _one_of(value: object, allowed: frozenset[str] | tuple[str, ...], where: str) -> str:
    if value not in allowed:
        msg = f'{where} is {value!r}, not one of {sorted(allowed)}'
        raise FindingsInvalid(msg)
    return str(value)


def _reviewer(row: object, at: int) -> Reviewer:
    got = _fields(row, _REVIEWER, f'reviewers[{at}]')
    status = _one_of(got['status'], REVIEWER_STATUSES, f'reviewers[{at}].status')
    return Reviewer(str(got['name']), got['provider'], status, int(got['dropped_findings']))


def _finding(row: object, at: int) -> Finding:
    got = _fields(row, _FINDING, f'findings[{at}]')
    by = tuple(f'{one["name"]}@{one["provider"]}' for one in got['reviewers'])
    if not isinstance(got['security'], bool):
        msg = f'findings[{at}].security is {got["security"]!r}, not a boolean'
        raise FindingsInvalid(msg)
    return Finding(
        str(got['id']), _one_of(got['severity'], SEVERITIES, f'findings[{at}].severity'), got['security'],
        str(got['rule']), str(got['file']), str(got['anchor']), str(got['summary']), str(got['category']),
        str(got['suggestion']), str(got['detail']), str(got['confidence']), by,
    )  # fmt: skip


def parse_findings(text: str) -> Findings:
    """The :class:`Findings` *text* holds; :class:`UnknownSchemaVersion` / :class:`FindingsInvalid` naming why not."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as bad:
        msg = f'the review command printed no findings JSON: {bad}'
        raise FindingsInvalid(msg) from None
    if not isinstance(raw, dict) or 'schema_version' not in raw:
        msg = 'the review output has no schema_version'
        raise FindingsInvalid(msg)
    if (version := raw['schema_version']) not in SCHEMA_VERSIONS:
        msg = f'the review output is findings schema_version {version!r}; this reader knows {sorted(SCHEMA_VERSIONS)}'
        raise UnknownSchemaVersion(msg)
    got = _fields(raw, _TOP, 'the review output')
    return Findings(
        version, str(got['range']), tuple(map(str, got['profiles'])),
        tuple(_reviewer(row, at) for at, row in enumerate(got['reviewers'])),
        tuple(_finding(row, at) for at, row in enumerate(got['findings'])),
    )  # fmt: skip


def merge_outputs(texts: Sequence[str], range_: str) -> str:
    """ONE findings document of the slice outputs *texts* over *range_*: reviewers in order, findings once by id.

    Each output is read first (:func:`parse_findings`), so a slice printing an unknown version is refused here.
    """
    for text in texts:
        parse_findings(text)
    docs = [json.loads(text) for text in texts]
    findings = {row['id']: row for doc in docs for row in doc['findings']}
    merged = {
        'schema_version': docs[0]['schema_version'], 'range': range_,
        'profiles': list(dict.fromkeys(name for doc in docs for name in doc['profiles'])),
        'reviewers': [row for doc in docs for row in doc['reviewers']], 'findings': list(findings.values()),
    }  # fmt: skip
    return json.dumps(merged, ensure_ascii=False)
