"""THE CJK RATCHET, applied to lab-commons itself -- the same shape the suppression ratchet uses.

The rule this guards -- no CJK character in tracked source outside `.claude/memory/`, `attic/` and
`archived/` -- is only worth carrying if the same three shapes as every other ratchet in this family
hold: a PLANTED CONTROL through the REAL scanner, the OPPOSITE DIRECTION (a clean file, an exempt
file, a binary file), and the DECLARED GAPS as a named set that may only shrink.

LAB-COMMONS' OWN DECLARATION IS EMPTY. The two CJK sites this repo carried (`src/lab_commons/dev/
_unit_tokens.py`, `src/lab_commons/dev/units.py` -- both direct quotations of a user ruling) were
translated to English in the same commit that added this guard, so `_DECLARED` below is the
strictest form the ratchet can take and this test is the proof it still runs green on a clean tree.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

from lab_commons.dev.cjk import (
    CJK_RANGES,
    EXEMPT_PREFIXES,
    Occurrence,
    VacuousScan,
    assert_floor,
    exempted,
    find_cjk,
    is_cjk,
    ratchet,
    remedy,
    scan_files,
)
from lab_commons.dev.rules import tracked_files

_ROOT: Final = Path(__file__).resolve().parents[1]

#: Files this repo still carries CJK in, as a NAMED SET that may only shrink. Empty because this
#: commit is the one that cleaned the last two sites and built the guard in the same edit.
_DECLARED: Final[frozenset[str]] = frozenset()

#: Measured 2026-09-16: this repo tracks well over 40 `.py`/`.md`/`.toml` files under `src/`/`tests/`.
_FLOOR: Final = 30


def _corpus() -> tuple[Path, ...]:
    names = tracked_files(_ROOT)
    return tuple(
        _ROOT / name
        for name in sorted(names)
        if (_ROOT / name).is_file() and not name.startswith(('.claude/memory/', 'attic/', 'archived/'))
    )


def test_is_cjk_matches_each_declared_range_and_nothing_else() -> None:
    for lo, hi in CJK_RANGES:
        assert is_cjk(chr(lo))
        assert is_cjk(chr(hi))
    assert not is_cjk('a')
    assert not is_cjk('-')
    assert not is_cjk('—')  # an em dash: ordinary family prose, never a violation


def test_find_cjk_locates_line_and_column_one_based() -> None:
    han1, han2 = chr(0x4E2D), chr(0x6587)
    text = f'clean line\nsecond line has {han1}{han2} in it\n'
    found = find_cjk(text)
    assert found == ((2, 17, han1), (2, 18, han2)), found


def test_an_escape_sequence_is_ascii_source_and_passes(tmp_path: Path) -> None:
    """The remedy for a test that must PLANT a CJK literal: write it as \\uXXXX, not the character.

    ``naming.assert_ascii('\\u76f8_br01')`` runs against the real character at runtime while its
    SOURCE is eight ASCII characters -- this scanner reads the file as written, never a decoded
    runtime string, so the escape sequence contains no code point in :data:`CJK_RANGES` and passes.
    """
    escaped = tmp_path / 'test_naming.py'
    body = "assert_ascii('\\u76f8_br01')  # non-ASCII at runtime, ASCII in source\n"
    escaped.write_text(body, encoding='utf-8')
    scan = scan_files((escaped,), root=tmp_path)
    assert scan.occurrences == ()
    assert scan.files_read == 1


def test_exempted_matches_the_declared_prefixes_and_nothing_wider() -> None:
    assert exempted('.claude/memory/2026/09/16/x.md')
    assert exempted('attic/motor_solver/old.py')
    assert exempted('archived/thing.py')
    assert not exempted('src/lab_commons/dev/cjk.py')
    assert EXEMPT_PREFIXES == ('.claude/memory/', 'attic/', 'archived/')


def test_exempted_matches_a_nested_directory_and_not_a_nested_lookalike() -> None:
    assert exempted('src/motronics/hamilton/.claude/memory/x.md')
    assert exempted('src/pkg/attic/old.py')
    assert exempted('rust/.claude/memory/note.md')
    assert not exempted('src/pkg/notattic/x.py')
    assert not exempted('src/lab_commons/attic_style/x.py')


def test_a_planted_violation_and_a_planted_clean_file_are_told_apart(tmp_path: Path) -> None:
    """THE PLANTED CONTROL, both directions, through the REAL scanner."""
    dirty = tmp_path / 'dirty.py'
    dirty.write_text('x = 1  # ' + chr(0x4E2D) + chr(0x6587) + '\n', encoding='utf-8')
    clean = tmp_path / 'clean.py'
    clean.write_text('x = 1  # ascii only, an em dash -- and nothing else\n', encoding='utf-8')
    memory = tmp_path / '.claude' / 'memory' / 'note.md'
    memory.parent.mkdir(parents=True)
    memory.write_text(chr(0x4E2D) + chr(0x6587) + ' lives here and is exempt\n', encoding='utf-8')

    scan = scan_files(
        (dirty, clean, tmp_path / '.claude/memory/note.md'),
        exempt_prefixes=('.claude/memory/',),
        root=tmp_path,
    )
    assert [o.path for o in scan.occurrences] == ['dirty.py', 'dirty.py']
    assert scan.exempted == ('.claude/memory/note.md',)
    assert scan.files_read == 2, 'the exempt file must not count towards files_read'


def test_a_nested_exemption_directory_is_recognised_and_a_nested_lookalike_is_not(tmp_path: Path) -> None:
    """MEASURED on motronics-studio: `.claude/memory/` and `attic/` are not only root directories.

    A root-prefix-only match reported 47,521 CJK characters under `src/motronics/**` that were all
    inside NESTED memory files (`src/motronics/hamilton/.claude/memory/x.md`). Both directions are
    planted here: a nested memory file and a nested `attic/` file are exempt, while a nested file
    that merely starts with the same letters (`notattic/`) is still caught.
    """
    nested_memory = tmp_path / 'src' / 'motronics' / 'hamilton' / '.claude' / 'memory' / 'note.md'
    nested_memory.parent.mkdir(parents=True)
    nested_memory.write_text(chr(0x4E2D) + chr(0x6587) + ' nested and exempt\n', encoding='utf-8')

    nested_attic = tmp_path / 'src' / 'pkg' / 'attic' / 'old.py'
    nested_attic.parent.mkdir(parents=True)
    nested_attic.write_text('x = 1  # ' + chr(0x4E2D) + '\n', encoding='utf-8')

    lookalike = tmp_path / 'src' / 'pkg' / 'notattic' / 'x.py'
    lookalike.parent.mkdir(parents=True)
    lookalike.write_text('x = 1  # ' + chr(0x6587) + '\n', encoding='utf-8')

    scan = scan_files((nested_memory, nested_attic, lookalike), root=tmp_path)
    assert scan.exempted == (
        'src/motronics/hamilton/.claude/memory/note.md',
        'src/pkg/attic/old.py',
    )
    assert [o.path for o in scan.occurrences] == ['src/pkg/notattic/x.py']
    assert scan.files_read == 1, 'only the lookalike is real source; both exemptions must not be read'


def test_a_binary_file_is_named_undecodable_not_silently_clean(tmp_path: Path) -> None:
    binary = tmp_path / 'blob.bin'
    binary.write_bytes(b'\xff\xfe\x00\x01')
    scan = scan_files((binary,), root=tmp_path)
    assert scan.undecodable == ('blob.bin',)
    assert scan.occurrences == ()
    assert scan.files_read == 0, 'an undecodable file was never read as text'


def test_the_ratchet_refuses_both_an_undeclared_hit_and_an_orphaned_declaration() -> None:
    found = (Occurrence('dirty.py', 1, 10, chr(0x4E2D)),)
    undeclared = ratchet(found, frozenset())
    assert len(undeclared) == 1
    assert undeclared[0].startswith('UNDECLARED CJK -- dirty.py:1:')

    orphaned = ratchet((), frozenset({'gone.py'}))
    assert orphaned == (
        "ORPHANED CJK declaration 'gone.py' -- no CJK remains in this file; remove it from the "
        'declared set in this same commit.',
    )

    assert ratchet(found, frozenset({'dirty.py'})) == ()


def test_remedy_names_the_file_line_and_code_point_and_is_itself_cjk_free() -> None:
    line = remedy(Occurrence('a.py', 3, 5, chr(0x4E2D)))
    assert 'a.py:3' in line
    assert 'U+4E2D' in line
    for lo, hi in CJK_RANGES:
        assert not any(lo <= ord(char) <= hi for char in line)


def test_assert_floor_refuses_a_scan_that_read_too_little() -> None:
    with pytest.raises(VacuousScan):
        assert_floor(0, 1, 'CJK')
    assert_floor(5, 1, 'CJK')  # does not raise


def test_lab_commons_declares_no_cjk_anywhere_it_tracks() -> None:
    """THE CHECK. Every tracked file outside the exemptions is CJK-free -- the declaration is empty."""
    corpus = _corpus()
    assert_floor(len(corpus), _FLOOR, 'CJK (lab-commons)')
    scan = scan_files(corpus, root=_ROOT)
    problems = ratchet(scan.occurrences, _DECLARED)
    assert problems == (), 'the CJK ratchet moved:\n  ' + '\n  '.join(problems)
