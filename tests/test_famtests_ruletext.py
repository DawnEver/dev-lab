"""The controls for :mod:`dev_lab.dev.famtests.ruletext`, and the body run over this repo's own always-loaded page."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.dev.famtests.ruletext import assert_no_bare_interpreter, bare_interpreter_spans

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    'text',
    [
        'You run only `python scripts/gate/runner.py measure <paths>`.',
        'Where a sha stands: `python -m dev_lab.dev.forge queue`.',
        'Use `py -3 tool.py` here.',
        'Or `python3 -I x.py`.',
        'Just `python`.',
    ],
)
def test_a_bare_interpreter_span_is_convicted(text: str) -> None:
    assert bare_interpreter_spans(text)


@pytest.mark.parametrize(
    'text',
    [
        'Run `.venv/Scripts/python.exe -m dev_lab.dev.verify --`.',
        'Stop it with `<venv python> -m dev_lab.dev.stoprun --pid <pid>`.',
        'The `{python}` placeholder.',
        'The `python_requires` key and `pyproject.toml`.',
        'Prose that says python without a code span.',
    ],
)
def test_a_named_interpreter_or_a_mere_word_passes(text: str) -> None:
    assert bare_interpreter_spans(text) == []


def test_the_body_names_the_page_and_the_span(tmp_path: Path) -> None:
    page = tmp_path / 'AGENTS.md'
    page.write_text('- You run `python -m x`.\n', encoding='utf-8')
    with pytest.raises(AssertionError, match=r'AGENTS\.md: `python -m x`'):
        assert_no_bare_interpreter([page], root=tmp_path)


def test_a_scan_over_no_page_cannot_read_green(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match='scan over nothing'):
        assert_no_bare_interpreter([], root=tmp_path)


def test_this_repos_always_loaded_page_spells_no_bare_interpreter() -> None:
    assert_no_bare_interpreter([ROOT / 'AGENTS.md'], root=ROOT)
