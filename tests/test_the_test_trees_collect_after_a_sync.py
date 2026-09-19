"""THE LIVE HALF: every recorded selection re-measured against the four test trees beside this one.

`test_dev_collectscope.py` proves the reader can fail, over planted files. THIS file is a
MEASUREMENT of the family -- would the selections it actually makes leave each repo able to COLLECT
its tests -- and on the day it was written three of its five rows were findings, two of them
against selections `_synccensus_rows.py` had already scored COMPLETE at the runner.

Nothing here installs, syncs or prunes, and nothing imports a scanned file. A sibling not on this
box is ABSENT rather than failing; the repo and row floors are what stop that being a free pass.
"""

from __future__ import annotations

import pytest
from _collect_census import (
    BASE,
    HERE,
    PATHS,
    CollectRow,
    CollectRowError,
    assert_reaches,
    measure,
    present,
    readings_of,
)
from _collect_census_rows import FILE_FLOORS, REPO_FLOOR, ROW_FLOOR, ROWS

from lab_commons.dev.collectscope import ALIASES, STDLIB


def test_every_recorded_selection_still_leaves_the_tree_what_the_table_records() -> None:
    """THE CENSUS. Equality on errors, degrades AND unresolved, in both directions, per row."""
    seen = assert_reaches(ROWS, FILE_FLOORS, repo_floor=REPO_FLOOR, row_floor=ROW_FLOOR)
    assert HERE in seen, 'the census did not even read the tree it runs in'


def test_the_family_disagrees_with_itself_about_one_import_name() -> None:
    """THE CONTROL THE FAMILY SUPPLIES: ``OCP`` degrades in wdg-lab and errors in motronics.

    Two repos, one import name, one reader, opposite answers -- and the only difference is the
    GUARD. A reader that convicted every optional integration would strand it twice; one that
    trusted the scope would strand it never. This is the row that makes both impossible.
    """
    by_key = {row.key: row for row in ROWS}
    guarded = by_key['wdg-lab[dev]']
    bare = by_key['motronics-studio[pareto,dev]']
    assert 'cadquery-ocp' in guarded.degrades
    assert 'cadquery-ocp' not in guarded.errors
    assert 'cadquery-ocp-novtk' in bare.errors
    assert 'cadquery-ocp-novtk' not in bare.degrades


def test_the_sanctioned_selection_cannot_collect_the_tree_it_is_sanctioned_for() -> None:
    """THE FINDING, pinned so closing it reds as loudly as opening it did.

    `_synccensus_rows.py` scores `--extra pareto --extra dev` COMPLETE, and is right at its own
    question. The row below is the other half: the runner starts and the tree does not collect. The
    day somebody repairs that manifest this assertion fails, which is the ratchet's second side --
    the repair has to be recorded, not absorbed.
    """
    row = next(row for row in ROWS if row.key == 'motronics-studio[pareto,dev]')
    assert len(row.errors) == 7, sorted(row.errors)
    assert 'pillow' in row.errors


def test_the_recorded_repair_is_still_one_extra_short() -> None:
    """The incantation the sibling table calls the one that restored the box still strands `pillow`."""
    row = next(row for row in ROWS if row.key == 'motronics-studio[all,dev,img-to-cad]')
    assert row.errors == frozenset({'pillow'}), sorted(row.errors)


def test_every_alias_row_is_needed_by_a_real_tree_and_no_needed_one_is_missing() -> None:
    """BOTH SIDES OF THE ALIAS TABLE, DERIVED: an unused row is a waiver nothing uses.

    Reached means the import name appears at module scope in some repo the box has. The set is
    computed from the live readings rather than listed, so an alias that stops being imported
    anywhere reds exactly as loudly as an import nothing can resolve.
    """
    reached: set[str] = set()
    seen_names: set[str] = set()
    for repo in sorted(PATHS):
        if not present(repo):
            continue
        readings, _, _, _ = readings_of(repo)
        for reading in readings.values():
            names = {use.name for use in reading.uses if use.name not in STDLIB}
            reached |= names & set(ALIASES)
            seen_names |= names
    assert len(seen_names) > 30, f'the alias scan read {len(seen_names)} import names, which is no corpus'
    assert reached >= {'OCP', 'cv2'}, sorted(reached)
    assert set(ALIASES) - reached == set(), sorted(set(ALIASES) - reached)


def test_a_row_refuses_a_caption_and_an_empty_selection() -> None:
    """THE PLANTED CONTROL on the row shape, through the REAL constructor."""
    good = {
        'repo': 'planted',
        'selected': ('dev',),
        'errors': frozenset(),
        'degrades': frozenset(),
        'unresolved': frozenset(),
        'why': 'x' * 200,
    }
    assert CollectRow(**good).key == 'planted[dev]'
    with pytest.raises(CollectRowError, match='below the floor'):
        CollectRow(**{**good, 'why': 'too short'})
    with pytest.raises(CollectRowError, match='names no extra'):
        CollectRow(**{**good, 'selected': ()})


def test_the_measurement_is_the_real_join_and_not_a_recorded_number() -> None:
    """`measure` is what the census calls; asserting it here stops the table being self-referential."""
    found = measure(HERE, BASE / PATHS[HERE], ('dev',))
    assert found.files >= FILE_FLOORS['lab-commons'], found.files
    assert (found.errors, found.degrades, found.unresolved) == (frozenset(), frozenset(), frozenset())
