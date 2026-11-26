"""The controls for EVIDENCE-OUTLIVES-OUTPUT, both directions, and this repo's own full-tree adoption."""

from __future__ import annotations

from pathlib import Path

import pytest
from lab_commons.launch import run

from dev_lab.dev import evidencerefs, floors
from dev_lab.dev.famtests.evidencerefs import (
    assert_no_tracked_value_cites_output_evidence,
    assert_the_evidence_scan_still_convicts,
)

_REPO = Path(__file__).resolve().parents[1]


def test_the_planted_control_convicts_exactly_the_planted_offenders(tmp_path: Path) -> None:
    assert_the_evidence_scan_still_convicts(tmp_path)


@pytest.mark.parametrize(
    ('blind', 'value'),
    [('ROOT_CALLS', frozenset()), ('WRITE_VERBS', frozenset())],
)
def test_the_planted_control_reds_when_a_judgment_goes_blind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blind: str, value: frozenset[str]
) -> None:
    """Without the repo-root reading (b) passes; without the writer set (e) convicts: each reds the control."""
    monkeypatch.setattr(evidencerefs, blind, value)
    with pytest.raises(AssertionError, match='must read 3'):
        assert_the_evidence_scan_still_convicts(tmp_path)


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    run(['git', 'init', '-q'], cwd=tmp_path, check=True, timeout=60)
    (tmp_path / '.gitignore').write_text('/output/\n', encoding='utf-8')
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding='utf-8')
    run(['git', 'add', '-A'], cwd=tmp_path, check=True, timeout=60)
    return tmp_path


_ESCAPE = (
    '[tool.dev_lab.evidence_refs]\nceiling = {n}\nescapes = [{{ file = "a.py", token = "{t}", reason = "{w}" }}]\n'
)


def test_a_declared_escape_clears_its_citation(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        {'a.py': "NOTE = 'output/x.json'\n", 'pyproject.toml': _ESCAPE.format(n=1, t='output/x.json', w='why')},
    )
    assert evidencerefs.scan(root) == ([], 2)


@pytest.mark.parametrize(
    ('ceiling', 'token', 'why', 'refusal'),
    [
        (2, 'output/x.json', 'why', 'must be EQUAL'),
        (1, 'output/gone.json', 'why', 'ORPHANED'),
        (1, 'output/x.json', ' ', 'no reason'),
    ],
)
def test_a_misdeclared_escape_set_reds(tmp_path: Path, ceiling: int, token: str, why: str, refusal: str) -> None:
    pyproject = _ESCAPE.format(n=ceiling, t=token, w=why)
    root = _repo(tmp_path, {'a.py': "NOTE = 'output/x.json'\n", 'pyproject.toml': pyproject})
    problems, _ = evidencerefs.scan(root)
    assert any(refusal in p for p in problems), problems


def test_an_unread_tree_reds_on_the_floor(tmp_path: Path) -> None:
    root = _repo(tmp_path, {'a.py': ''})
    with pytest.raises(floors.FloorUnmet):
        assert_no_tracked_value_cites_output_evidence(root=root, floor=10, headroom=5)
