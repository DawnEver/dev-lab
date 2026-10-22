"""THE KIT'S COLLECTION-REACH ROW, pure DATA -- the selection this repo makes and what it leaves its tests.

The machinery is `dev_lab.dev.collectcensus` and the reader under it is
`dev_lab.dev.collectscope`. Nothing here computes: a table edited through the module that checks
it drifts away from what it describes.

THE KIT'S OWN ROW ONLY. Every consumer declares its selections -- and the residue it cannot settle,
with a reason per name -- in its own tests, and calls `collectcensus.assert_reaches` over its own
checkout. Rows for other repos stored here were facts about them under names that were not theirs,
and they went stale the day a consumer's distribution name was not the neutral spelling.

MEASURED 2026-10-02 against this repo's WORKING TREE: the then-`dev` selection strands nothing,
degrades nothing and leaves no name unresolved. RE-MEASURED 2026-10-06 over the selection CI now
makes -- `dev` plus the two plotting extras -- with the same three empty sets.
"""

from __future__ import annotations

from dev_lab.dev.collectcensus import CollectRow

__all__ = [
    'FILE_FLOORS',
    'REPO_FLOOR',
    'ROWS',
    'ROW_FLOOR',
]

#: One row per (repo, selection). Three sets, each by EQUALITY in both directions.
ROWS: tuple[CollectRow, ...] = (
    CollectRow(
        repo='dev-lab',
        selected=(),
        errors=frozenset(),
        degrades=frozenset(),
        unresolved=frozenset(),
        why=(
            'THE KIT COLLECTS UNDER ITS OWN CI SELECTION, and nothing is guarded to get there. Since the '
            '2026-10-22 split the selection is EMPTY: dev-lab IS the development system, so pytest, ruff and '
            'the lab-commons runtime (with its units, paths, io and structured extras) are its BASE install, '
            'and the plotting adapters whose extras once degraded this tree stayed in lab-commons with their '
            'tests. An empty UNRESOLVED set here proves the resolution rules cover an entire real tree.'
        ),
    ),
)

#: The fewest test files the kit's read must hold. MEASURED 2026-09-19 at 108; set below it, because
#: a tree that was not read reports the same empty stranded set as a tree whose every import survives.
FILE_FLOORS: dict[str, int] = {'dev-lab': 90}

#: The census reads one repo -- the one it runs in -- and judges its one selection.
REPO_FLOOR: int = 1
ROW_FLOOR: int = 1
