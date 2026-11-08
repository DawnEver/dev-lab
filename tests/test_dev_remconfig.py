"""The family rem config: every repo commits `.claude/rem.json` saying its backlog is the issue tracker."""

from __future__ import annotations

import json
from pathlib import Path

from dev_lab.dev import remconfig
from dev_lab.dev.famfiles import PROJECT_FILES


def test_the_render_says_the_backlog_is_the_issue_tracker() -> None:
    assert json.loads(remconfig.render()) == {'backlog': 'issues'}


def test_it_is_a_generated_family_file() -> None:
    assert PROJECT_FILES[remconfig.REL].generated


def test_this_repo_commits_the_render() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / remconfig.REL).read_text(encoding='utf-8') == remconfig.render()
