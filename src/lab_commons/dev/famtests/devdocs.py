"""A consumer's local dev page under a FAMILY page's name is a RESIDUE, never a copy.

WHAT THIS REFUSES. :mod:`lab_commons.dev.devdocs` declares the family's mechanism pages, and each
exists ONCE, in lab-commons' ``docs-src/dev/``. A consuming repo may keep a page of the same STEM --
but only as that repo's DELTA: it links the family page in its first lines, and it repeats almost
none of it. Two drifts re-open the fork the sharing removed, and both had happened by 2026-09-30:

* **A re-copy.** A local page that restates the family page is a second version of one document.
  It agrees for a while, and then the two are two documents.
* **A family subject written locally under a NEW name.** ConsumerA' ``translations.md`` documented
  :mod:`lab_commons.dev.cjk` and :mod:`lab_commons.dev.famtests.trackedcjk` -- family modules -- as a
  local page with no family twin. A residue check keyed on the family's stems cannot see that, so the
  second arm asks what the page is ABOUT: a local page whose LEAD names a ``lab_commons.dev`` module
  is taking it as its subject, and is refused unless the consumer's own allowlist says why.

WHY 6-WORD SHINGLES AND NOT LINES. A line-equality reader is blind to a copy re-wrapped, re-bulleted
or lightly re-worded at its edges, which is how prose is actually copied. A 6-word shingle survives
re-wrapping and still does not fire on a shared PHRASE -- the same instrument consumer-a'
``test_rules_line_ratchet.py`` used to measure its rules pages against ``docs-src/dev/``.

EVERY REPO-SHAPED FACT IS AN ARGUMENT WITH NO DEFAULT (see :mod:`lab_commons.dev.famtests`): where the
consumer's tree is, where it reaches the family tree, and its allowlist with a REASON per row. The
allowlist is two-sided: a row whose page no longer names a family module, or no longer exists, is
STALE and refused, so the set can only shrink.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons.dev.devdocs import CANONICAL_TREE, pointer_table, slugs

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    'COPY_CEILING',
    'LINK_WINDOW',
    'SHINGLE_WORDS',
    'UPSTREAM_SHINGLE_FLOOR',
    'assert_local_dev_pages_are_residues',
    'assert_the_index_holds_the_live_table',
    'copied_fraction',
    'family_subjects',
    'local_pages',
    'residue_problems',
    'shingles',
]

#: Words per shingle. Six is long enough that two pages sharing one did not do so by idiom.
SHINGLE_WORDS: Final = 6

#: The share of a family page's shingles a residue may repeat. A verbatim copy reads 1.0; a residue
#: that cites the family page's NAMES (a module path, a rule ID) reads a few percent.
COPY_CEILING: Final = 0.10

#: How many lines from the top the family link must appear in -- the title, a blank, the lead.
LINK_WINDOW: Final = 5

#: A family page with fewer shingles than this has nothing to copy, so a 0.0 against it is vacuous.
UPSTREAM_SHINGLE_FLOOR: Final = 50

_WORD: Final = re.compile(r'[a-z0-9_]+')
_FAMILY_MODULE: Final = re.compile(r'\blab_commons\.dev(?:\.[A-Za-z_][A-Za-z0-9_]*)+')


def shingles(text: str, words: int = SHINGLE_WORDS) -> frozenset[tuple[str, ...]]:
    """Every run of *words* consecutive words in *text*, case- and punctuation-blind."""
    tokens = _WORD.findall(text.lower())
    return frozenset(tuple(tokens[i : i + words]) for i in range(len(tokens) - words + 1))


def copied_fraction(upstream: str, local: str) -> float:
    """What share of *upstream*'s shingles *local* repeats. A residue reads ~0, a copy 1.0.

    Raises rather than returning 0.0 for an upstream too short to copy: "no overlap with an empty
    page" is the vacuous green this family has convicted one-sided floors for.
    """
    source = shingles(upstream)
    if len(source) < UPSTREAM_SHINGLE_FLOOR:
        msg = f'{len(source)} shingles upstream, below the floor of {UPSTREAM_SHINGLE_FLOOR}: nothing to copy'
        raise AssertionError(msg)
    return len(source & shingles(local)) / len(source)


def family_subjects(text: str) -> frozenset[str]:
    """The ``lab_commons.dev`` modules a page's LEAD names -- the first :data:`LINK_WINDOW` lines."""
    lead = '\n'.join(text.splitlines()[:LINK_WINDOW])
    return frozenset(_FAMILY_MODULE.findall(lead))


def _links_family_page(text: str, slug: str) -> bool:
    lead = '\n'.join(text.splitlines()[:LINK_WINDOW])
    return f'lab-commons/{CANONICAL_TREE}/{slug}.md)' in lead


