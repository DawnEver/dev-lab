"""THE KIT'S COLLECTION-REACH ROW, pure DATA -- the selection this repo makes and what it leaves its tests.

The machinery is `lab_commons.dev.collectcensus` and the reader under it is
`lab_commons.dev.collectscope`. Nothing here computes: a table edited through the module that checks
it drifts away from what it describes.

THE KIT'S OWN ROW ONLY. Every consumer declares its selections -- and the residue it cannot settle,
with a reason per name -- in its own tests, and calls `collectcensus.assert_reaches` over its own
checkout. Rows for other repos stored here were facts about them under names that were not theirs,
and they went stale the day a consumer's distribution name was not the neutral spelling.

MEASURED 2026-10-02 against this repo's WORKING TREE: the `dev` selection strands nothing, degrades
nothing and leaves no name unresolved.
"""

from __future__ import annotations

from lab_commons.dev.collectcensus import CollectRow

__all__ = [
    'FILE_FLOORS',
    'REPO_FLOOR',
    'ROWS',
    'ROW_FLOOR',
]

#: One row per (repo, selection). Three sets, each by EQUALITY in both directions.
ROWS: tuple[CollectRow, ...] = (
    CollectRow(
        repo='lab-commons',
        selected=('dev',),
        errors=frozenset(),
        degrades=frozenset(),
        unresolved=frozenset(),
        why=(
            'THE KIT COLLECTS UNDER ITS OWN CI SELECTION, and nothing is guarded to get there. Its test tree '
            'imports lab_commons, pytest, numpy, pint and rtoml and nothing else, every one of them '
            'in the `dev` extra or the base, and it resolves every import name it uses -- an empty '
            'UNRESOLVED set here is what proves the three resolution rules cover an entire real tree '
            'rather than only the names somebody thought to alias.'
        ),
    ),
)

#: The fewest test files the kit's read must hold. MEASURED 2026-09-19 at 108; set below it, because
#: a tree that was not read reports the same empty stranded set as a tree whose every import survives.
FILE_FLOORS: dict[str, int] = {'lab-commons': 90}

#: The census reads one repo -- the one it runs in -- and judges its one selection.
REPO_FLOOR: int = 1
ROW_FLOOR: int = 1
