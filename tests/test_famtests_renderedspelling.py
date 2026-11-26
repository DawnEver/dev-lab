"""Adoption of :mod:`dev_lab.dev.famtests.renderedspelling` at the source: every family render passes typos."""

from __future__ import annotations

from pathlib import Path

from dev_lab.dev.famtests.renderedspelling import (
    assert_a_planted_render_is_convicted,
    assert_rendered_files_pass_spelling,
    rendered_files,
)


def test_every_family_render_passes_the_family_spelling_check(tmp_path: Path) -> None:
    assert_rendered_files_pass_spelling(tmp_path)


def test_a_planted_british_spelling_in_a_render_is_convicted(tmp_path: Path) -> None:
    assert_a_planted_render_is_convicted(tmp_path)


def test_every_render_is_read() -> None:
    """A render list that lost the deny registry, or a render that came back empty, is a scan of nothing."""
    renders = rendered_files()
    assert '.claude/hooks/deny-rules.json' in renders
    assert all(text.strip() for text in renders.values())
