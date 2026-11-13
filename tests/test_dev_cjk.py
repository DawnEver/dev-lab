"""The controls for :mod:`dev_lab.dev.cjk` -- the scanner, the ranges, the exemptions and the ratchet.

Planted violations through the REAL scanner, in both directions (a clean file, an exempt file, a
binary file). The scan of a repo's OWN tracked files is not here: it is the always-on family row
:mod:`dev_lab.dev.famtests.alwayson`, which every repo installing dev-lab runs, this one included.
"""

from __future__ import annotations

from collections.abc import Collection
from pathlib import Path

import pytest

from dev_lab.dev.cjk import (
    CJK_RANGES,
    EXEMPT_PREFIXES,
    Occurrence,
    VacuousScan,
    assert_floor,
    char_class,
    exempted,
    find_cjk,
    is_cjk,
    non_ascii_distance,
    orphaned_translations,
    ratchet,
    remedy,
    scan_files,
    scan_non_ascii,
    translation_source,
)


def test_is_cjk_matches_each_declared_range_and_nothing_else() -> None:
    for lo, hi in CJK_RANGES:
        assert is_cjk(chr(lo))
        assert is_cjk(chr(hi))
    assert not is_cjk('a')
    assert not is_cjk('-')
    assert not is_cjk('—')  # an em dash: ordinary family prose, never a violation


def test_a_kana_line_and_a_hangul_line_are_refused_and_ordinary_non_ascii_passes(tmp_path: Path) -> None:
    kana = tmp_path / 'kana.md'
    kana.write_text('ok\nsee \u3072\u30ab\u31f0\uff76\n', encoding='utf-8')
    hangul = tmp_path / 'hangul.md'
    hangul.write_text('\ud55c\u1100\u3131\ua960\ud7b0\n', encoding='utf-8')
    clean = tmp_path / 'clean.md'
    clean.write_text('20 \u00b0C, \u03b1 \u03c9 \u2014 \u00d7 \u00e9\n', encoding='utf-8')
    scan = scan_files([kana, hangul, clean], root=tmp_path)
    assert {(o.path, o.line) for o in scan} == {('kana.md', 2), ('hangul.md', 1)}
    assert len(scan.occurrences) == 9
    refused = [problem.split(':')[0] for problem in ratchet(scan.occurrences, ())]
    assert refused == ['UNDECLARED CJK -- hangul.md', 'UNDECLARED CJK -- kana.md']


def test_find_cjk_locates_line_and_column_one_based() -> None:
    han1, han2 = chr(0x4E2D), chr(0x6587)
    text = f'clean line\nsecond line has {han1}{han2} in it\n'
    found = find_cjk(text)
    assert found == ((2, 17, han1), (2, 18, han2)), found


