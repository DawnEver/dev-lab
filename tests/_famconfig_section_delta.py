r"""The four repos' RUFF SECTION deltas -- data, computed by nothing, one entry per repo.

THE GAP THIS CLOSES, MEASURED 2026-09-18. :data:`lab_commons.dev.famconfig.RUFF_SECTIONS` landed with
21 tests and every one of them drove a PLANTED file: a scan of ``tests/`` and ``src/`` for the three
names that base publishes returned nothing outside the module defining them and the kit's re-export.
A base nothing runs over a real tree is the shape this family's taste rule already names -- "a
capability that disappears, or a waiver nothing uses, is as wrong as its opposite" -- so this file is
the consumer side of that base, and the suite beside it is what drives it.

WHY THE KIT DECLARES THREE OTHER REPOS' DELTAS. It already does, twice, for the same reason: a base
is a claim about four trees, and a claim nobody re-derives ages fastest. `PRECOMMIT_OWN_HOOKS` and
`CONSUMER_IGNORE_DELTA` in `_config_census_rows.py` are the precedent, and the suite beside this file
re-measures every entry here against the live checkouts rather than trusting it.

WHAT WAS MEASURED, by parsing the live ruff config of `lab-commons`, `wdg-lab`, `optimi-lab` and the
motronics-studio LANE at ``.claude/worktrees/feat/optimi-lab`` -- never the main checkout:

* ``select`` -- 58 in all four, four-way symmetric difference EMPTY. Nobody adds and nobody drops, so
  every absent ``added['select']`` below is a stated answer rather than an omission.
* ``ignore`` -- intersection 10, union 67; the 10 are exactly what the KIT ignores. So the kit's
  delta is EMPTY and each consumer's delta IS its own waiver set. That asymmetry is the whole arm:
  a base asserting PRESENCE could not see a consumer ADD a waiver, and adding one is the move.
* ``line-length`` 120 and ``quote-style`` single in all four, so no scalar drop exists anywhere.
* ``target-version`` is in NO base (`RUFF_TARGET_VERSIONS` records why), so no delta names it.

THE DROP MAPS ARE ALL EMPTY AND THAT IS A MEASUREMENT. Every one of the four holds all 58 selectors,
all 10 core ignores and both owned scalars, so there is nothing for a drop to name. A drop here is
the honest declaration for an entry a repo genuinely cannot take; the machinery refuses one that
outlives its subject, which is what keeps this emptiness from being a default nobody checked.

EVERY CEILING IS ITS MEASUREMENT AND NOT A ROUND NUMBER ABOVE IT. `SectionDelta.ceiling` has no
default on purpose, so the next waiver anybody adds raises the number in the same edit and says what
it is for, instead of arriving as headroom somebody left behind.
"""

from __future__ import annotations

from typing import Final

from lab_commons.dev.famconfig import SectionDelta

__all__ = [
    'CONSUMER_IGNORE_TAIL',
    'RUFF_FORMAT',
    'RUFF_LINT',
    'RUFF_ROOT',
    'SECTION_DELTAS',
]

#: The three ruff tables the family base owns, each spelled once.
RUFF_ROOT: Final = '[tool.ruff]'
RUFF_LINT: Final = '[tool.ruff.lint]'
RUFF_FORMAT: Final = '[tool.ruff.format]'

#: The 52 codes ALL THREE CONSUMERS ignore beyond the family's 10, MEASURED as the three-way
#: intersection of their ignore lists minus `RUFF_IGNORE_CORE`. It is named ONCE and each consumer's
#: delta is this tuple plus its own, because restating 52 codes three times is the table forking
#: inside one file: an edit landing in two of the three copies would then read as a real divergence.
#:
#: IT IS NOT PROMOTED INTO THE BASE, and that is a decision rather than a pending chore. The kit
#: ENFORCES all 52 -- it ignores exactly the 10 -- so moving them into `RUFF_IGNORE_CORE` would make
#: the publishing repo adopt three other repos' waivers on the strength of their agreeing with each
#: other, which is the anti-fork arm pointing at the stricter repo. It is the same reasoning
#: `RUFF_QUOTE_STYLE` gives for the six formatter keys it declines.
CONSUMER_IGNORE_TAIL: Final[tuple[str, ...]] = (
    'ANN001',
    'ANN002',
    'ANN003',
    'ANN201',
    'ANN202',
    'ANN206',
    'ARG002',
    'B018',
    'B904',
    'C901',
    'D100',
    'D101',
    'D102',
    'D103',
    'D104',
    'D105',
    'D107',
    'D205',
    'D415',
    'D417',
    'DTZ005',
    'E501',
    'ERA001',
    'EXE',
    'FBT',
    'FIX',
    'INP001',
    'LOG015',
    'N801',
    'N802',
    'N803',
    'N805',
    'N806',
    'N815',
    'N816',
    'NPY002',
    'PLR0912',
    'PLR0915',
    'PLR2004',
    'PLW2901',
    'PT012',
    'PT018',
    'RUF012',
    'RUF043',
    'S101',
    'S311',
    'SIM108',
    'SIM113',
    'SLF001',
    'TD',
    'TRY300',
    'UP017',
)

