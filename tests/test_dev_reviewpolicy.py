"""REVIEW-POLICY: one export of the family review policy, read by both triggers and by the forge review itself."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev_lab.dev import reviewpolicy
from dev_lab.dev.forgereview import load_review
from dev_lab.dev.forgereview_findings import Finding
from dev_lab.dev.forgereview_scope import CODE, NOT_CODE
from dev_lab.dev.principles import payload
from dev_lab.dev.reviewpolicy import policy


def _finding(severity: str, *, security: bool = False) -> Finding:
    return Finding('SR-1', severity, security, 'r', 'f.py', 'a', 's', 'c', '', '', 'high')


def test_the_schema_is_pinned(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--json --repo`` prints exactly the named keys, family defaults for a repo with no manifest."""
    assert reviewpolicy.main(['--json', '--repo', str(tmp_path)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed == {
        'schema': 1,
        'principles': payload()['principles'],
        'code': list(CODE),
        'not_code': list(NOT_CODE),
        'max_total_bytes': 4_000_000,
        'max_file_bytes': 200_000,
        'blocking': ['HIGH', 'security'],
        'summary': {'cite': ['commits', 'memory', 'merge_audit', 'pr_body']},
    }


def test_a_repo_override_overlays_the_family_defaults(tmp_path: Path) -> None:
    """``[tool.dev_lab.review]`` replaces only what it declares; the rest stays the family's."""
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.dev_lab.review]\ncode = ["**/*.py"]\nmax_total_bytes = 7\nmax_diff_bytes = 3\n', encoding='utf-8'
    )
    got = policy(tmp_path)
    assert (got['code'], got['max_total_bytes'], got['max_file_bytes']) == (['**/*.py'], 7, 3)
    assert got['not_code'] == list(NOT_CODE)  # planted control: an undeclared key stays the family's


def test_the_forge_review_and_the_export_agree(tmp_path: Path) -> None:
    """The bounds the forge review cuts by and the severities it blocks on are the exported ones."""
    (tmp_path / 'pyproject.toml').write_text('[tool.dev_lab.review]\nnot_code = ["x/**"]\n', encoding='utf-8')
    got, budget = policy(tmp_path), load_review(tmp_path).budget
    assert (got['code'], got['not_code']) == (list(budget.code), list(budget.not_code))
    assert (got['max_total_bytes'], got['max_file_bytes']) == (budget.total_bytes, budget.slice_bytes)
    assert _finding('HIGH').blocking
    assert _finding('LOW', security=True).blocking
    assert not _finding('MEDIUM').blocking  # planted control: a non-blocking severity does not block
    assert 'MEDIUM' not in got['blocking']


def test_an_unknown_override_is_refused(tmp_path: Path) -> None:
    """A key the review does not know is refused, not exported."""
    (tmp_path / 'pyproject.toml').write_text('[tool.dev_lab.review]\nbogus = 1\n', encoding='utf-8')
    with pytest.raises(ValueError, match='bogus'):
        policy(tmp_path)
