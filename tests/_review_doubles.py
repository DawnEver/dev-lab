"""Doubles shared by the review tests: a declared review, a finding, a findings document, a head's review state."""

from __future__ import annotations

import json

from dev_lab.dev.forgereview_declared import RANGE_FIELD, Review
from dev_lab.dev.forgereview_findings import Finding
from dev_lab.dev.forgestatus import status_list
from dev_lab.dev.platformparts import REVIEW_CONTEXT

_REVIEW = Review(command=('reviewer', '--range', RANGE_FIELD))


def _finding(fid: str = 'F-000000000001', *, severity: str = 'MEDIUM', security: bool = False,
             file: str = 'x.txt', anchor: str = 'x') -> Finding:  # fmt: skip
    return Finding(fid, severity, security, 'occams-razor', file, anchor, f'{fid} summary', 'Bug')


def _doc(*findings: Finding, **top: object) -> str:
    """A findings-output v3 document of *findings*, one ok reviewer; *top* adds top-level keys."""
    rows = [
        {'id': one.id, 'severity': one.severity, 'security': one.security, 'rule': one.rule, 'file': one.file,
         'anchor': one.anchor, 'summary': one.summary, 'category': one.category, 'status': 'OPEN',
         'suggestion': '', 'detail': '', 'confidence': 'single', 'reviewers': [{'name': 'c', 'provider': 'p'}]}
        for one in findings
    ]  # fmt: skip
    return json.dumps({
        'schema_version': 3, 'range': 'a..b', 'profiles': ['c'],
        'reviewers': [{'name': 'c', 'provider': 'p', 'status': 'ok', 'dropped_findings': 0}], 'findings': rows, **top,
    })  # fmt: skip


def _state(forge: object, sha: str) -> tuple[str, str]:
    """*sha*'s latest ``tests/review`` as ``(state, description)``."""
    latest = next(one for one in status_list(forge, sha) if one.context == REVIEW_CONTEXT)
    return latest.state, latest.description