def test_an_escape_sequence_is_ascii_source_and_passes(tmp_path: Path) -> None:
    r"""The remedy for a test that must PLANT a CJK literal: write it as \\uXXXX, not the character.

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


def test_only_the_repo_root_attic_is_exempt_by_path() -> None:
    """User rulings 2026-11-12: the root `attic/` is the one path exemption; memory, tasks, archived/ are not."""
    assert EXEMPT_PREFIXES == ('/attic/',)
    assert exempted('attic/motor_solver/old.py')
    assert exempted('attic/motor_solver/archived/old.py')
    assert not exempted('src/pkg/attic/old.py')
    assert not exempted('notattic/x.py')
    assert not exempted('archived/thing.py')
    assert not exempted('.claude/memory/2026/09/16/x.md')
    assert not exempted('.claude/tasks/some-task/JOURNAL.md')
    assert not exempted('src/pkg/.claude/memory/x.md')
    assert not exempted('src/dev_lab/dev/cjk.py')


def test_a_planted_violation_and_a_planted_clean_file_are_told_apart(tmp_path: Path) -> None:
    """THE PLANTED CONTROL, both directions, through the REAL scanner and the family's own prefixes.

    CJK in memory, in a task journal, in a nested `attic/` and in `archived/` is refused; CJK in the
    repo-root `attic/` passes; an ASCII file is clean.
    """
    han = chr(0x4E2D) + chr(0x6587)
    refused = ('.claude/memory/2026/11/12/note.md', '.claude/tasks/t/JOURNAL.md', 'x/attic/old.py', 'archived/f.py')
    for name in (*refused, 'attic/old.py'):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'x = 1  # {han}\n', encoding='utf-8')
    clean = tmp_path / 'clean.py'
    clean.write_text('x = 1  # ascii only, an em dash -- and nothing else\n', encoding='utf-8')

    scan = scan_files([tmp_path / name for name in (*refused, 'attic/old.py', 'clean.py')], root=tmp_path)
    assert sorted({o.path for o in scan.occurrences}) == sorted(refused)
    assert scan.exempted == ('attic/old.py',)
    assert scan.files_read == len(refused) + 1, 'the exempt file must not count towards files_read'


def test_a_bare_prefix_still_matches_as_a_segment_when_a_caller_passes_one(tmp_path: Path) -> None:
    """The segment shape is kept for a caller's own prefixes: nested matches, a lookalike does not."""
    nested = tmp_path / 'src' / 'pkg' / 'vendor' / 'x.py'
    lookalike = tmp_path / 'src' / 'pkg' / 'notvendor' / 'x.py'
    for path in (nested, lookalike):
        path.parent.mkdir(parents=True)
        path.write_text('x = 1  # ' + chr(0x4E2D) + '\n', encoding='utf-8')
    scan = scan_files((nested, lookalike), exempt_prefixes=('vendor/',), root=tmp_path)
    assert scan.exempted == ('src/pkg/vendor/x.py',)
    assert [o.path for o in scan.occurrences] == ['src/pkg/notvendor/x.py']


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
        (
            "ORPHANED CJK declaration 'gone.py' -- no CJK remains in this file; remove it from the "
            'declared set in this same commit.'
        ),
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


