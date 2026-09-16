"""The family's MECHANISM DOCS, declared as data so a consumer's pointer cannot rot.

THE DEFECT THIS CLOSES, MEASURED 2026-09-16. The universal rule STATEMENTS were unified into
:mod:`lab_commons.dev.rules` on 2026-09-15, each row carrying its ID, its statement and the
mechanism that refuses a violation. **The MECHANISM DOCS were not.** So the four repos cited rules
by ID and had nothing that explained how the mechanism works: ``motronics-studio`` held 14 dev
documents totalling roughly 1300 lines, of which ten were not about motors at all; ``wdg-lab`` held
one document and it was its own architecture; ``optimi-lab`` and this repo held none. Three of four
repos had no written mechanism, while one held all of it under a name that made it look local.

THE SUBJECT TEST decides what is here, and it is the same shape as the noun test in
:mod:`lab_commons.dev.rules`: **does the document's SUBJECT change when you change repos?** The BOX,
GIT, THE FORGE or THE FAMILY'S PROCESS is the family's. Motors, solvers, meshes and cases stay home.
A document that fails the test on half its sections is SPLIT at that seam rather than moved whole.

WHY THIS MODULE IS DATA AND NOT THE PROSE. ``tests/test_arch_rules_pages.py`` refuses prose markdown
under ``src/``, and it is right to: a page shipped inside a package is loaded by nobody and reviewed
by nobody. So the pages live in ``docs-src/dev/`` of THIS repo -- one copy, in the open -- and what
ships is the TABLE OF CONTENTS. That is the half a consumer needs, because the failure this migration
exists to avoid is a consuming repo COPYING a shared page, which is the fork the sharing removed.

SO THE CONSUMER SIDE IS GENERATED. A repo's own dev index calls :func:`pointer_table` and pastes what
it returns, or renders it at build time; either way the row set comes from here. A page added, renamed
or retired here changes every consumer's pointer at its next render instead of leaving four hand-typed
tables that agree for a while. :func:`missing_pages` is the other half of the same ratchet, checked by
this repo's own test suite: a row naming a file that is not on disk is a citation pointing at nothing.

WHAT IS NOT HERE. Any BUILD of these pages. :mod:`lab_commons.dev.docsite` is the family's docs
driver and a rendered portal for this tree would be a sub-site row in whichever repo wants one. No
such row exists today, and saying so is the point: "the docs are built" would be the declaration that
lies, and a reader who expects a portal and finds markdown has been told something false.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Final, NamedTuple

__all__ = [
    'CANONICAL_TREE',
    'PAGES',
    'Page',
    'docs_dir',
    'missing_pages',
    'page_path',
    'pointer_table',
    'slugs',
]

#: Where the pages live, relative to this repo's root. A consumer reaches them by reading this
#: repo -- a checkout beside its own, or the file's page on the forge -- and never by copying one in.
CANONICAL_TREE: Final = 'docs-src/dev'


class Page(NamedTuple):
    """One family mechanism document: its slug, its title, and the subject it owns."""

    slug: str
    title: str
    subject: str


#: One row per page under :data:`CANONICAL_TREE`. ORDER IS READING ORDER, not alphabetical: a reader
#: arriving at the family's process for the first time needs the participants before the verdict they
#: all cite, and the verdict before the branch layers that spend it.
PAGES: Final[tuple[Page, ...]] = (
    Page(
        'the-three-participants',
        'The three participants',
        'Who does what: the human, the concurrent dev agents, the coordinator that absorbs their work',
    ),
    Page(
        'verdict-model',
        'The verdict model',
        'What a verdict IS, why it starts INCONCLUSIVE, the three tiers and the destination each one gates',
    ),
    Page(
        'testing-discipline',
        'Testing discipline',
        'The lightweight/heavy partition, xfail never skip, one test session at a time',
    ),
    Page(
        'branch-layers',
        'Branch layers',
        'What a lane, an integration branch and `main` each PROVE, and why one cannot substitute for another',
    ),
    Page(
        'alignment',
        'Alignment',
        'The framework every branch develops against so an integration conflicts on CODE, never on bookkeeping',
    ),
    Page(
        'fanout',
        'Fan-out',
        'Parallel lanes in worktrees: environments, subagent bases, the shared hazards, landing',
    ),
    Page(
        'shared-checkout',
        'The shared checkout',
        "Where a tool's correctness argument stops transferring when the checkout is not exclusive",
    ),
    Page(
        'orphans',
        'Killed runs and orphans',
        'What survives a stopped run, why a lock does not time out, and the census a reaper needs',
    ),
    Page(
        'box-resources',
        'Box resources',
        'What one workstation rations, the four defects measured in doing it by hand, and the broker shape',
    ),
    Page(
        'forge',
        'The forge',
        'How `main` is protected on a self-hosted forge: the push whitelist, the status check, branch disposal',
    ),
    Page(
        'retirement',
        'Retirement',
        'An archive and a retired-spelling registry are a PLACE and a RULE, and why the rule cannot live in the place',
    ),
    Page(
        'docs-pipeline',
        'The docs pipeline',
        'The three properties a docs builder must hold, and why an unbuilt sub-site is announced rather than silent',
    ),
)


def slugs() -> tuple[str, ...]:
    """Every page slug, in reading order."""
    return tuple(page.slug for page in PAGES)


def docs_dir(root: Path) -> Path:
    """The pages directory inside a lab-commons checkout rooted at *root*."""
    return root.joinpath(*CANONICAL_TREE.split('/'))


def page_path(root: Path, slug: str) -> Path:
    """The file one page is in. Raises :class:`KeyError` for a slug the registry does not declare."""
    if slug not in slugs():
        msg = f'{slug!r} is not a family mechanism page; declared: {", ".join(slugs())}'
        raise KeyError(msg)
    return docs_dir(root) / f'{slug}.md'


def missing_pages(root: Path) -> tuple[str, ...]:
    """Every declared slug with no file, and every file with no row -- BOTH sides, in one call.

    Two-sided on purpose. A row naming an absent file is a citation pointing at nothing; a page
    nobody declared is a page no consumer's pointer table will ever show, which is the same failure
    wearing the opposite sign. Pure over *root* so a planted tree can drive this function rather
    than a re-implementation of it.
    """
    directory = docs_dir(root)
    declared = set(slugs())
    present = {path.stem for path in sorted(directory.glob('*.md'))} - {'index'}
    out = [f'{slug}: declared with no file at {CANONICAL_TREE}/{slug}.md' for slug in sorted(declared - present)]
    out += [f'{stem}: a page under {CANONICAL_TREE} that no row declares' for stem in sorted(present - declared)]
    return tuple(out)


def pointer_table(base: str, pages: Iterable[Page] = PAGES) -> str:
    """The markdown table a CONSUMING repo puts in its own dev index, generated from the rows.

    *base* is how that repo reaches this one -- a relative path to a sibling checkout, or the forge
    URL of ``docs-src/dev``. It is the caller's because only the caller knows how it reaches the
    shared tree; everything else comes from :data:`PAGES`, so four repos cannot drift into four
    different tables of contents.
    """
    rows = '\n'.join(f'| [{page.title}]({base.rstrip("/")}/{page.slug}.md) | {page.subject} |' for page in pages)
    return f'| page | what it covers |\n|---|---|\n{rows}'
