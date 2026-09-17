"""DOCS-SPLIT and DECLARATION-LIES, over this repo's own always-loaded rules pages.

`.claude/rules/**` is read on EVERY turn, which is what makes it expensive and what makes it drift.
Two constraints keep it honest, and they pull in opposite directions on purpose:

* A LINE RATCHET. The pages are hard constraints only; mechanism belongs in the code that enforces
  it and reasoning belongs in `.claude/memory/`. Without a ceiling, the cheapest place to put any
  new thought is the file every turn already pays for, and the pages become a document nobody reads
  because it is too long to read.
* EVERY CITED RULE ID RESOLVES. A page cites the shared registry by ID rather than restating the
  statement -- two statements of one rule is exactly the drift the registry removes. An ID that no
  longer exists is then the dominant defect verbatim: a citation that reads as a guarantee and
  points at nothing. Renaming a row must red HERE, in the repo that owns the row.

AND NO PROSE MARKDOWN UNDER ``src/``. A page that ships inside the package is loaded by nobody and
reviewed by nobody, and it is the one place a retired spelling survives longest.
"""

from __future__ import annotations

import re
from pathlib import Path

from _arch_corpus import _tracked, assert_floor, rel, rules_pages

from lab_commons.dev.rules import RULES

#: The always-loaded budget, MEASURED 2026-09-15. It may only go DOWN, and a new page is paid for
#: out of it rather than added beside it.
RULES_LINE_CEILING = 60

#: A rules page must exist at all: a ceiling over an empty directory is a check that cannot fail.
RULES_PAGE_FLOOR = 2

#: A cited rule ID: an upper-case slug with at least one hyphen, so ordinary emphatic prose
#: ("STATEMENT", "ABSENT") is not mistaken for a citation the registry has to answer for.
_CITATION = re.compile(r'\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\b')


def dangling_citations(pages: tuple[Path, ...], known: frozenset[str]) -> tuple[str, ...]:
    """Every rule ID a page cites that *known* does not define -- pure over its arguments."""
    out: list[str] = []
    for page in pages:
        out.extend(
            f'{page.name} cites {cited}, which the registry does not define'
            for cited in sorted(set(_CITATION.findall(page.read_text(encoding='utf-8'))))
            if cited not in known
        )
    return tuple(out)


def test_every_rule_id_a_page_cites_resolves() -> None:
    """THE CHECK. A renamed or deleted row reds here, in the repo that owns the row."""
    pages = rules_pages()
    assert_floor(len(pages), RULES_PAGE_FLOOR, 'rules page')
    known = frozenset(rule.id for rule in RULES)
    text = '\n'.join(page.read_text(encoding='utf-8') for page in pages)
    assert _CITATION.search(text), 'no page cites a rule ID, so this guard proved nothing about any page'
    problems = dangling_citations(pages, known)
    assert problems == (), 'a citation points at nothing:\n  ' + '\n  '.join(problems)


def test_the_rules_pages_stay_inside_their_budget() -> None:
    """The ratchet on prose that is read on every turn."""
    pages = rules_pages()
    assert_floor(len(pages), RULES_PAGE_FLOOR, 'rules budget')
    total = sum(len(page.read_text(encoding='utf-8').splitlines()) for page in pages)
    assert total <= RULES_LINE_CEILING, (
        f'{total} lines of always-loaded rules, above the {RULES_LINE_CEILING} ceiling. Mechanism '
        f'belongs in the code that enforces it and reasoning in .claude/memory/; a new page is paid '
        f'for out of this budget rather than added beside it.'
    )


def test_no_prose_markdown_ships_inside_the_package() -> None:
    """A page under ``src/`` is loaded by nobody, reviewed by nobody, and retires nothing."""
    stowaways = [name for name in _tracked() if name.startswith('src/') and name.endswith('.md')]
    assert stowaways == [], f'prose shipped inside the package: {stowaways}'


def test_a_planted_dangling_citation_is_refused(tmp_path: Path) -> None:
    """THE PLANTED CONTROL, through the REAL matcher, with a live citation alongside."""
    page = tmp_path / 'planted.md'
    page.write_text('- cites `DECLARATION-LIES` and `NOT-A-RULE-AT-ALL`, and STATEMENT is prose.\n', encoding='utf-8')
    problems = dangling_citations((page,), frozenset({'DECLARATION-LIES'}))
    assert problems == ('planted.md cites NOT-A-RULE-AT-ALL, which the registry does not define',)


def test_the_guard_reads_this_repo_s_pages() -> None:
    """The corpus really is `.claude/rules/`, spelled the way a refusal would spell it."""
    assert {rel(p) for p in rules_pages()} >= {'.claude/rules/downstream.md'}