def _walk_every_character(
    text: str, ranges: Collection[tuple[int, int]] = CJK_RANGES
) -> tuple[tuple[int, int, str], ...]:
    """The pre-prefilter implementation, kept as the CONTROL the fast path is judged against.

    This is the per-character walk `find_cjk` used before the derived-class prefilter landed,
    reproduced here rather than imported so the equivalence test compares two INDEPENDENT answers.
    If it is ever edited to match a new `find_cjk`, the test below stops proving anything -- it is
    the OLD behaviour on purpose.
    """
    found: list[tuple[int, int, str]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        found.extend((line_no, col, char) for col, char in enumerate(line, start=1) if is_cjk(char, ranges))
    return tuple(found)


def test_the_prefilter_skips_work_without_changing_one_reported_occurrence(tmp_path: Path) -> None:
    """THE EQUIVALENCE PROOF: every case the two implementations must agree about, planted at once.

    The plant is a corpus of five files -- CJK at a known line and column, a memory note that is
    SCANNED like any other file, a root ``attic/`` file that is EXEMPT though it still carries CJK, an
    UNDECODABLE file, and a CLEAN file -- because the fast path's whole risk is that
    it returns the empty tuple for something the walk would have reported.

    THE FLOOR COMES FIRST: the control is asserted to FIND the plant, at the exact line and column,
    before the two answers are compared. Without it, an equality between two empty tuples would read
    as success and the prefilter could be skipping everything.
    """
    han, full_width_a = chr(0x4E2D), chr(0xFF21)
    dirty = tmp_path / 'dirty.py'
    dirty.write_text(f'clean first line\nx = 1  # {han}{full_width_a}\n', encoding='utf-8')
    memory = tmp_path / '.claude' / 'memory' / 'note.md'
    memory.parent.mkdir(parents=True)
    memory.write_text(f'{han} is scanned here too\n', encoding='utf-8')
    exempt = tmp_path / 'attic' / 'note.md'
    exempt.parent.mkdir(parents=True)
    exempt.write_text(f'{han} is allowed to live here\n', encoding='utf-8')
    undecodable = tmp_path / 'blob.bin'
    undecodable.write_bytes(b'\xff\xfe\x00\x01')
    clean = tmp_path / 'clean.py'
    clean.write_text('x = 1  # ascii only, an em dash -- and nothing else\n', encoding='utf-8')

    # THE FLOOR: the control finds the plant, so the equality below is not two empty answers agreeing.
    control = _walk_every_character(dirty.read_text(encoding='utf-8'))
    assert control == ((2, 10, han), (2, 11, full_width_a)), control
    assert _walk_every_character(exempt.read_text(encoding='utf-8')) == ((1, 1, han),)
    assert _walk_every_character(memory.read_text(encoding='utf-8')) == ((1, 1, han),)
    assert _walk_every_character(clean.read_text(encoding='utf-8')) == ()

    for planted in (dirty, memory, exempt, clean):
        text = planted.read_text(encoding='utf-8')
        assert find_cjk(text) == _walk_every_character(text), planted.name

    scan = scan_files((dirty, memory, exempt, clean, undecodable), root=tmp_path)
    assert scan.occurrences == (
        Occurrence('.claude/memory/note.md', 1, 1, han),
        Occurrence('dirty.py', 2, 10, han),
        Occurrence('dirty.py', 2, 11, full_width_a),
    )
    assert scan.exempted == ('attic/note.md',)
    assert scan.undecodable == ('blob.bin',)
    assert scan.files_read == 3


def test_the_prefilter_agrees_with_the_control_on_every_declared_range_and_line_boundary() -> None:
    r"""The endpoints of every range, and the line boundaries `splitlines()` counts but `\n` does not.

    A regex class is built from the SAME `CJK_RANGES`, so the endpoints are where a derived class and
    a comparison would first disagree if either were off by one. The boundary characters matter
    because the detailed pass still uses `splitlines()` to number lines: a form feed or `\u2028` ends
    a line for it, and a prefilter that numbered lines any other way would shift every column after it.
    """
    for lo, hi in CJK_RANGES:
        for point in (lo - 1, lo, lo + 1, hi - 1, hi, hi + 1):
            text = f'a{chr(point)}b'
            assert find_cjk(text) == _walk_every_character(text), hex(point)

    han = chr(0x4E2D)
    for boundary in ('\n', '\r\n', '\r', '\x0b', '\x0c', '\x1c', '\x85', chr(0x2028)):
        text = f'first{boundary}second {han} here'
        assert find_cjk(text) == _walk_every_character(text), repr(boundary)


def test_a_custom_range_set_still_drives_the_derived_pattern() -> None:
    """The prefilter is derived from the ARGUMENT, not from the module constant.

    A caller passing narrower ranges must get the narrower answer -- if the fast path had been built
    from `CJK_RANGES` unconditionally, this is the call that would silently over-report.
    """
    han, hiragana = chr(0x4E2D), chr(0x3042)
    text = f'{han}{hiragana}'
    narrow = ((0x4E00, 0x9FFF),)
    assert find_cjk(text, narrow) == _walk_every_character(text, narrow) == ((1, 1, han),)
    assert find_cjk(text, [(0x3040, 0x309F)]) == ((1, 2, hiragana),)


def test_attic_is_exempt_only_at_the_repo_root(tmp_path: Path) -> None:
    """THE PLANTED CONTROL for the 2026-11-12 anchoring: `attic/f.py` is exempt, `x/attic/f.py` NOT."""
    han = chr(0x4E2D)
    root_attic = tmp_path / 'attic' / 'f.py'
    nested_attic = tmp_path / 'x' / 'attic' / 'f.py'
    for path in (root_attic, nested_attic):
        path.parent.mkdir(parents=True)
        path.write_text(f'x = 1  # {han}\n', encoding='utf-8')
    scan = scan_files((root_attic, nested_attic), root=tmp_path)
    assert scan.exempted == ('attic/f.py',)
    assert [o.path for o in scan.occurrences] == ['x/attic/f.py']


def test_a_translation_is_exempt_only_beside_its_english_source(tmp_path: Path) -> None:
    """TRANSLATION-HAS-ITS-SOURCE, both directions: a `.zh.md` beside its `.md` is exempt, an orphan is read."""
    han = chr(0x4E2D)
    paired = tmp_path / 'docs' / 'page.zh.md'
    paired.parent.mkdir(parents=True)
    paired.write_text(f'{han}\n', encoding='utf-8')
    (tmp_path / 'docs' / 'page.md').write_text('the English source of truth\n', encoding='utf-8')
    orphan = tmp_path / 'docs' / 'lonely.zh.md'
    orphan.write_text(f'{han}\n', encoding='utf-8')
    scan = scan_files(sorted(p for p in tmp_path.rglob('*') if p.is_file()), root=tmp_path)
    assert scan.exempted == ('docs/page.zh.md',)
    assert [o.path for o in scan.occurrences] == ['docs/lonely.zh.md']
    problems = orphaned_translations(('docs/page.md', 'docs/page.zh.md', 'docs/lonely.zh.md'))
    assert len(problems) == 1
    assert "'docs/lonely.zh.md'" in problems[0]
    assert "'docs/lonely.md'" in problems[0], 'the refusal must name the source to add -- the remedy'
    assert orphaned_translations(('docs/page.md', 'docs/page.zh.md')) == ()


def test_translation_source_names_the_sibling_and_ignores_everything_else() -> None:
    assert translation_source('a/b.zh.md') == 'a/b.md'
    assert translation_source('b.zh.md') == 'b.md'
    assert translation_source('a/b.md') is None
    assert translation_source('a/.zh.md') is None
    assert translation_source('a/b.zh.txt') is None


def test_the_non_ascii_census_counts_per_file_and_per_class_and_reports_the_distance(tmp_path: Path) -> None:
    """The final-goal reading: every non-ASCII character counted, classed, and the distance printed."""
    dirty = tmp_path / 'dirty.md'
    dirty.write_text('a \u2014 b \u00d7 c ' + chr(0x4E2D) + '\n', encoding='utf-8')
    clean = tmp_path / 'clean.md'
    clean.write_text('ascii only\n', encoding='utf-8')
    memory = tmp_path / '.claude' / 'memory' / 'n.md'
    memory.parent.mkdir(parents=True)
    memory.write_text('\u2014\n', encoding='utf-8')
    attic = tmp_path / 'attic' / 'old.md'
    attic.parent.mkdir(parents=True)
    attic.write_text('\u00d7\n', encoding='utf-8')
    scan = scan_non_ascii((dirty, clean, memory, attic), root=tmp_path)
    assert scan.files_read == 3
    assert scan.total == 4
    assert dict(scan.by_file['dirty.md']) == {'dash': 1, 'math symbol': 1, 'CJK': 1}
    assert dict(scan.by_file['.claude/memory/n.md']) == {'dash': 1}
    assert 'attic/old.md' not in scan.by_file
    report = non_ascii_distance(scan)
    assert report.startswith('4 non-ASCII character(s) remain in 2 of 3 file(s) read.')
    assert 'dirty.md' in report
    assert 'dash 1' in report
    assert report.isascii()
    assert char_class(chr(0x4E2D)) == 'CJK'
    assert char_class('\u2014') == 'dash'


def test_a_submodule_directory_among_the_tracked_paths_is_skipped_not_read(tmp_path: Path) -> None:
    """``git ls-files`` names a submodule as a path that is a DIRECTORY; reading it raises on every OS."""
    submodule = tmp_path / 'vendor' / 'sub'
    submodule.mkdir(parents=True)
    (submodule / 'inner.md').write_text('\u2014\n', encoding='utf-8')
    dirty = tmp_path / 'dirty.md'
    dirty.write_text('\u2014\n', encoding='utf-8')
    scan = scan_non_ascii((submodule, dirty), root=tmp_path)
    assert scan.files_read == 1
    assert set(scan.by_file) == {'dirty.md'}


def test_the_cjk_scan_skips_a_submodule_directory_too(tmp_path: Path) -> None:
    submodule = tmp_path / 'sub'
    submodule.mkdir()
    clean = tmp_path / 'clean.md'
    clean.write_text('ascii\n', encoding='utf-8')
    scan = scan_files((submodule, clean), root=tmp_path)
    assert scan.files_read == 1
    assert 'sub' not in scan.exempted
