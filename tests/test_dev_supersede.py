"""`lab_commons.dev.supersede`: both plants, both floors, and the fourteen rows it has to reproduce.

THE TEST THAT DECIDES WHETHER THIS MODULE WAS WORTH WRITING is `test_the_hand_measurement_is_
reproduced`. Three tranches read a placement roster by hand on 2026-09-17 and corrected 17 declared
MOVES to 7; the instrument is only interesting if it reaches the same answer from the kit's source
without being handed it. The rows live in `_supersede_rows.py` as DATA, the kit side is read LIVE,
and the expected grades are asserted one by one rather than in aggregate -- an aggregate count can
be satisfied by two compensating mistakes.

BOTH DIRECTIONS ARE PLANTED, because only the second one makes this a census rather than a name
matcher: a file whose subject IS upstream must be flagged, and a file that merely SHARES NAMES with
an upstream module must NOT be. The second plant is the load-bearing one -- this family has already
measured 89% DIFFERENT content under a shared filename -- and it is planted in a real tree and run
through the REAL `take_census`, never through a re-implementation that would agree with itself.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _supersede_rows import ALREADY_IN_THE_KIT, DISAGREEMENTS, MEASURED_ROWS, ROW_FLOOR, STILL_LOCAL

import lab_commons.dev as dev_pkg
from lab_commons.dev.supersede import (
    CONSULTS,
    IMPORT,
    NAMED_ONLY,
    PARTIAL,
    PROVENANCE,
    SUPERSEDED,
    UNMEASURABLE,
    UNTOUCHED,
    KitModule,
    Row,
    VacuousCensus,
    grade_row,
    kit_modules,
    take_census,
)

#: The shipped kit, read as source. This is the half of the fixture that can rot, so it is not pinned.
DEV_DIR = Path(dev_pkg.__file__).resolve().parent

#: The kit publishes far more than this; the floor refuses a directory the scan failed to reach.
KIT_FLOOR = 15

#: Both halves of the validation need a population or the separation is vacuous. MEASURED over the
#: fixture: 6 rows hand-read as already in the kit, 8 as still local.
FLAGGED_FLOOR = 4
LOCAL_FLOOR = 6

PACKAGE = 'lab_commons.dev'


def _plant(tmp_path: Path, kit: dict[str, str], consumers: dict[str, str]) -> tuple[Path, Path]:
    """A throwaway kit directory and consumer tree, written to disk so the REAL readers run."""
    kit_dir = tmp_path / 'kit'
    kit_dir.mkdir()
    for name, body in kit.items():
        (kit_dir / name).write_text(body, encoding='utf-8')
    root = tmp_path / 'repo'
    for name, body in consumers.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding='utf-8')
    return kit_dir, root


_CLAIMING_KIT = '''"""Does the thing. Provenance: ``scripts/repo/debris.py``, migrated today."""

def orphan_directories(): ...
def stale_branches(): ...
def report(): ...
'''

_SILENT_KIT = '''"""Does a different thing entirely, and names no file at all."""

def orphan_directories(): ...
def stale_branches(): ...
def report(): ...
'''

_FORK = '''"""A live fork that imports nothing."""

def orphan_directories(): ...
def stale_branches(): ...
def report(): ...
def main(): ...
'''


def test_a_row_whose_subject_is_upstream_is_flagged(tmp_path: Path) -> None:
    """THE FIRST PLANT. The kit names the file and covers its whole surface, and nothing imports it."""
    kit_dir, root = _plant(tmp_path, {'checkout.py': _CLAIMING_KIT}, {'scripts/repo/debris.py': _FORK})
    census = take_census(
        {'scripts/repo/debris.py': 'moves'},
        kit_modules(kit_dir),
        root=root,
        package=PACKAGE,
        row_floor=1,
        module_floor=1,
    )
    (claim,) = census.claims
    assert claim.grade == SUPERSEDED
    assert claim.detectors == (PROVENANCE,)
    assert claim.kit_module == 'checkout'
    assert claim.remainder == ()
    assert census.flagged == (claim,)


def test_a_row_that_merely_shares_a_name_is_not_flagged(tmp_path: Path) -> None:
    """THE SECOND PLANT, and the one that makes this a census. IDENTICAL surface, no claim, no import."""
    kit_dir, root = _plant(tmp_path, {'checkout.py': _SILENT_KIT}, {'scripts/repo/debris.py': _FORK})
    census = take_census(
        {'scripts/repo/debris.py': 'moves'},
        kit_modules(kit_dir),
        root=root,
        package=PACKAGE,
        row_floor=1,
        module_floor=1,
    )
    (claim,) = census.claims
    assert claim.grade == UNTOUCHED
    assert claim.detectors == ()
    assert claim.kit_module is None
    assert census.flagged == ()


def test_the_remainder_is_the_local_half_of_a_split() -> None:
    """PARTLY superseded is the common case, so the answer names WHICH names are still local."""
    kit = KitModule(name='checkout', claims=frozenset({'prune.py'}), universe=frozenset({'survey', 'debris'}))
    surface = frozenset({'survey', 'PROTECTED'})
    row = Row(path='scripts/lanes/prune.py', side='moves', public=surface, imports=frozenset())
    claim = grade_row(row, [kit])
    assert claim.grade == PARTIAL
    assert claim.covered == ('survey',)
    assert claim.remainder == ('PROTECTED',)


def test_a_claim_nothing_corroborates_is_named_only() -> None:
    """The kit's prose names the file, the surfaces share NOTHING and it imports nothing: prose alone."""
    kit = KitModule(name='verify', claims=frozenset({'runner.py'}), universe=frozenset({'lint', 'report'}))
    row = Row(path='scripts/gate/runner.py', side='stays', public=frozenset({'promote'}), imports=frozenset())
    assert grade_row(row, [kit]).grade == NAMED_ONLY


