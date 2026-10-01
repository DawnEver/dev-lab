r"""`docs-src/dev/` DECLINES A FAMILY-CONFIG BASE, because it is shared by REFERENCE and not by COPY.

WHY THIS MODULE EXISTS. `docs-src/dev/` is the last artefact of the config census with no base at
all, and its raw line counts -- 13 / 1 / 1 / 14 across kit, wdg-lab, optimi-lab and the motronics
lane -- read like the largest fork in the family. R6 of
`.claude/memory/2026/09/17/plan-one-source-of-truth-for-the-family-config-layer.md` dissolved that
reading once, in PROSE, and this family has watched prose go stale three times. It is re-measured
here, and the answer is ratcheted both ways.

WHY A BASE IS THE WRONG MECHANISM, stated as the property rather than as an opinion. A
`famconfig.Base` exists to keep N COPIES of one file agreeing -- it renders the shared part into
every repo and diffs what came back. This tree has no copies to keep agreeing: each family page
exists exactly ONCE, in the kit, and what a consumer holds is a POINTER TABLE rendered from
:data:`lab_commons.dev.devdocs.PAGES`. Rendering a page into four repos is precisely the fork the
reference removed, so adopting a base here would UNDO the migration rather than complete it.
`TestTheFamilyPagesExistExactlyOnce` is that sentence as a measurement.

WHAT RE-MEASURING FOUND THAT THE PROSE DID NOT, and it is why this module is not just a pin:

* **The "generated" claim was a declaration that lies.** All four indexes SAY their table is what
  `lab_commons.dev.devdocs.pointer_table` renders, "so a page renamed there does not leave this one
  quietly wrong". Nothing outside this repo has ever called that function: `pointer_table` was run
  once on 2026-09-16 and its output PASTED. A rename upstream would have left three tables of dead
  links saying in their own text that they could not rot.
* **And it had already rotted, at the origin.** The kit's own `docs-src/dev/index.md` table was
  hand-typed rather than rendered: every title agreed with `PAGES` and SIX of the twelve subjects
  did not. Two tables describing the same twelve pages, disagreeing on half of them, with the
  registry-driven one shipped to three other repos. The kit's table is `pointer_table('.')` now.
* The three consumer tables were, by luck, still VERBATIM equal to a live render on 2026-09-19.
  That is the state this module freezes: an equality against a live call, never against a copy.

THE TWO SIDES OF THE RATCHET.

* It reds when the world moves in the direction that re-opens the question: a lab growing a second
  page, a consumer's pointer table drifting from the live render, or a family page appearing as a
  real COPY in a consumer -- the day there are two copies of one page is the day a base has a job.
* It reds when someone acts against the measurement while it still holds: a `famconfig` base or
  Delta declared for this tree, or a renderer stamp pasted into a dev index.

EVERY COUNT BELOW IS AN EQUALITY AGAINST A LIVE READING, never a `<=`. A subset guard is satisfied
by every shorter declaration, which is exactly how `SHARED_GITIGNORE_CORE` sat two short and green.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from _config_census import dev_pages, reachable_repos, read_at_head
from _config_census_rows import REPO_PATHS
from _famconfig_delta import DELTAS

from lab_commons.dev.devdocs import CANONICAL_TREE, PAGES, Page, pointer_table, slugs
from lab_commons.dev.famconfig import BASES, STAMP, ForkedDelta, artefact_base
from lab_commons.dev.famtests.devdocs import COPY_CEILING, copied_fraction, residue_problems

#: The dev index, spelled once. Every repo in the family keeps one and only this one is generated.
INDEX: Final = 'index.md'

#: The committed path of that file inside any repo of the family.
INDEX_PATH: Final = f'{CANONICAL_TREE}/{INDEX}'

#: How each repo REACHES the shared tree, which is the only input `pointer_table` takes. The kit's
#: is `.` because the pages are beside its index; a consumer's is the sibling checkout. Declared as
#: data so the four tables cannot become four hand-typed tables that agree for a while.
POINTER_BASES: Final[dict[str, str]] = {
    'lab-commons': '.',
    'wdg-lab': '../../../lab-commons/docs-src/dev',
    'optimi-lab': '../../../lab-commons/docs-src/dev',
    'motronics-studio': '../../../lab-commons/docs-src/dev',
}

#: The two consumers that kept NOTHING of their own under this tree. Their row in the census reads
#: MOVES, and the claim being measured is that the "1" is the move already executed.
LAB_REPOS: Final[tuple[str, ...]] = ('wdg-lab', 'optimi-lab')

#: The consumer whose row reads SPLITS: it keeps pages of its own AND pointers to the family's.
MOTRONICS: Final = 'motronics-studio'

#: Floors: the readings that would otherwise be vacuous if a reader found nothing. The copy reader and
#: its ceiling are :mod:`lab_commons.dev.famtests.devdocs`' -- the same body a consumer's own suite
#: runs, so the census and the consumer cannot disagree about what a copy is.
REPO_FLOOR: Final = 3
RESIDUE_FLOOR: Final = 5

#: The header every dev-index table starts with. Motronics has TWO tables under it -- the family's
#: and its own -- so a reader keyed on this line alone would compare the wrong one.
TABLE_HEADER: Final = '| page | what it covers |'

_ROW: Final = re.compile(r'^\| \[(?P<title>[^\]]+)\]\((?P<target>[^)]+)\) \| (?P<subject>.+) \|$')


def table_blocks(text: str) -> tuple[str, ...]:
    """Every maximal run of markdown table lines in *text*, header included, in document order."""
    blocks: list[list[str]] = []
    for line in text.splitlines():
        if line.startswith('|'):
            if line == TABLE_HEADER or not blocks or not blocks[-1]:
                blocks.append([])
            blocks[-1].append(line)
        elif blocks and blocks[-1]:
            blocks.append([])
    return tuple('\n'.join(block) for block in blocks if block)


def family_blocks(text: str) -> tuple[str, ...]:
    """Every table in *text* that is a FAMILY pointer table -- one row per declared page, no others.

    Pure over TEXT so the planted controls drive this exact function rather than a second reading of
    the same idea. The identifying property is the ROW SET, not the position or the heading above it:
    motronics' second table has the identical header and links to pages of its own, and a reader
    keyed on the header would have compared that one and called the tree forked.
    """
    declared = set(slugs())
    out: list[str] = []
    for block in table_blocks(text):
        rows = [_ROW.match(line) for line in block.splitlines() if _ROW.match(line)]
        stems = {Path(row['target']).stem for row in rows if row is not None}
        if stems == declared:
            out.append(block)
    return tuple(out)


def copies_of_page(page_text: str, held: dict[str, str | None]) -> tuple[str, ...]:
    """Which repos in *held* hold a COPY of *page_text*, by the ceiling. Pure over its mapping.

    This is the decline's whole argument in one function: a `famconfig` base keeps N copies of a file
    agreeing, so the question "does this tree need one" is the question "how many copies are there".
    """
    return tuple(
        repo
        for repo, text in sorted(held.items())
        if text is not None and copied_fraction(page_text, text) > COPY_CEILING
    )


def _reached() -> dict[str, Path]:
    """Every family repo checked out on this box, with a floor under the reading."""
    reached = reachable_repos(REPO_PATHS)
    assert 'lab-commons' in reached, 'the reader could not find the tree it is running in'
    assert len(reached) >= REPO_FLOOR, (
        f'{sorted(reached)}: fewer than {REPO_FLOOR} repos reached, so nothing below is a family measurement'
    )
    return reached


def _index_of(root: Path) -> str:
    """A repo's committed dev index. Committed, because a census asks what a repo DECLARES."""
    text = read_at_head(root, INDEX_PATH)
    assert text is not None, f'no committed {INDEX_PATH} in {root}'
    return text


