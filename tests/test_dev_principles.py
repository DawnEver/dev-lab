"""The family's engineering principles: one tuple, its JSON payload, its rendered rules page."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev_lab.dev import principles
from dev_lab.dev.docwidth import WIDTH_CEILING
from dev_lab.dev.famfiles import render_agent_files
from dev_lab.dev.famtests.principlespage import assert_principles_page_is_rendered
from dev_lab.dev.principles import PAGE_REL, PRINCIPLES, payload, render

ROOT = Path(__file__).resolve().parents[1]


def test_the_set_is_the_named_set_and_keeps_valuable_options() -> None:
    """A NAMED SET, not a count: a dropped or renamed id names itself."""
    assert [one.id for one in PRINCIPLES] == [
        'first-principles', 'no-historical-baggage', 'occams-razor', 'single-source-of-truth',
        'layered-decoupling', 'names-match-behaviour', 'no-backward-compatibility', 'progressive-disclosure',
        'keep-valuable-options', 'every-wall-teaches',
    ]  # fmt: skip
    kept = PRINCIPLES[-2]
    assert kept.name == 'Keep every valuable parameter and option'
    assert kept.statement.startswith('Generality is a requirement: keep every parameter and option')


def test_a_reference_match_adds_an_option_and_the_razors_never_remove_capability() -> None:
    """User ruling 2026-11-12: a vendor match is ADDED as a choice, never substituted for the native one."""
    by_id = {one.id: one.statement for one in PRINCIPLES}
    kept = by_id['keep-valuable-options']
    for clause in (
        'ADDS a selectable option',
        'never replaces or deletes the alternative',
        'numerical method choices are options even with no current caller',
    ):
        assert clause in kept
    assert by_id['occams-razor'].endswith('never a capability.')
    assert by_id['no-historical-baggage'].endswith('never a capability.')


def test_every_wall_teaches_names_the_gap_and_the_loop() -> None:
    """User ruling 2026-11-13: a wall with no named cause and door is a mechanism gap, closed before the task."""
    wall = {one.id: one for one in PRINCIPLES}['every-wall-teaches']
    for clause in (
        'names its cause and its door',
        'is a mechanism gap',
        'comes before the task',
        'Never route around a wall or hand the user a command.',
        'docs-src/dev/feedback.md',
    ):
        assert clause in wall.statement


def test_the_json_flag_prints_the_payload(capsys: pytest.CaptureFixture[str]) -> None:
    """``--json`` prints exactly ``{"principles": [{id, name, statement}...]}``."""
    assert principles.main(['--json']) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed == payload()
    assert printed['principles'][0] == {
        'id': 'first-principles',
        'name': 'First principles',
        'statement': PRINCIPLES[0].statement,
    }


def test_the_page_fits_the_width_and_names_every_principle() -> None:
    """Every line within the injected-doc ceiling; every id and verbatim statement present."""
    page = render()
    assert all(len(line) <= WIDTH_CEILING for line in page.splitlines())
    flat = ' '.join(line.strip() for line in page.splitlines())
    for one in PRINCIPLES:
        assert f'- **{one.name}** (`{one.id}`): {one.statement}' in flat


def test_famfiles_writes_the_page_and_a_drifted_page_reds(tmp_path: Path) -> None:
    """PLANTED: an absent page reds, the write greens it, a hand edit reds again."""
    with pytest.raises(AssertionError, match='no '):
        assert_principles_page_is_rendered(root=tmp_path)
    render_agent_files(tmp_path, write=True)
    assert render_agent_files(tmp_path, write=False)[0] == f'{PAGE_REL}: current'
    assert_principles_page_is_rendered(root=tmp_path)
    page = tmp_path / PAGE_REL
    page.write_text(page.read_text(encoding='utf-8') + '- extra\n', encoding='utf-8')
    with pytest.raises(AssertionError, match='drifted'):
        assert_principles_page_is_rendered(root=tmp_path)


def test_this_repo_commits_the_render() -> None:
    """The kit's own page through the consumer body."""
    assert_principles_page_is_rendered(root=ROOT)
