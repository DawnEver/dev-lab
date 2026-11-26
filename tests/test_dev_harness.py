"""The harness context: dev-lab's one environment entry reads each named fact, and passes a child's environment on."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dev_lab.dev import harness
from dev_lab.dev.harness import Harness

if TYPE_CHECKING:
    import pytest


def test_context_reads_each_named_fact_and_says_empty_where_the_environment_is_silent() -> None:
    env = {
        'CLAUDE_PROJECT_DIR': '/p',
        'CLAUDE_CONFIG_DIR': '/c',
        'CODEX_HOME': '/x',
        'HARNESS_MACHINE': ' box ',
        'USERNAME': 'win',
        'SUDO_USER': 'admin',
    }
    assert harness.context(env) == Harness('/p', '/c', '/x', 'box', 'win', 'admin')
    assert harness.context({}) == Harness()


def test_the_posix_login_name_wins_over_the_windows_one() -> None:
    assert harness.context({'USER': 'posix', 'USERNAME': 'win'}).user == 'posix'
    assert harness.context({'USER': '', 'USERNAME': 'win'}).user == 'win'


def test_context_defaults_to_the_live_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('HARNESS_MACHINE', 'planted')
    assert harness.context().machine == 'planted'


def test_child_env_drops_then_overlays_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('DEV_LAB_PLANTED_A', 'a')
    monkeypatch.setenv('DEV_LAB_PLANTED_B', 'b')
    child = harness.child_env({'DEV_LAB_PLANTED_C': '1'}, {'DEV_LAB_PLANTED_C': '2'}, drop=('DEV_LAB_PLANTED_B',))
    assert child['DEV_LAB_PLANTED_A'] == 'a'
    assert 'DEV_LAB_PLANTED_B' not in child
    assert child['DEV_LAB_PLANTED_C'] == '2'
    child['DEV_LAB_PLANTED_A'] = 'changed'
    assert harness.child_env()['DEV_LAB_PLANTED_A'] == 'a', 'a copy: the caller never mutates this process'
