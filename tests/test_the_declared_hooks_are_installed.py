"""THE KIT'S OWN CHECKOUT ADOPTS THE KIT: every hook this repo declares is installed here.

Until 2026-09-23 lab-commons published :mod:`lab_commons.dev.famtests.hookinstall` and three sibling
repos adopted it, while the repo that publishes it had no adoption of its own -- the shape every other
finding in this family has. This file is that adoption; the three facts only this repo can answer are
its root, its configuration name, and the NAMED SET of stages it declares.

The set is PINNED rather than read back from the configuration: :func:`assert_stages_are_declared`
compares the configuration AGAINST this pin, both directions red, and a pin read from the thing it
checks would agree with every change.
"""

from __future__ import annotations

from pathlib import Path

from lab_commons.dev.famtests.hookinstall import (
    assert_a_foreign_hook_is_not_installed,
    assert_declared_hooks_are_installed,
    assert_hooks_dir_is_the_one_git_consults,
    assert_stages_are_declared,
    assert_the_guard_can_go_both_ways,
    assert_the_remedy_is_derived,
)
from lab_commons.dev.hook_install import DEFAULT_CONFIG_NAME

#: THE TREE UNDER TEST, not the working directory.
_ROOT = Path(__file__).resolve().parents[1]

#: The named set this repo's rendered `.pre-commit-config.yaml` declares.
_DECLARED_STAGES = frozenset({'commit-msg', 'pre-commit'})


def test_the_declared_set_is_what_this_repo_pinned() -> None:
    assert_stages_are_declared(root=_ROOT, config_name=DEFAULT_CONFIG_NAME, declared_stages=_DECLARED_STAGES)


def test_every_hook_this_repository_declares_is_installed() -> None:
    assert_declared_hooks_are_installed(root=_ROOT, config_name=DEFAULT_CONFIG_NAME)


def test_the_hooks_directory_is_the_one_git_will_consult() -> None:
    assert_hooks_dir_is_the_one_git_consults(root=_ROOT)


def test_the_remedy_names_every_declared_stage() -> None:
    assert_the_remedy_is_derived(root=_ROOT, config_name=DEFAULT_CONFIG_NAME)


def test_this_guard_can_go_both_ways(tmp_path: Path) -> None:
    assert_the_guard_can_go_both_ways(root=_ROOT, config_name=DEFAULT_CONFIG_NAME, scratch=tmp_path)


def test_somebody_elses_hook_is_its_own_finding(tmp_path: Path) -> None:
    assert_a_foreign_hook_is_not_installed(root=_ROOT, config_name=DEFAULT_CONFIG_NAME, scratch=tmp_path)
