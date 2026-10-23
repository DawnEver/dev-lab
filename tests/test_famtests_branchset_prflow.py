"""A repo that has not declared the one flow keeps a hand merge admissible, so the declarations ARE the rule.

PLANTED control on a manifest written by hand: each missing declaration is named, and the same manifest
with both supplied passes and hands the sha back.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.dev.famtests.branchset import BranchSetViolation, assert_the_pr_flow_is_declared

_BRANCHSET = "[tool.lab_commons.branchset]\ntrunk = 'main'\nsessions = ['integrate/main']\n"


def _manifest(root: Path, text: str) -> Path:
    (root / 'pyproject.toml').write_text(text, encoding='utf-8')
    return root


def test_a_repo_with_no_branch_set_is_told_the_two_lines_to_add(tmp_path: Path) -> None:
    _manifest(tmp_path, "[project]\nname = 'x'\n")
    with pytest.raises(BranchSetViolation, match="sessions = \\['integrate/main'\\]"):
        assert_the_pr_flow_is_declared(root=tmp_path)


def test_each_missing_declaration_is_named(tmp_path: Path) -> None:
    """An omitted ``ephemeral`` is the family ``pr/*`` default; only ``ephemeral = []`` turns the flow off."""
    off = _BRANCHSET + 'ephemeral = []\n' + "[tool.lab_commons.integrator]\nintegration = 'integrate/main'\n"
    _manifest(tmp_path, off)
    with pytest.raises(BranchSetViolation) as refused:
        assert_the_pr_flow_is_declared(root=tmp_path)
    assert 'pr_merges_since' in str(refused.value)
    assert 'ephemeral = [] turns off' in str(refused.value)


def test_the_same_manifest_with_both_declarations_passes_and_hands_the_sha_back(tmp_path: Path) -> None:
    """PLANTED control: the manifest above, with the two lines it was told to add."""
    _declared = (
        "ephemeral = ['pr/*']\n"
        '[tool.lab_commons.integrator]\n'
        "integration = 'integrate/main'\n"
        "pr_merges_since = 'abc123'\n"
    )
    _manifest(tmp_path, _BRANCHSET + _declared)
    assert assert_the_pr_flow_is_declared(root=tmp_path) == 'abc123'
