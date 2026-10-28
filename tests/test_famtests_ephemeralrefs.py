"""The controls for TRACKED-CITES-NO-EPHEMERAL, both directions, and this repo's own full-tree adoption."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.dev import ephemeralrefs, floors
from dev_lab.dev.famtests.ephemeralrefs import (
    assert_no_tracked_file_cites_ephemeral,
    assert_the_scanner_still_convicts,
)

_REPO = Path(__file__).resolve().parents[1]


def test_the_planted_control_convicts_exactly_the_planted_offenders(tmp_path: Path) -> None:
    assert_the_scanner_still_convicts(tmp_path)


def test_the_planted_control_reds_when_the_machine_local_reader_goes_blind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ephemeralrefs, 'MACHINE_LOCAL', ephemeralrefs.re.compile(r'(?!)'))
    with pytest.raises(AssertionError, match='must read 6'):
        assert_the_scanner_still_convicts(tmp_path)


def _repo(tmp_path: Path, doc: str, pyproject: str = '') -> Path:
    ephemeralrefs._door.run(['git', 'init', '-q'], cwd=tmp_path, check=True, timeout=60)
    (tmp_path / '.gitignore').write_text('/output/\n', encoding='utf-8')
    (tmp_path / 'doc.md').write_text(doc, encoding='utf-8')
    (tmp_path / 'pyproject.toml').write_text(pyproject, encoding='utf-8')
    ephemeralrefs._door.run(['git', 'add', '-A'], cwd=tmp_path, check=True, timeout=60)
    return tmp_path


_ESCAPE = '[tool.dev_lab.ephemeral_refs]\nceiling = {n}\nescapes = [{rows}]\n'
_ROW = '{{ file = "doc.md", token = "{path}", reason = "{why}" }}'


def test_a_declared_escape_clears_its_citation(tmp_path: Path) -> None:
    rows = _ROW.format(path='output/x.json', why='defines it')
    root = _repo(tmp_path, 'see output/x.json\n', _ESCAPE.format(n=1, rows=rows))
    assert ephemeralrefs.scan(root) == ([], 3)


@pytest.mark.parametrize(
    ('ceiling', 'token', 'why', 'refusal'),
    [
        (2, 'output/x.json', 'defines it', 'must be EQUAL'),
        (1, 'output/gone.json', 'defines it', 'ORPHANED'),
        (1, 'output/x.json', ' ', 'no reason'),
    ],
)
def test_a_misdeclared_escape_set_reds(tmp_path: Path, ceiling: int, token: str, why: str, refusal: str) -> None:
    rows = _ROW.format(path=token, why=why)
    root = _repo(tmp_path, 'see output/x.json\n', _ESCAPE.format(n=ceiling, rows=rows))
    problems, _ = ephemeralrefs.scan(root)
    assert any(refusal in p for p in problems), problems


def test_the_pre_commit_entry_reds_on_a_staged_citation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _repo(tmp_path, 'see output/x.json\n')
    monkeypatch.chdir(root)
    assert ephemeralrefs.main(['doc.md']) == 1
    (root / 'doc.md').write_text('see `output/<run>/x.json`\n', encoding='utf-8')
    assert ephemeralrefs.main(['doc.md']) == 0


def test_an_unread_tree_reds_on_the_floor(tmp_path: Path) -> None:
    root = _repo(tmp_path, 'clean\n')
    with pytest.raises(floors.FloorUnmet):
        assert_no_tracked_file_cites_ephemeral(root=root, floor=10, headroom=5)


def test_this_repo_cites_no_ephemeral_path() -> None:
    # Floor re-taken 2026-10-22 at 594 after the split left lab-commons' trees behind.
    assert_no_tracked_file_cites_ephemeral(root=_REPO, floor=540, headroom=60)