def _residue_problems(stem: str, text: str, family: Mapping[str, str]) -> list[str]:
    out = []
    if not _links_family_page(text, stem):
        out.append(
            f'{stem}.md: under a family page`s name and does not link '
            f'`.../lab-commons/{CANONICAL_TREE}/{stem}.md` in its first {LINK_WINDOW} lines'
        )
    if stem in family:
        fraction = copied_fraction(family[stem], text)
        if fraction > COPY_CEILING:
            out.append(
                f'{stem}.md: repeats {fraction:.1%} of the family page`s {SHINGLE_WORDS}-word shingles, '
                f'over {COPY_CEILING:.0%} -- it is a copy; delete what the family page says and keep '
                f'only this repo`s delta'
            )
    return out


def _allowlist_problems(local: Mapping[str, str], subject_allowlist: Mapping[str, str]) -> list[str]:
    out = []
    for stem, reason in sorted(subject_allowlist.items()):
        if not reason.strip():
            out.append(f'{stem}: allowlisted with no reason')
        if stem not in local:
            out.append(f'{stem}: allowlisted and no such local page exists -- delete the row')
        elif stem in slugs() or not family_subjects(local[stem]):
            out.append(f'{stem}: allowlisted and no longer needs it -- delete the row')
    return out


def residue_problems(
    local: Mapping[str, str],
    family: Mapping[str, str],
    *,
    subject_allowlist: Mapping[str, str],
) -> tuple[str, ...]:
    """Every way *local* (stem -> text) fails to be residues of *family* (slug -> text). Pure.

    *family* must hold every declared slug: a family page this reader cannot see is a page it cannot
    compare against, which is refused rather than skipped.
    """
    declared = slugs()
    out = [f'{slug}: a declared family page with no text to compare against' for slug in declared if slug not in family]
    for stem, text in sorted(local.items()):
        if stem in declared:
            out += _residue_problems(stem, text, family)
            continue
        subjects = family_subjects(text)
        if subjects and stem not in subject_allowlist:
            out.append(
                f'{stem}.md: its lead takes {sorted(subjects)} as its subject, which is a FAMILY module with no '
                f'family page here -- upstream it to lab-commons `{CANONICAL_TREE}/`, or allowlist it with a reason'
            )
    out += _allowlist_problems(local, subject_allowlist)
    return tuple(out)


def local_pages(root: Path) -> dict[str, str]:
    """Every ``docs-src/dev/*.md`` in the tree at *root*, by stem, the index excluded."""
    directory = root.joinpath(*CANONICAL_TREE.split('/'))
    return {
        path.stem: path.read_text(encoding='utf-8') for path in sorted(directory.glob('*.md')) if path.stem != 'index'
    }


def assert_local_dev_pages_are_residues(
    root: Path,
    *,
    family_root: Path,
    subject_allowlist: Mapping[str, str],
) -> None:
    """The consumer's verdict: every local dev page is a residue, and none adopts a family subject.

    *root* is the consumer's checkout, *family_root* a lab-commons checkout (the pages are not in the
    wheel). Both REFUSE when absent: "I could not look" is not "nothing was copied".
    """
    pages = local_pages(root)
    if not pages:
        msg = f'no pages under {root / CANONICAL_TREE}, so nothing below is a measurement'
        raise AssertionError(msg)
    family_dir = family_root.joinpath(*CANONICAL_TREE.split('/'))
    if not family_dir.is_dir():
        msg = f'no family tree at {family_dir}; clone lab-commons there'
        raise AssertionError(msg)
    family = {
        slug: (family_dir / f'{slug}.md').read_text(encoding='utf-8')
        for slug in slugs()
        if (family_dir / f'{slug}.md').is_file()
    }
    problems = residue_problems(pages, family, subject_allowlist=subject_allowlist)
    if problems:
        msg = 'local dev pages that are not residues of the family tree:\n  ' + '\n  '.join(problems)
        raise AssertionError(msg)


def assert_the_index_holds_the_live_table(*, root: Path, base: str) -> None:
    """The consumer's verdict on ITS OWN dev index: exactly one copy of the LIVE family pointer table.

    *base* is how this repo reaches the family pages (a relative sibling path or the forge URL), and
    the table is re-rendered from the registry rather than compared with a stored copy -- so a page
    added or renamed upstream reds here until this repo re-renders. Moved here 2026-10-03 from a kit
    test that reached into every consumer checkout: a test judges the repo it lives in.
    """
    index = root.joinpath(*CANONICAL_TREE.split('/'), 'index.md')
    if not index.is_file():
        msg = f'no dev index at {index}; the family pointer table has nowhere to live'
        raise AssertionError(msg)
    table = pointer_table(base)
    found = index.read_text(encoding='utf-8').count(table)
    if found != 1:
        msg = (
            f'{index} holds {found} copies of the live family pointer table (want exactly 1). Re-render it: '
            f'paste lab_commons.dev.devdocs.pointer_table({base!r}) in place of the old table.'
        )
        raise AssertionError(msg)
