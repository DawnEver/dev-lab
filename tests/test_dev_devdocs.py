"""The family mechanism docs: every row has a page, every page has a row, and the pointer is generated.

DECLARATION-LIES and FLOOR-ON-EVERY-SCAN, over a table of contents. A pointer table that a consuming
repo hand-copies is the fork this migration removed, so the table is GENERATED from the rows -- and a
generated table is only as honest as the rows, which is what the two-sided check below is for.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lab_commons.dev.devdocs import (
    CANONICAL_TREE,
    PAGES,
    Page,
    docs_dir,
    missing_pages,
    page_path,
    pointer_table,
    slugs,
)

ROOT = Path(__file__).resolve().parents[1]

#: The floor: a table of contents with one row proves nothing about a migration. MEASURED 2026-09-16,
#: the day the pages landed: 12 rows. Set below it, because a floor refuses an UNREAD registry rather
#: than pinning a count that reds on every page added.
PAGE_FLOOR = 8


def test_the_registry_is_not_vacuous() -> None:
    """A scan over an empty table is green for the wrong reason."""
    assert len(PAGES) >= PAGE_FLOOR, f'{len(PAGES)} family pages, below the {PAGE_FLOOR} floor'
    assert len(set(slugs())) == len(PAGES), 'a slug is declared twice'


def test_every_row_has_a_page_and_every_page_has_a_row() -> None:
    """THE CHECK, both sides. A row naming nothing, or a page nobody points at, reds here."""
    assert docs_dir(ROOT).is_dir(), f'{CANONICAL_TREE} does not exist in this checkout'
    problems = missing_pages(ROOT)
    assert problems == (), 'the family docs registry and its tree disagree:\n  ' + '\n  '.join(problems)


def test_a_planted_tree_reds_on_both_sides(tmp_path: Path) -> None:
    """THE PLANTED CONTROL, through the REAL function, on each side separately."""
    tree = docs_dir(tmp_path)
    tree.mkdir(parents=True)
    for slug in slugs():
        (tree / f'{slug}.md').write_text('- a page\n', encoding='utf-8')
    assert missing_pages(tmp_path) == ()

    (tree / f'{slugs()[0]}.md').unlink()
    (tree / 'an-undeclared-page.md').write_text('- a page\n', encoding='utf-8')
    problems = missing_pages(tmp_path)
    assert any(slugs()[0] in p and 'no file' in p for p in problems), problems
    assert any('an-undeclared-page' in p and 'no row' in p for p in problems), problems


def test_an_index_page_is_not_mistaken_for_a_missing_row(tmp_path: Path) -> None:
    """The directory's own index is navigation, not a mechanism page, and must not red the scan."""
    tree = docs_dir(tmp_path)
    tree.mkdir(parents=True)
    for slug in slugs():
        (tree / f'{slug}.md').write_text('- a page\n', encoding='utf-8')
    (tree / 'index.md').write_text('- navigation\n', encoding='utf-8')
    assert missing_pages(tmp_path) == ()


def test_an_undeclared_slug_raises_rather_than_returning_a_path() -> None:
    """A path built for a page that does not exist is a declaration that lies, one call later."""
    with pytest.raises(KeyError, match='not a family mechanism page'):
        page_path(ROOT, 'a-page-nobody-wrote')
    assert page_path(ROOT, slugs()[0]).name == f'{slugs()[0]}.md'


def test_the_pointer_table_is_generated_from_the_rows() -> None:
    """The consumer side is rendered, never hand-copied -- and the base is the caller's alone."""
    table = pointer_table('../../lab-commons/docs-src/dev')
    assert table.splitlines()[:2] == ['| page | what it covers |', '|---|---|']
    assert len(table.splitlines()) == len(PAGES) + 2
    for page in PAGES:
        assert f'[{page.title}](../../lab-commons/docs-src/dev/{page.slug}.md)' in table
    assert pointer_table('https://example.invalid/dev/', (Page('s', 'T', 'what'),)).endswith(
        '| [T](https://example.invalid/dev/s.md) | what |'
    )