def _kit_page(root: Path, slug: str) -> str:
    text = read_at_head(root, f'{CANONICAL_TREE}/{slug}.md')
    assert text is not None, f'{slug}.md is declared in PAGES and not committed in the kit'
    return text


class TestEveryDevIndexIsOneRenderOfOneRegistry:
    """The property the four indexes CLAIM in their own prose, asserted against a live render."""

    def test_each_repo_holds_exactly_one_family_table_and_it_is_the_live_render(self) -> None:
        """EQUALITY against `pointer_table(base)`, not containment and not against a stored copy."""
        reached = _reached()
        for repo, root in sorted(reached.items()):
            found = family_blocks(_index_of(root))
            assert len(found) == 1, (
                f'{repo} holds {len(found)} family pointer tables in {INDEX_PATH}; exactly one is the '
                f'shape every repo here declares'
            )
            assert found[0] == pointer_table(POINTER_BASES[repo]), (
                f"{repo}'s dev index table is not what `pointer_table({POINTER_BASES[repo]!r})` renders "
                f'today. That file says in its own text that it cannot drift from PAGES, so either the '
                f'registry moved and this table was not re-rendered, or the table was hand-edited. '
                f'Re-render it; do not edit this assertion.'
            )

    def test_the_render_covers_every_declared_page_and_the_registry_is_not_empty(self) -> None:
        """The floor. An empty `PAGES` renders an empty table that every index would trivially match."""
        assert len(PAGES) >= 10, f'{len(PAGES)} pages declared; the registry this module measures is nearly empty'
        rendered = pointer_table(POINTER_BASES['lab-commons'])
        for page in PAGES:
            assert f'{page.slug}.md' in rendered, f'{page.slug} is declared and absent from its own render'

    def test_a_planted_rename_upstream_convicts_every_pasted_table(self) -> None:
        """PLANTED CONTROL for the rot the prose promised was impossible, driving the REAL comparator.

        One page is renamed in a COPY of the registry, exactly as a rename upstream would do. Every
        live index must then fail the same equality that passes above -- which is what says the green
        above is a measurement of four files rather than of a constant.
        """
        renamed = tuple(Page('renamed-slug', p.title, p.subject) if i == 0 else p for i, p in enumerate(PAGES))
        assert renamed != PAGES, 'the control renamed nothing'
        for repo, root in sorted(_reached().items()):
            stale = family_blocks(_index_of(root))
            assert stale, f'{repo} had no family table to convict, so this control proves nothing there'
            assert stale[0] != pointer_table(POINTER_BASES[repo], renamed), (
                f'{repo} matches a table rendered from a registry with a RENAMED page, so this '
                f'comparison cannot tell the two apart and the arm above is not checking anything'
            )

    def test_a_planted_local_table_is_not_read_as_the_family_one(self) -> None:
        """PLANTED CONTROL for the reader. motronics' own table has the identical header."""
        local = f'{TABLE_HEADER}\n|---|---|\n| [The gate](gate.md) | THIS repo`s runner |'
        assert table_blocks(local), 'the control planted no table at all'
        assert family_blocks(local) == (), 'a table of the repo`s OWN pages reads as the family table'
        both = f'{pointer_table(".")}\n\nsome prose\n\n{local}'
        assert len(family_blocks(both)) == 1, 'the reader cannot separate the two tables motronics holds'