#: Every repo's delta against every owned table: ``repo -> artefact -> SectionDelta``. The two SCALAR
#: tables carry an empty delta in all four, which is a stated answer rather than an omission -- a
#: repo that widened its own line length would need a drop here, and none does.
#:
#: THE KIT'S THREE ENTRIES ARE ALL ZERO-CEILING, which is the ratchet the publisher owes its
#: consumers: the next waiver added to `lab-commons` raises a number in this file, in public, in the
#: same edit. The census already found this repo linted less strictly than everything it shipped to,
#: and a ceiling of zero is what stops that reopening quietly.
SECTION_DELTAS: Final[dict[str, dict[str, SectionDelta]]] = {
    'lab-commons': {
        RUFF_ROOT: SectionDelta(repo='lab-commons', added={}, dropped={}, ceiling=0),
        RUFF_LINT: SectionDelta(repo='lab-commons', added={}, dropped={}, ceiling=0),
        RUFF_FORMAT: SectionDelta(repo='lab-commons', added={}, dropped={}, ceiling=0),
    },
    'wdg-lab': {
        RUFF_ROOT: SectionDelta(repo='wdg-lab', added={}, dropped={}, ceiling=0),
        RUFF_LINT: SectionDelta(
            repo='wdg-lab',
            #: 53 = the 52 shared with the other two consumers, plus `ANN205`. That single code is
            #: this lab's own and `CONSUMER_IGNORE_DELTA` records it as such.
            added={'ignore': (*CONSUMER_IGNORE_TAIL, 'ANN205')},
            dropped={},
            ceiling=53,
        ),
        RUFF_FORMAT: SectionDelta(repo='wdg-lab', added={}, dropped={}, ceiling=0),
    },
    'optimi-lab': {
        RUFF_ROOT: SectionDelta(repo='optimi-lab', added={}, dropped={}, ceiling=0),
        RUFF_LINT: SectionDelta(
            repo='optimi-lab',
            #: 52 and NOTHING OF ITS OWN -- the only consumer whose waiver list is exactly the shared
            #: tail. Worth recording, because it is the evidence that the tail is a genuine three-way
            #: agreement rather than one repo's list the other two happen to sit near.
            added={'ignore': CONSUMER_IGNORE_TAIL},
            dropped={},
            ceiling=52,
        ),
        RUFF_FORMAT: SectionDelta(repo='optimi-lab', added={}, dropped={}, ceiling=0),
    },
    'motronics-studio': {
        RUFF_ROOT: SectionDelta(repo='motronics-studio', added={}, dropped={}, ceiling=0),
        RUFF_LINT: SectionDelta(
            repo='motronics-studio',
            #: 56 = the shared 52 plus four of its own: `B023` (loop-variable capture in closures),
            #: `PLR0917` (positional-argument count, a physics-signature shape), and
            #: `RUF002`/`RUF003` (ambiguous unicode in docstrings and comments -- that tree writes
            #: CJK reasoning in prose). The largest waiver set in the family, which is exactly why it
            #: is the one whose ceiling is worth stating.
            added={'ignore': (*CONSUMER_IGNORE_TAIL, 'B023', 'PLR0917', 'RUF002', 'RUF003')},
            dropped={},
            ceiling=56,
        ),
        RUFF_FORMAT: SectionDelta(repo='motronics-studio', added={}, dropped={}, ceiling=0),
    },
}
