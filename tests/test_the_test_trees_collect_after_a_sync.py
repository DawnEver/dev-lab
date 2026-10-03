"""THE LIVE HALF: the kit's recorded selection re-measured against its own test tree, plus the kit's controls.

`test_dev_collectscope.py` proves the reader can fail, over planted files. THIS file proves the CENSUS
can -- every refusal of `lab_commons.dev.collectcensus` driven through the real function -- and
measures the one selection this repo makes. Each consumer declares its own selections and residue in
its own tests and calls the same `assert_reaches` over its own checkout.

ONE ARM STILL READS THE FAMILY, AND IT HOLDS NO CONSUMER FACT: the alias table is the KIT's, and
whether each of its rows is needed by SOME real tree is a question only the union of the trees can
answer. It reads whatever siblings the box has and names no row of theirs.

Nothing here installs, syncs or prunes, and nothing imports a scanned file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest
from _collect_census_rows import FILE_FLOORS, REPO_FLOOR, ROW_FLOOR, ROWS

from lab_commons.dev.collectcensus import (
    CollectRow,
    CollectRowError,
    ReachDriftError,
    UnresolvedSupplierError,
    VacuousTreeScanError,
    assert_no_unresolved_has_a_declared_supplier,
    assert_reaches,
    derivable_suppliers,
    measure,
)

#: The repo under verification, read from its WORKING TREE.
HERE: Final = 'lab-commons'
ROOT: Final = Path(__file__).resolve().parents[1]
ROOTS: Final = {HERE: ROOT}


def test_every_recorded_selection_still_leaves_the_tree_what_the_table_records() -> None:
    """THE CENSUS. Equality on errors, degrades AND unresolved, in both directions, per row."""
    seen = assert_reaches(ROWS, ROOTS, FILE_FLOORS, here=HERE, repo_floor=REPO_FLOOR, row_floor=ROW_FLOOR)
    assert seen == {HERE}


def test_the_measurement_is_the_real_join_and_not_a_recorded_number() -> None:
    """`measure` is what the census calls; asserting it here stops the table being self-referential."""
    found = measure(ROOT, ('dev',), at_head=False)
    assert found.files >= FILE_FLOORS[HERE], found.files
    assert (found.errors, found.degrades, found.unresolved) == (frozenset(), frozenset(), frozenset())


def test_the_census_refuses_a_drift_planted_into_the_real_row() -> None:
    """THE PLANTED CONTROL ON THE LIVE HALF: the real row, one name wrong, through the real guard."""
    row = ROWS[0]
    broken = CollectRow(row.repo, row.selected, frozenset({'planted'}), row.degrades, row.unresolved, row.why)
    with pytest.raises(ReachDriftError, match='now measures'):
        assert_reaches((broken,), ROOTS, FILE_FLOORS, here=HERE, repo_floor=1, row_floor=1)


def test_a_census_that_read_too_little_is_refused() -> None:
    """THE FLOORS' OWN CONTROLS: a file floor above the tree, and a repo floor above what was read."""
    with pytest.raises(VacuousTreeScanError, match='test files'):
        assert_reaches(ROWS, ROOTS, {HERE: 10**6}, here=HERE, repo_floor=1, row_floor=1)
    with pytest.raises(VacuousTreeScanError, match='below the floors'):
        assert_reaches(ROWS, ROOTS, FILE_FLOORS, here=HERE, repo_floor=2, row_floor=1)


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


def _planted(unresolved: frozenset[str]) -> CollectRow:
    """One row over the repo this file runs in, so a planted control drives the REAL declared set."""
    return CollectRow(
        repo=HERE,
        selected=('dev',),
        errors=frozenset(),
        degrades=frozenset(),
        unresolved=unresolved,
        why='planted. ' * 40,
    )


def test_a_residue_name_its_own_manifest_declares_is_convicted() -> None:
    """THE PLANTED CONTROL, through the real guard and over lab-commons' REAL declared set.

    `pytest` is planted as residue; the manifest declares `pytest-cov` and `pytest-mock`, so the
    derivation fires. Revert the guard and this row passes silently.
    """
    with pytest.raises(UnresolvedSupplierError, match='not a transitive dependency'):
        assert_no_unresolved_has_a_declared_supplier((_planted(frozenset({'pytest'})),), ROOTS, here=HERE, pair_floor=1)


def test_a_derivation_scan_that_read_nothing_is_refused() -> None:
    """THE FLOOR'S OWN CONTROL: a clean answer over zero pairs is vacuous, not green."""
    with pytest.raises(VacuousTreeScanError, match='below the floor'):
        assert_no_unresolved_has_a_declared_supplier((), ROOTS, here=HERE, pair_floor=1)


@pytest.mark.parametrize(
    ('name', 'declared', 'expected'),
    [
        ('pdfminer', frozenset({'pdfminer-six'}), frozenset({'pdfminer-six'})),
        ('OCP', frozenset({'cadquery-ocp'}), frozenset({'cadquery-ocp'})),
        ('yaml', frozenset({'pyyaml'}), frozenset({'pyyaml'})),
        ('win32com', frozenset({'pywin32'}), frozenset()),
        ('pywintypes', frozenset({'pywin32'}), frozenset()),
        ('pydantic_core', frozenset({'pydantic'}), frozenset()),
    ],
)
def test_the_derivation_reaches_what_a_spelling_settles_and_refuses_the_rest(
    name: str, declared: frozenset[str], expected: frozenset[str]
) -> None:
    """BOTH FAILURE DIRECTIONS OF THE DERIVATION, over planted declared sets.

    Nothing in `pywin32`'s spelling reaches `win32com` or `pywintypes`, and `pydantic-core` is a
    distribution distinct from `pydantic`. A rule loose enough to catch those would read every
    `foo-bar` as supplying `foo`.
    """
    assert derivable_suppliers(name, declared) == expected