class TestTheTwoReadersAgreeOnThisRepo:
    """Every reading above is of the COMMITTED file. This is what says that is also the file on disk.

    Without it, an uncommitted edit to this repo's own index makes every arm here describe a document
    nobody else has -- and it is the arm that caught the first run of this module, where the kit's
    regenerated table was in the working tree and the hand-typed one was still at HEAD.
    """

    def test_the_working_tree_and_HEAD_agree_on_this_repos_dev_index(self) -> None:
        """One file, two readers, and a floor under the reading."""
        root = _reached()['lab-commons']
        at_head = family_blocks(_index_of(root))
        in_tree = family_blocks((root / CANONICAL_TREE / INDEX).read_text(encoding='utf-8'))
        assert at_head, 'the HEAD reader found no family table, so every comparison here is against nothing'
        assert in_tree == at_head, (
            'this checkout`s dev index differs from HEAD. Every arm in this module reads the COMMITTED '
            'file, so an uncommitted edit here makes them describe a file nobody else has.'
        )


class TestTheFamilyPagesExistExactlyOnce:
    """THE DECLINE, AS A MEASUREMENT. A base keeps copies agreeing; there is nothing here to keep."""

    def test_every_family_page_is_held_by_the_kit_and_by_nobody_else(self) -> None:
        """The reading that makes a base pointless, taken over all four repos and all twelve pages."""
        reached = _reached()
        consumers = {repo: root for repo, root in reached.items() if repo != 'lab-commons'}
        assert len(consumers) >= REPO_FLOOR - 1, sorted(consumers)
        for slug in slugs():
            page = _kit_page(reached['lab-commons'], slug)
            held = {repo: read_at_head(root, f'{CANONICAL_TREE}/{slug}.md') for repo, root in consumers.items()}
            assert copies_of_page(page, held) == (), (
                f'{slug}.md now exists as a real COPY outside the kit. That is the day this tree has '
                f'two versions of one document to keep agreeing, which is the job a famconfig base '
                f'does -- re-open the decline with this measurement quoted.'
            )

    def test_a_planted_copy_is_convicted_by_the_same_reader(self) -> None:
        """PLANTED CONTROL. Without it the arm above is green on a reader that reads nothing."""
        page = _kit_page(_reached()['lab-commons'], slugs()[0])
        assert copies_of_page(page, {'planted': page}) == ('planted',), 'a verbatim copy is not read as a copy'
        assert copies_of_page(page, {'planted': None}) == (), 'an absent file is read as a copy'
        assert copied_fraction(page, page) == 1.0, 'the fraction reader does not recognise its own input'