def test_an_import_with_no_claim_is_consults_never_superseded() -> None:
    """Adoption is not supersession: importing the kit says the file DELEGATES, not that it is gone."""
    kit = KitModule(name='docsite', claims=frozenset(), universe=frozenset({'build_all'}))
    surface = frozenset({'build_all'})
    row = Row(path='scripts/repo/docs.py', side='splits', public=surface, imports=frozenset({'docsite'}))
    claim = grade_row(row, [kit])
    assert claim.grade == CONSULTS
    assert claim.detectors == (IMPORT,)
    assert not claim.flagged


def test_a_file_with_no_public_surface_refuses_a_grade() -> None:
    """Nothing to rule. Saying so beats scoring it zero, which would read as a finished migration."""
    kit = KitModule(name='bounded', claims=frozenset({'wall_reason.py'}), universe=frozenset({'wall_reason'}))
    row = Row(path='scripts/gate/wall_reason.py', side='stays', public=frozenset(), imports=frozenset())
    claim = grade_row(row, [kit])
    assert claim.grade == UNMEASURABLE
    assert not claim.flagged


def test_an_entry_point_is_not_remainder() -> None:
    """Every runnable script has a ``main``; counting it would floor every file's remainder at one."""
    kit = KitModule(name='checkout', claims=frozenset({'debris.py'}), universe=frozenset({'report'}))
    row = Row(path='scripts/repo/debris.py', side='moves', public=frozenset({'report'}), imports=frozenset())
    assert grade_row(row, [kit]).grade == SUPERSEDED


def test_an_underscore_does_not_manufacture_a_remainder() -> None:
    """MEASURED on ``_box.py`` -> ``bounded._available_gb``: one character, a whole false remainder."""
    kit = KitModule(name='bounded', claims=frozenset({'_box.py'}), universe=frozenset({'available_gb'}))
    row = Row(path='scripts/gate/_box.py', side='moves', public=frozenset({'available_gb'}), imports=frozenset())
    assert grade_row(row, [kit]).grade == SUPERSEDED


@pytest.mark.parametrize('row_floor', [0, -1])
def test_a_floor_of_zero_is_refused(tmp_path: Path, row_floor: int) -> None:
    """A floor of zero is the vacuity written down, not a decision to permit it."""
    kit_dir, root = _plant(tmp_path, {'checkout.py': _SILENT_KIT}, {'scripts/repo/debris.py': _FORK})
    with pytest.raises(VacuousCensus, match='refuses nothing'):
        take_census(
            {'scripts/repo/debris.py': 'moves'},
            kit_modules(kit_dir),
            root=root,
            package=PACKAGE,
            row_floor=row_floor,
            module_floor=1,
        )


def test_an_unread_kit_and_an_unread_roster_are_both_refused(tmp_path: Path) -> None:
    """Both sides can go empty, and each reports exactly what a finished migration reports."""
    kit_dir, root = _plant(tmp_path, {'checkout.py': _CLAIMING_KIT}, {'scripts/repo/debris.py': _FORK})
    rows = {'scripts/repo/debris.py': 'moves'}
    with pytest.raises(VacuousCensus, match='kit modules, below'):
        take_census(rows, kit_modules(kit_dir), root=root, package=PACKAGE, row_floor=1, module_floor=9)
    with pytest.raises(VacuousCensus, match='rows, below'):
        take_census(rows, kit_modules(kit_dir), root=root, package=PACKAGE, row_floor=9, module_floor=1)


def test_the_fixture_holds_both_directions() -> None:
    """A validation set with no negatives cannot fail the way this instrument fails."""
    assert len(MEASURED_ROWS) >= ROW_FLOOR
    upstream = [r for r in MEASURED_ROWS if r.hand == ALREADY_IN_THE_KIT]
    local = [r for r in MEASURED_ROWS if r.hand == STILL_LOCAL]
    assert len(upstream) >= FLAGGED_FLOOR
    assert len(local) >= LOCAL_FLOOR


def test_the_hand_measurement_is_reproduced() -> None:
    """THE DELIVERABLE: today's fourteen hand-read rows, graded against the LIVE kit source."""
    modules = kit_modules(DEV_DIR)
    assert len(modules) >= KIT_FLOOR
    graded = {row.path: grade_row(Row(row.path, row.side, row.public, row.imports), modules) for row in MEASURED_ROWS}
    wrong = {path: claim.grade for row in MEASURED_ROWS if (claim := graded[(path := row.path)]).grade != row.expected}
    assert not wrong, f'the instrument moved away from the hand measurement: {wrong}'

    flagged = {path for path, claim in graded.items() if claim.flagged}
    hand_upstream = {row.path for row in MEASURED_ROWS if row.hand == ALREADY_IN_THE_KIT}
    assert hand_upstream <= flagged, f'missed, and a miss here is the blind spot itself: {hand_upstream - flagged}'
    assert flagged - hand_upstream == set(DISAGREEMENTS), 'an undeclared disagreement is a tuned threshold'


def test_the_live_fork_is_the_row_this_was_built_for() -> None:
    """``worktree_debris.py`` imports NOTHING, so only provenance can reach it. Named, not aggregated."""
    row = next(r for r in MEASURED_ROWS if r.path.endswith('worktree_debris.py'))
    claim = grade_row(Row(row.path, row.side, row.public, row.imports), kit_modules(DEV_DIR))
    assert claim.kit_module == 'checkout'
    assert claim.detectors == (PROVENANCE,)
    assert claim.flagged
    assert 'orphan_directories' in claim.covered
