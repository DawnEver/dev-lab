"""The family's engineering principles: one tuple, its JSON payload, its rendered rules page."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev_lab.dev import principles
from dev_lab.dev.docwidth import WIDTH_CEILING
from dev_lab.dev.famtests.principlespage import assert_principles_page_is_rendered
from dev_lab.dev.principles import PAGE_REL, PRINCIPLES, payload, render, write_page

ROOT = Path(__file__).resolve().parents[1]


def test_the_set_is_the_named_set_and_keeps_valuable_options() -> None:
    """A NAMED SET, not a count: a dropped or renamed id names itself."""
    assert [one.id for one in PRINCIPLES] == [
        'first-principles', 'no-historical-baggage', 'occams-razor', 'single-source-of-truth',
        'layered-decoupling', 'names-match-behaviour', 'no-backward-compatibility', 'progressive-disclosure',
        'keep-valuable-options',
    ]  # fmt: skip
    kept = PRINCIPLES[-1]
    assert kept.name == 'Keep every valuable parameter and option'
    assert kept.statement.startswith('Generality is a requirement: keep every parameter and option')


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


def test_write_page_is_idempotent_and_a_drifted_page_reds(tmp_path: Path) -> None:
    """PLANTED: an absent page reds, the write greens it, a hand edit reds again."""
    with pytest.raises(AssertionError, match='no '):
        assert_principles_page_is_rendered(root=tmp_path)
    assert write_page(tmp_path) is True
    assert write_page(tmp_path) is False
    assert_principles_page_is_rendered(root=tmp_path)
    page = tmp_path / PAGE_REL
    page.write_text(page.read_text(encoding='utf-8') + '- extra\n', encoding='utf-8')
    with pytest.raises(AssertionError, match='drifted'):
        assert_principles_page_is_rendered(root=tmp_path)


def test_this_repo_commits_the_render() -> None:
    """The kit's own page through the consumer body."""
    assert_principles_page_is_rendered(root=ROOT)