class TestTheConsumersKeepPointersAndNotCopies:
    """What each consumer's tree actually holds, as EQUALITIES against the live directories."""

    def test_neither_lab_holds_anything_but_its_index(self) -> None:
        """The MOVES rows, re-measured. A second page here re-opens whether the move finished."""
        reached = _reached()
        for repo in LAB_REPOS:
            if repo not in reached:
                continue
            pages = dev_pages(reached[repo])
            assert pages == {INDEX}, (
                f'{repo} now holds {sorted(pages)} under {CANONICAL_TREE}; its census row says the tree '
                f'is one pointer page, so either a page came back or one of its own was written'
            )

    def test_every_motronics_page_under_a_family_name_is_a_residue(self) -> None:
        """The SPLITS row's own claim, read off the live trees and `slugs()` -- no hand-held name set.

        Through the consumer-side famtest's own pure reader, so the census and motronics' suite judge
        a copy by ONE instrument. Only the stems the family declares are passed: which of motronics'
        OTHER pages may name a family module is motronics' allowlist, asserted in its own suite.
        """
        reached = _reached()
        assert MOTRONICS in reached, (
            f'{MOTRONICS} is not checked out beside lab-commons, so the one SPLITS consumer is unmeasured'
        )
        declared = set(slugs())
        local = {
            name.removesuffix('.md'): read_at_head(reached[MOTRONICS], f'{CANONICAL_TREE}/{name}') or ''
            for name in dev_pages(reached[MOTRONICS])
            if name.removesuffix('.md') in declared
        }
        assert len(local) >= RESIDUE_FLOOR, f'{sorted(local)}: below anything worth calling a split tree'
        family = {slug: _kit_page(reached['lab-commons'], slug) for slug in slugs()}
        problems = residue_problems(local, family, subject_allowlist={})
        assert problems == (), 'motronics pages under a family name that are not residues:\n  ' + '\n  '.join(problems)


class TestNobodyDeclaresABaseWhileTheMeasurementHolds:
    """THE OTHER SIDE. Without it the decline could be made moot instead of re-decided."""

    def test_famconfig_declares_no_artefact_for_this_tree(self) -> None:
        """Through the kit's OWN lookup, so this cannot disagree with what `artefact_base` would say."""
        assert BASES, 'the base table is empty, so this arm would pass against a kit declaring nothing'
        for artefact in (f'{CANONICAL_TREE}/', INDEX, INDEX_PATH):
            assert artefact not in BASES, (
                f'a famconfig Base arrived for {artefact!r}. A base RENDERS a file into every repo, '
                f'which for this tree means four copies of a document that exists once -- flip '
                f'`TestTheFamilyPagesExistExactlyOnce` first, with numbers.'
            )
            try:
                artefact_base(artefact)
            except ForkedDelta:
                continue
            msg = f'artefact_base({artefact!r}) returned a base for a tree nothing declares'
            raise AssertionError(msg)

    def test_the_kit_declares_no_delta_for_a_dev_doc(self) -> None:
        """A Delta is how adoption is declared here; one appearing without a base is the same claim."""
        assert DELTAS, 'the delta table is empty, so this arm would pass against a repo declaring nothing'
        for artefact in (f'{CANONICAL_TREE}/', INDEX, INDEX_PATH):
            assert artefact not in DELTAS, f'a Delta arrived for {artefact!r} while the tree is shared by reference'

    def test_no_dev_index_carries_a_renderer_stamp(self) -> None:
        """A stamp would mean `famconfig` wrote one of these files, which is the adoption nobody argued."""
        for repo, root in sorted(_reached().items()):
            assert STAMP not in _index_of(root), (
                f'{repo}`s {INDEX_PATH} carries the famconfig stamp. Either it was rendered -- declare '
                f'it and flip the arms above -- or a stamp was pasted into a file nobody rendered.'
            )
