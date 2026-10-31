"""The family rem config: every repo commits `.claude/rem.json` saying its backlog is the issue tracker."""

from __future__ import annotations

import json
from pathlib import Path

from dev_lab.dev import remconfig
from dev_lab.dev.famfiles import PROJECT_FILES


def test_the_render_says_the_backlog_is_the_issue_tracker() -> None:
    assert json.loads(remconfig.render()) == {'backlog': 'issues'}


def test_write_writes_once_then_is_a_no_op(tmp_path: Path) -> None:
    assert remconfig.write(tmp_path) is True
    assert (tmp_path / remconfig.REL).read_text(encoding='utf-8') == remconfig.render()
    assert remconfig.write(tmp_path) is False


def test_a_drifted_config_is_rewritten(tmp_path: Path) -> None:
    (tmp_path / '.claude').mkdir()
    (tmp_path / remconfig.REL).write_text('{"backlog": "files"}\n', encoding='utf-8')
    assert remconfig.write(tmp_path) is True
    assert json.loads((tmp_path / remconfig.REL).read_text(encoding='utf-8')) == {'backlog': 'issues'}


def test_it_is_a_generated_family_file() -> None:
    assert PROJECT_FILES[remconfig.REL].generated


def test_this_repo_commits_the_render() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / remconfig.REL).read_text(encoding='utf-8') == remconfig.render()
