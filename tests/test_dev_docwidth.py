"""THE INJECTED-DOC WIDTH RATCHET, applied to lab-commons itself -- same shape as the CJK ratchet.

The rule: every document this family injects into an agent's context (`AGENTS.md`/`CLAUDE.md` by
basename, `.claude/rules/**`, `.claude/memory/` excluded) is capped at 120 columns PER LINE, on top
of whatever line-COUNT ratchet a repo already runs -- a line-count pin cannot see a page that grows
wider while its line count shrinks, and MEASURED 2026-09-16 one motronics page reaches column 786
while motronics' own line-count ratchet reads only its 32 lines.

LAB-COMMONS' OWN DECLARATION IS EMPTY. Its two tracked `.claude/rules/*.md` pages measure a maximum
of 99 columns (MEASURED 2026-09-16), comfortably under the 120 ceiling with no `AGENTS.md` or
`CLAUDE.md` tracked here at all, so `_DECLARED` below is the strictest form and this test proves the
guard runs green on a clean, already-compliant repo.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

from lab_commons.dev.docwidth import (
    INJECTED_BASENAMES,
    INJECTED_EXEMPT_PREFIXES,
    INJECTED_PREFIXES,
    WIDTH_CEILING,
    Overwidth,
    VacuousWidthScan,
    assert_width_floor,
    injected_docs,
    is_injected_doc,
    line_widths,
    scan_widths,
    width_ratchet,
    width_remedy,
)
from lab_commons.dev.rules import tracked_files

_ROOT: Final = Path(__file__).resolve().parents[1]

#: `path:line` sites this repo still carries an over-width injected-doc line at. Empty: this commit
#: is the one that added the guard to an already-compliant repo.
_DECLARED: Final[frozenset[str]] = frozenset()

#: Measured 2026-09-16: this repo tracks exactly 2 `.claude/rules/*.md` pages and no root AGENTS.md
#: or CLAUDE.md. A floor of 2 refuses an unread corpus without pinning a count that grows on its own.
_FLOOR: Final = 2


def test_width_ceiling_is_the_one_the_family_already_uses_for_code() -> None:
    assert WIDTH_CEILING == 120


def test_is_injected_doc_matches_the_measured_default_corpus() -> None:
    assert is_injected_doc('AGENTS.md')
    assert is_injected_doc('attic/motor_solver/AGENTS.md')
    assert is_injected_doc('CLAUDE.md')
    assert is_injected_doc('.claude/rules/taste.md')
    assert not is_injected_doc('.claude/memory/2026/09/16/note.md')
    assert not is_injected_doc('src/lab_commons/dev/docwidth.py')
    assert frozenset({'AGENTS.md', 'CLAUDE.md'}) == INJECTED_BASENAMES
    assert INJECTED_PREFIXES == ('.claude/rules/',)
    assert INJECTED_EXEMPT_PREFIXES == ('.claude/memory/',)


def test_a_nested_rules_page_is_recognised_and_a_nested_lookalike_is_not() -> None:
    """MEASURED on motronics-studio: `.claude/rules/` pages are SCOPED per module, not root-only.

    `src/motronics/hamilton/.claude/rules/femm.md`, `scripts/.claude/rules/scripts.md` and every
    `src/motronics/*/.claude/rules/MEMORY.md` are real injected pages a root-only prefix would miss
    entirely -- the width ceiling would then cover nothing that repo actually injects.
    """
    assert is_injected_doc('src/motronics/hamilton/.claude/rules/femm.md')
    assert is_injected_doc('scripts/.claude/rules/scripts.md')
    assert not is_injected_doc('src/motronics/hamilton/.claude/memory/note.md')
    assert not is_injected_doc('src/pkgnot.claude/rules/x.md'), 'the prefix must start a path segment'


def test_the_exemption_is_checked_before_the_prefix_even_when_both_would_match() -> None:
    assert not is_injected_doc('.claude/memory/x.md', prefixes=('.claude/memory/',))


def test_a_consumer_can_override_every_half_of_the_corpus_definition() -> None:
    assert is_injected_doc('docs-src/dev/always-loaded.md', prefixes=('docs-src/dev/',))
    assert not is_injected_doc('AGENTS.md', basenames=frozenset())
    assert not is_injected_doc('.claude/rules/x.md', exempt_prefixes=('.claude/rules/',))


def test_injected_docs_narrows_a_tracked_list_to_the_corpus() -> None:
    paths = ('AGENTS.md', 'src/a.py', '.claude/rules/taste.md', '.claude/memory/x.md')
    assert injected_docs(paths) == ('.claude/rules/taste.md', 'AGENTS.md')


def test_line_widths_counts_every_line_one_based() -> None:
    assert line_widths('ab\nabcd\n\n') == ((1, 2), (2, 4), (3, 0))


def test_a_planted_overwidth_line_and_a_planted_clean_file_are_told_apart(tmp_path: Path) -> None:
    """THE PLANTED CONTROL, both directions, through the REAL scanner."""
    wide = tmp_path / 'AGENTS.md'
    wide.write_text('short line\n' + ('x' * 130) + '\n', encoding='utf-8')
    narrow = tmp_path / 'CLAUDE.md'
    narrow.write_text('every line here fits comfortably under the ceiling\n', encoding='utf-8')

    scan = scan_widths((wide, narrow), root=tmp_path)
    assert scan.overwidth == (Overwidth('AGENTS.md', 2, 130),)
    assert scan.files_read == 2


def test_a_binary_file_is_named_undecodable_not_silently_clean(tmp_path: Path) -> None:
    binary = tmp_path / 'blob.bin'
    binary.write_bytes(b'\xff\xfe\x00\x01')
    scan = scan_widths((binary,), root=tmp_path)
    assert scan.undecodable == ('blob.bin',)
    assert scan.overwidth == ()
    assert scan.files_read == 0


def test_the_ratchet_refuses_both_an_undeclared_hit_and_an_orphaned_declaration() -> None:
    found = (Overwidth('AGENTS.md', 4, 200),)
    undeclared = width_ratchet(found, frozenset())
    assert len(undeclared) == 1
    assert undeclared[0].startswith('UNDECLARED overwidth line -- AGENTS.md:4:')

    orphaned = width_ratchet((), frozenset({'AGENTS.md:4'}))
    assert orphaned == (
        (
            "ORPHANED overwidth declaration 'AGENTS.md:4' -- the line is no longer over width; remove it "
            'from the declared set in this same commit.'
        ),
    )

    assert width_ratchet(found, frozenset({'AGENTS.md:4'})) == ()


def test_width_remedy_names_the_file_line_and_measured_width() -> None:
    line = width_remedy(Overwidth('AGENTS.md', 7, 250))
    assert 'AGENTS.md:7' in line
    assert '250 columns' in line
    assert '120' in line


def test_assert_width_floor_refuses_a_scan_that_read_too_little() -> None:
    with pytest.raises(VacuousWidthScan):
        assert_width_floor(0, 1, 'injected-doc width')
    assert_width_floor(5, 1, 'injected-doc width')  # does not raise


def test_lab_commons_declares_no_overwidth_injected_doc_line() -> None:
    """THE CHECK. Every tracked injected doc fits the ceiling -- the declaration is empty."""
    corpus = injected_docs(tracked_files(_ROOT))
    assert_width_floor(len(corpus), _FLOOR, 'injected-doc width (lab-commons)')
    scan = scan_widths((_ROOT / name for name in corpus), root=_ROOT)
    problems = width_ratchet(scan.overwidth, _DECLARED)
    assert problems == (), 'the injected-doc width ratchet moved:\n  ' + '\n  '.join(problems)
