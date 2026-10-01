"""The controls for :mod:`lab_commons.dev.famtests.devdocs` -- each arm fires on a plant, and is silent beside it.

A residue check that reads nothing and a residue check that reads everything as a copy both pass a
one-sided test, so every arm here is driven both ways through the REAL function, over planted trees
rather than a consumer's answer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lab_commons.dev.devdocs import CANONICAL_TREE, slugs
from lab_commons.dev.famtests.devdocs import (
    COPY_CEILING,
    assert_local_dev_pages_are_residues,
    copied_fraction,
    family_subjects,
    residue_problems,
    shingles,
)

ROOT = Path(__file__).resolve().parents[1]

#: A family page long enough to clear the shingle floor, distinct per slug.
_BODY = ' '.join(f'word{i} sits in sentence number {i} of the family page' for i in range(40))


def _family() -> dict[str, str]:
    return {slug: f'# {slug}\n\n- {slug} {_BODY}\n' for slug in slugs()}


def _residue(slug: str) -> str:
    return f'# {slug} here\n\n- Read [it](../../../lab-commons/{CANONICAL_TREE}/{slug}.md) first.\n- Local delta.\n'


def test_shingles_are_wrapping_and_case_blind() -> None:
    """A copy re-wrapped onto new lines is still a copy; that is why lines were not the unit."""
    text = 'One two three four five six seven'
    assert shingles(text) == shingles('one TWO three\nfour, five six - seven')
    assert len(shingles(text)) == 2


def test_copied_fraction_reads_a_copy_as_one_and_refuses_an_empty_upstream() -> None:
    page = _family()[slugs()[0]]
    assert copied_fraction(page, page) == 1.0
    assert copied_fraction(page, 'nothing in common at all here today') == 0.0
    with pytest.raises(AssertionError, match='nothing to copy'):
        copied_fraction('too short', page)


def test_honest_residues_and_a_plain_local_page_read_clean() -> None:
    local = {slug: _residue(slug) for slug in slugs()[:3]} | {'motors': '# Motors\n\n- Only ours.\n'}
    assert residue_problems(local, _family(), subject_allowlist={}) == ()


def test_a_residue_with_no_family_link_in_its_lead_is_refused() -> None:
    slug = slugs()[0]
    late = '# x\n\n- a\n- b\n- c\n- ' + _residue(slug)
    problems = residue_problems({slug: late}, _family(), subject_allowlist={})
    assert any('does not link' in p for p in problems), problems


def test_a_recopied_family_page_is_refused() -> None:
    slug = slugs()[0]
    family = _family()
    copy = _residue(slug) + family[slug]
    assert copied_fraction(family[slug], copy) > COPY_CEILING
    problems = residue_problems({slug: copy}, family, subject_allowlist={})
    assert any('it is a copy' in p for p in problems), problems


def test_a_family_subject_under_a_local_name_is_refused_unless_allowlisted() -> None:
    page = '# Translations\n\n- How `lab_commons.dev.cjk` exempts a translation.\n'
    assert family_subjects(page) == {'lab_commons.dev.cjk'}
    problems = residue_problems({'local-cjk': page}, _family(), subject_allowlist={})
    assert any('FAMILY module' in p for p in problems), problems
    assert residue_problems({'local-cjk': page}, _family(), subject_allowlist={'local-cjk': 'ours'}) == ()


def test_the_allowlist_is_two_sided() -> None:
    """A row with no reason, no page, or a page that no longer needs it, is refused."""
    plain = {'motors': '# Motors\n\n- Only ours.\n'}
    assert any('no reason' in p for p in residue_problems(plain, _family(), subject_allowlist={'motors': ' '}))
    assert any('no such local page' in p for p in residue_problems({}, _family(), subject_allowlist={'gone': 'x'}))
    assert any('no longer needs it' in p for p in residue_problems(plain, _family(), subject_allowlist={'motors': 'x'}))


def test_a_family_page_the_reader_cannot_see_is_refused() -> None:
    family = _family()
    del family[slugs()[0]]
    assert any('no text to compare' in p for p in residue_problems({}, family, subject_allowlist={}))


def test_the_filesystem_verdict_over_a_planted_consumer_and_this_family_tree(tmp_path: Path) -> None:
    """Driven against THIS repo's real pages, so the floor and the reader are exercised for real."""
    tree = tmp_path.joinpath(*CANONICAL_TREE.split('/'))
    tree.mkdir(parents=True)
    (tree / 'index.md').write_text('# index\n', encoding='utf-8')
    for slug in slugs():
        (tree / f'{slug}.md').write_text(_residue(slug), encoding='utf-8')
    assert_local_dev_pages_are_residues(tmp_path, family_root=ROOT, subject_allowlist={})

    slug = slugs()[0]
    real = (ROOT / CANONICAL_TREE / f'{slug}.md').read_text(encoding='utf-8')
    (tree / f'{slug}.md').write_text(_residue(slug) + real, encoding='utf-8')
    with pytest.raises(AssertionError, match='it is a copy'):
        assert_local_dev_pages_are_residues(tmp_path, family_root=ROOT, subject_allowlist={})


def test_an_absent_tree_refuses_rather_than_passing(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match='nothing below is a measurement'):
        assert_local_dev_pages_are_residues(tmp_path, family_root=ROOT, subject_allowlist={})
    tree = tmp_path.joinpath(*CANONICAL_TREE.split('/'))
    tree.mkdir(parents=True)
    (tree / 'motors.md').write_text('# Motors\n', encoding='utf-8')
    with pytest.raises(AssertionError, match='clone lab-commons'):
        assert_local_dev_pages_are_residues(tmp_path, family_root=tmp_path / 'nowhere', subject_allowlist={})
