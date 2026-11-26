"""dev_lab.dev.memory: the write doors produce only what memoryentry admits, and search reads the files."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest

from dev_lab.dev import memory, memoryentry
from dev_lab.dev.memory import MemoryRefused

if TYPE_CHECKING:
    from pathlib import Path

DAY = date(2026, 11, 23)


def _entry(root: Path, name: str = 'seam-measured', body: str = 'The seam costs 4 s.\nSecond line.') -> str:
    path = memory.add(root, name, 'what the seam costs', body, day=DAY)
    return path.relative_to(root).as_posix()


def test_add_writes_a_dated_entry_with_its_frontmatter(tmp_path: Path) -> None:
    rel = _entry(tmp_path)
    assert rel == '.claude/memory/2026/11/23/seam-measured.md'
    text = (tmp_path / rel).read_text(encoding='utf-8')
    assert text.startswith('---\nname: seam-measured\ndescription: what the seam costs\n---\n')


def test_add_refuses_an_existing_entry_and_a_bad_slug(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same add twice is refused, and the file keeps its first text."""
    rel = _entry(tmp_path, body='first')
    with pytest.raises(MemoryRefused, match='never rewritten'):
        _entry(tmp_path, body='second')
    assert 'first' in (tmp_path / rel).read_text(encoding='utf-8')
    with pytest.raises(MemoryRefused, match='kebab-case'):
        memory.add(tmp_path, 'Not A Slug', 'd', 'b', day=DAY)
    with pytest.raises(MemoryRefused, match='one non-empty line'):
        memory.add(tmp_path, 'ok', 'two\nlines', 'b', day=DAY)


def test_amend_replaces_one_line_and_adds_the_note(tmp_path: Path) -> None:
    rel = _entry(tmp_path)
    memory.amend(tmp_path, rel, 6, 'The seam costs 3 s.', reason='misstated figure', approved='yes fix it')
    text = (tmp_path / rel).read_text(encoding='utf-8')
    assert 'The seam costs 3 s.' in text
    assert 'The seam costs 4 s.' not in text
    assert '-- approved: "yes fix it"' in text


def test_amend_without_approval_words_is_refused(tmp_path: Path) -> None:
    """PLANTED CONTROL: an empty approval fails the commit judge, so the door writes nothing."""
    rel = _entry(tmp_path)
    before = (tmp_path / rel).read_text(encoding='utf-8')
    with pytest.raises(MemoryRefused, match='not an amendment'):
        memory.amend(tmp_path, rel, 6, 'changed', reason='r', approved='')
    assert (tmp_path / rel).read_text(encoding='utf-8') == before


def test_redact_swaps_a_span_for_a_placeholder(tmp_path: Path) -> None:
    rel = _entry(tmp_path, body='Measured on acme-host-7 today.')
    memory.redact(tmp_path, rel, 'acme-host-7', '<host>')
    text = (tmp_path / rel).read_text(encoding='utf-8')
    assert 'Measured on <host> today.' in text
    assert 'acme-host-7' not in text
    with pytest.raises(MemoryRefused, match='not a redaction'):
        memory.redact(tmp_path, rel, 'today', 'tomorrow')


def test_rename_drops_a_token_and_records_it(tmp_path: Path) -> None:
    rel = _entry(tmp_path, name='login-jdoe-fixed')
    moved = memory.rename(tmp_path, rel, 'login-user-fixed.md', approved='rename it')
    assert moved.name == 'login-user-fixed.md'
    assert not (tmp_path / rel).exists()
    assert 'renamed' in moved.read_text(encoding='utf-8')
    with pytest.raises(MemoryRefused, match='not a redacting rename'):
        memory.rename(tmp_path, moved.relative_to(tmp_path).as_posix(), 'other.md', approved='x')


def test_search_needs_every_term_and_ranks_the_frontmatter_first(tmp_path: Path) -> None:
    memory.add(tmp_path, 'body-only', 'unrelated', 'the seam and the mesh', day=DAY)
    memory.add(tmp_path, 'seam-in-head', 'the seam mesh profile', 'nothing', day=DAY)
    memory.add(tmp_path, 'mesh-only', 'mesh', 'no other term', day=DAY)
    hits = memory.search(tmp_path, ['SEAM', 'mesh'])
    assert [hit.path.rsplit('/', 1)[1] for hit in hits] == ['seam-in-head.md', 'body-only.md']
    assert hits[0].description == 'the seam mesh profile'
    assert memory.search(tmp_path, ['absent-term']) == [], 'planted control: a term nowhere finds nothing'


def test_the_cli_refuses_by_name_and_searches(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _entry(tmp_path)
    assert memory.main(['--root', str(tmp_path), 'search', 'seam']) == 0
    assert 'seam-measured.md: what the seam costs' in capsys.readouterr().out
    assert (
        memory.main(['--root', str(tmp_path), 'amend', 'nowhere.md', '1', 'x', '--reason', 'r', '--approved', 'a']) == 2
    )
    assert 'MEMORY-SHAPE' in capsys.readouterr().err


def _attach(root: Path, inside: str) -> Path:
    path = memory.memory_dir(root) / inside
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('x\n', encoding='utf-8')
    return path


def test_delete_removes_attachments_and_records_their_approval_in_a_new_entry(tmp_path: Path) -> None:
    """ATTACHMENT-DELETE: the door writes the note memoryadds admits a deletion by, then removes each file."""
    paths = [_attach(tmp_path, '2026/08/30/.archive/a.md'), _attach(tmp_path, '2026/08/30/.archive/b.mjs')]
    rels = [p.relative_to(tmp_path).as_posix() for p in paths]
    note_entry = memory.delete(tmp_path, 'archive-cleared', rels, reason='stray', approved='ok to clean', day=DAY)
    assert not any(p.exists() for p in paths)
    assert not (memory.memory_dir(tmp_path) / '2026/08/30/.archive').exists()
    notes = memoryentry.amendment_notes(note_entry.read_text(encoding='utf-8'))
    assert all(memoryentry.deletion_approved(rel, notes) for rel in rels)


def test_delete_refuses_an_entry_and_an_empty_approval(tmp_path: Path) -> None:
    """PLANTED CONTROL: a dated entry is never an attachment, and empty words approve nothing; nothing is removed."""
    rel = _entry(tmp_path)
    with pytest.raises(MemoryRefused, match='not a memory attachment'):
        memory.delete(tmp_path, 'gone', [rel], reason='r', approved='yes', day=DAY)
    assert (tmp_path / rel).exists()
    path = _attach(tmp_path, '2026/08/30/.archive/a.md')
    with pytest.raises(MemoryRefused, match='approv'):
        memory.delete(tmp_path, 'gone', [path.relative_to(tmp_path).as_posix()], reason='r', approved='', day=DAY)
    assert path.exists()
