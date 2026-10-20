"""THE KIT'S OWN CHECKOUT ADOPTS THE KIT: every hook stage this repo declares is installed here.

The set is PINNED rather than read back from the table: :func:`assert_stages_are_declared` compares the
merged table AGAINST this pin, both directions red.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lab_commons.dev.famtests.hookinstall import (
    assert_a_foreign_hook_is_not_installed,
    assert_declared_hooks_are_installed,
    assert_hooks_dir_is_the_one_git_consults,
    assert_stages_are_declared,
    assert_the_guard_can_go_both_ways,
)

#: THE TREE UNDER TEST, not the working directory.
_ROOT = Path(__file__).resolve().parents[1]

#: The family base declares pre-commit and commit-msg; this repo's layer adds the pre-push admission.
_DECLARED_STAGES = frozenset({'commit-msg', 'pre-commit', 'pre-push'})


def test_the_declared_set_is_what_this_repo_pinned() -> None:
    assert_stages_are_declared(root=_ROOT, declared_stages=_DECLARED_STAGES)


@pytest.mark.workstation
def test_every_hook_this_repository_declares_is_installed() -> None:
    assert_declared_hooks_are_installed(root=_ROOT)


@pytest.mark.workstation
def test_the_hooks_directory_is_the_one_git_will_consult() -> None:
    assert_hooks_dir_is_the_one_git_consults(root=_ROOT)


def test_this_guard_can_go_both_ways(tmp_path: Path) -> None:
    assert_the_guard_can_go_both_ways(root=_ROOT, scratch=tmp_path)


def test_somebody_elses_hook_is_its_own_finding(tmp_path: Path) -> None:
    assert_a_foreign_hook_is_not_installed(root=_ROOT, scratch=tmp_path)
