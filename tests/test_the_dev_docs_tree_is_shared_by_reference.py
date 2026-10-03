r"""`docs-src/dev/` DECLINES A FAMILY-CONFIG BASE, because it is shared by REFERENCE and not by COPY.

WHY THIS MODULE EXISTS. `docs-src/dev/` is the last artefact of the config census with no base at
all, and its raw line counts -- 13 / 1 / 1 / 14 across kit, consumer-b, consumer-c and the consumer-a
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

from _config_census import reachable_repos, read_at_head
from _config_census_rows import REPO_PATHS
from _famconfig_delta import DELTAS

from lab_commons.dev.devdocs import CANONICAL_TREE, PAGES, pointer_table, slugs
from lab_commons.dev.famconfig import BASES, ForkedDelta, artefact_base
from lab_commons.dev.famtests.devdocs import COPY_CEILING, copied_fraction

#: The dev index, spelled once. Every repo in the family keeps one and only this one is generated.
INDEX: Final = 'index.md'

#: The committed path of that file inside any repo of the family.
INDEX_PATH: Final = f'{CANONICAL_TREE}/{INDEX}'

#: How each repo REACHES the shared tree, which is the only input `pointer_table` takes. The kit's
#: is `.` because the pages are beside its index; a consumer's climbs out of its own
#: `docs-src/dev/` and then out of however deep `REPO_PATHS` places it under the family root, so the
#: layout is declared ONCE. Until 2026-10-01 these were typed as siblings, and consumer-b -- one level
#: deeper, and already rendering `../../../../` -- read as a stale table it was not.
POINTER_BASES: Final[dict[str, str]] = {
    'lab-commons': '.',
    **{
        repo: '../' * (CANONICAL_TREE.count('/') + 1 + path.count('/') + 1) + f'lab-commons/{CANONICAL_TREE}'
        for repo, path in REPO_PATHS.items()
    },
}

#: The two consumers that kept NOTHING of their own under this tree. Their row in the census reads
#: MOVES, and the claim being measured is that the "1" is the move already executed.
LAB_REPOS: Final[tuple[str, ...]] = ('consumer-b', 'consumer-c')

#: The consumer whose row reads SPLITS: it keeps pages of its own AND pointers to the family's.
CONSUMER_A: Final = 'consumer-a'

#: Floors: the readings that would otherwise be vacuous if a reader found nothing. The copy reader and
#: its ceiling are :mod:`lab_commons.dev.famtests.devdocs`' -- the same body a consumer's own suite
#: runs, so the census and the consumer cannot disagree about what a copy is.
REPO_FLOOR: Final = 3
RESIDUE_FLOOR: Final = 5

#: The header every dev-index table starts with. ConsumerA has TWO tables under it -- the family's
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
    consumer-a' second table has the identical header and links to pages of its own, and a reader
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

    def test_the_render_covers_every_declared_page_and_the_registry_is_not_empty(self) -> None:
        """The floor. An empty `PAGES` renders an empty table that every index would trivially match."""
        assert len(PAGES) >= 10, f'{len(PAGES)} pages declared; the registry this module measures is nearly empty'
        rendered = pointer_table(POINTER_BASES['lab-commons'])
        for page in PAGES:
            assert f'{page.slug}.md' in rendered, f'{page.slug} is declared and absent from its own render'

    def test_a_planted_local_table_is_not_read_as_the_family_one(self) -> None:
        """PLANTED CONTROL for the reader. consumer-a' own table has the identical header."""
        local = f'{TABLE_HEADER}\n|---|---|\n| [The gate](gate.md) | THIS repo`s runner |'
        assert table_blocks(local), 'the control planted no table at all'
        assert family_blocks(local) == (), 'a table of the repo`s OWN pages reads as the family table'
        both = f'{pointer_table(".")}\n\nsome prose\n\n{local}'
        assert len(family_blocks(both)) == 1, 'the reader cannot separate the two tables consumer-a holds'


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
