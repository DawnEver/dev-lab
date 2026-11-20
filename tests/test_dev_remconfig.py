"""The family rem config: every repo commits `.claude/rem.json` saying its backlog is the issue tracker."""

from __future__ import annotations

import json
from pathlib import Path

from dev_lab.dev import remconfig
from dev_lab.dev.famfiles import PROJECT_FILES


def test_the_render_says_the_backlog_is_the_issue_tracker() -> None:
    assert json.loads(remconfig.render())['backlog'] == 'issues'


def test_a_closed_task_prunes_its_branches_through_the_lossless_door() -> None:
    """User ruling D25: rem's generic onClose runs the task verb with the closed slug; rem itself names no door."""
    assert json.loads(remconfig.render())['onClose'] == [
        'uv',
        'run',
        '--no-sync',
        'python',
        '-m',
        'dev_lab.dev.branchprune',
        'task',
        '{slug}',
    ]


def test_it_is_a_generated_family_file() -> None:
    assert PROJECT_FILES[remconfig.REL].generated


def test_this_repo_commits_the_render() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / remconfig.REL).read_text(encoding='utf-8') == remconfig.render()
