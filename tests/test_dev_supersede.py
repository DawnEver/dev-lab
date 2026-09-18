"""`lab_commons.dev.supersede`: every plant, both floors, and the fifteen rows it has to reproduce.

THE TEST THAT DECIDES WHETHER THIS MODULE WAS WORTH WRITING is `test_the_hand_measurement_is_
reproduced`. Three tranches read a placement roster by hand on 2026-09-17 and corrected 17 declared
MOVES to 7; the instrument is only interesting if it reaches the same answer from the kit's source
without being handed it. The rows live in `_supersede_rows.py` as DATA, the kit side is read LIVE,
and the expected grades are asserted one by one rather than in aggregate -- an aggregate count can
be satisfied by two compensating mistakes.

THE FOUR HOLES A REAL CONSUMER FOUND each get a plant that FIRES and a plant that proves the old
correct answer did not move: provenance-as-data against a kit module that names nobody, an
unreadable row against a shell script, a wrong `package` that must refuse rather than report a
clean zero, and -- found 2026-09-18 by RE-MEASURING a row rather than re-labelling it -- a kit
module no import form could NAME, which made the IMPORT detector blind to a whole sub-package.
The third is this family's dominant defect inside the instrument built to find it; the fourth is
the same defect one level down, and it is the one that cost six true positives their corroboration.

BOTH DIRECTIONS ARE PLANTED, because only the second one makes this a census rather than a name
matcher: a file whose subject IS upstream must be flagged, and a file that merely SHARES NAMES with
an upstream module must NOT be. The second plant is the load-bearing one -- this family has already
measured 89% DIFFERENT content under a shared filename -- and it is planted in a real tree and run
through the REAL `take_census`, never through a re-implementation that would agree with itself.
"""

from __future__ import annotations

import ast
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
    UNREADABLE,
    UNTOUCHED,
    KitModule,
    PackageMismatch,
    Row,
    VacuousCensus,
    grade_row,
    imported_kit_modules,
    kit_modules,
    provenance_rows,
    take_census,
    undeclared_modules,
)

#: The shipped kit, read as source. This is the half of the fixture that can rot, so it is not pinned.
DEV_DIR = Path(dev_pkg.__file__).resolve().parent

#: The kit publishes far more than this; the floor refuses a directory the scan failed to reach.
#: It counts the sub-packages too, since `kit_modules` recurses: 46 modules MEASURED 2026-09-17.
KIT_FLOOR = 15

#: Both halves of the validation need a population or the separation is vacuous. MEASURED over the
#: fixture: 7 rows hand-read as already in the kit, 8 as still local.
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

_ADOPTER = '''"""A consumer that delegates."""

from lab_commons.dev.bounded import run_bounded

def worker_count(): ...
'''

_ROWS = "PROVENANCE = {{'checkout': ({kind!r}, 'scripts/repo/debris.py')}}\n"


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


# -- HOLE 1: the kit module that names nobody, and the registry that makes forgetting a red. --------


def test_a_kit_module_that_names_no_consumer_is_still_caught_by_its_row(tmp_path: Path) -> None:
    """THE PLANT FOR THE MISS. Silent docstring, no import, and the census convicts on the DATA.

    This is `famtests.rulespages` reduced: a kit module that published a consumer's whole subject,
    named no path and was imported by nobody, so both detectors were silent and the row read
    UNTOUCHED. The registry is what fires here, and nothing else in the plant changed.
    """
    kit = {'checkout.py': _SILENT_KIT, '_provenance_rows.py': _ROWS.format(kind='supersedes')}
    kit_dir, root = _plant(tmp_path, kit, {'scripts/repo/debris.py': _FORK})
    (claim,) = take_census(
        {'scripts/repo/debris.py': 'moves'},
        kit_modules(kit_dir),
        root=root,
        package=PACKAGE,
        row_floor=1,
        module_floor=1,
    ).claims
    assert claim.grade == SUPERSEDED
    assert claim.detectors == (PROVENANCE,)
    assert claim.kit_module == 'checkout'


def test_an_adopted_by_row_is_not_a_provenance_claim(tmp_path: Path) -> None:
    """THE CONTROL THAT KEEPS THE OLD ANSWER. Delegation is not supersession, so the row stays put.

    Without this the registry would re-admit exactly the false positive `named_only` was measured
    into existence for: `verify` names `scripts/gate/runner.py` as the tree it was carved FROM.
    """
    kit = {'checkout.py': _SILENT_KIT, '_provenance_rows.py': _ROWS.format(kind='adopted_by')}
    kit_dir, root = _plant(tmp_path, kit, {'scripts/repo/debris.py': _FORK})
    (claim,) = take_census(
        {'scripts/repo/debris.py': 'moves'},
        kit_modules(kit_dir),
        root=root,
        package=PACKAGE,
        row_floor=1,
        module_floor=1,
    ).claims
    assert claim.grade == UNTOUCHED, 'a consumer that delegates has not been replaced'
    assert claim.detectors == ()


def test_the_registry_is_two_sided_over_planted_modules() -> None:
    """A module with no row, a row with no module, and a kind that is not a kind. Over the REAL audit."""
    modules = [KitModule(name='checkout', claims=frozenset(), universe=frozenset())]
    assert undeclared_modules(modules, {'checkout': ('original',)}) == ()
    assert 'no provenance row' in undeclared_modules(modules, {})[0]
    assert (
        'naming no published module'
        in undeclared_modules(modules, {'checkout': ('original',), 'gone': ('original',)})[0]
    )
    assert 'not one of' in undeclared_modules(modules, {'checkout': ('moved',)})[0]


def test_every_published_kit_module_declares_its_provenance() -> None:
    """THE RATCHET, live. A module that forgets to say what it replaced is itself the red now.

    The convention it replaces cost the census its worst miss: `rulespages` landed hours before the
    census ran, said nothing, and its consumer graded UNTOUCHED against the module that supersedes it.
    """
    modules = kit_modules(DEV_DIR)
    assert len(modules) >= KIT_FLOOR
    problems = undeclared_modules(modules, provenance_rows(DEV_DIR))
    assert problems == (), 'the kit provenance registry disagrees with what is published:\n  ' + '\n  '.join(problems)


def test_the_row_that_found_the_miss_is_flagged() -> None:
    """optimi-lab's rules-page ratchet, against the LIVE kit -- the fifteenth row, named not aggregated.

    RE-MEASURED 2026-09-18 after optimi-lab `aab4074c` EXECUTED the move this row predicted. The
    grade is unchanged and everything under it moved: both detectors fire now instead of one, and
    the remainder is the repo's own four declarations instead of a local mechanism that had not
    left. It also still measures why OVERLAP was not promoted to a third detector, more sharply
    than before -- `covered` is now EMPTY, so an overlap detector scores this row at zero.
    """
    row = next(r for r in MEASURED_ROWS if r.path.endswith('test_the_rules_pages_are_a_ratchet.py'))
    claim = grade_row(Row(row.path, row.side, row.public, row.imports), kit_modules(DEV_DIR))
    assert claim.kit_module == 'rulespages'
    assert claim.detectors == (PROVENANCE, IMPORT)
    assert claim.flagged
    assert claim.covered == (), 'zero shared names: overlap could not have found this'
    assert claim.remainder == (
        'CEILING',
        'PAGE_FLOOR',
        'PINNED',
        'test_the_rule_pages_hold_their_measured_budget_per_page_and_in_total',
    ), 'the remainder IS the answer here, so it is pinned by name rather than counted'


# -- HOLE 2: a row that is not Python is a row, and it refuses a grade. ----------------------------


def test_a_shell_row_grades_unreadable_instead_of_crashing(tmp_path: Path) -> None:
    """THE PLANT. `ast.parse` on a shell script raised and the caller had to filter by hand."""
    kit_dir, root = _plant(tmp_path, {'checkout.py': _CLAIMING_KIT}, {'scripts/repo/debris.py': _FORK})
    (root / 'scripts' / 'hooks').mkdir(parents=True)
    (root / 'scripts' / 'hooks' / 'with-retry.sh').write_text(
        '#!/usr/bin/env bash\nset -euo pipefail\n', encoding='utf-8'
    )
    census = take_census(
        {'scripts/hooks/with-retry.sh': 'moves', 'scripts/repo/debris.py': 'moves'},
        kit_modules(kit_dir),
        root=root,
        package=PACKAGE,
        row_floor=2,
        module_floor=1,
    )
    graded = {claim.path: claim.grade for claim in census.claims}
    assert graded['scripts/hooks/with-retry.sh'] == UNREADABLE
    assert census.rows_read == 2, 'an unreadable row is still a row -- dropping it is how a MOVES row goes missing'
    assert graded['scripts/repo/debris.py'] == SUPERSEDED, 'the readable row beside it is graded as before'


def test_a_python_row_that_will_not_parse_still_raises(tmp_path: Path) -> None:
    """THE OTHER SIDE. A broken `.py` is a broken file in the tree, not a file of another kind."""
    kit_dir, root = _plant(tmp_path, {'checkout.py': _CLAIMING_KIT}, {'scripts/repo/debris.py': 'def (\n'})
    with pytest.raises(SyntaxError):
        take_census(
            {'scripts/repo/debris.py': 'moves'},
            kit_modules(kit_dir),
            root=root,
            package=PACKAGE,
            row_floor=1,
            module_floor=1,
        )


# -- HOLE 3: a wrong `package` must refuse, because its answer looks like a clean one. -------------


def test_a_package_that_resolves_onto_nothing_is_refused(tmp_path: Path) -> None:
    """THE PLANT. `package='lab_commons'` resolves every kit import to `'dev'` and reports 0 CONSULTS."""
    kit_dir, root = _plant(tmp_path, {'bounded.py': _SILENT_KIT}, {'scripts/gate/runner.py': _ADOPTER})
    with pytest.raises(PackageMismatch, match='wrong depth'):
        take_census(
            {'scripts/gate/runner.py': 'stays'},
            kit_modules(kit_dir),
            root=root,
            package='lab_commons',
            row_floor=1,
            module_floor=1,
        )


def test_the_right_package_still_reports_the_adoption(tmp_path: Path) -> None:
    """THE CONTROL. Same tree, correct depth: the IMPORT detector fires and the row reads CONSULTS."""
    kit_dir, root = _plant(tmp_path, {'bounded.py': _SILENT_KIT}, {'scripts/gate/runner.py': _ADOPTER})
    (claim,) = take_census(
        {'scripts/gate/runner.py': 'stays'},
        kit_modules(kit_dir),
        root=root,
        package=PACKAGE,
        row_floor=1,
        module_floor=1,
    ).claims
    assert claim.grade == CONSULTS
    assert claim.detectors == (IMPORT,)


def test_a_roster_that_imports_no_kit_module_is_not_a_mismatch(tmp_path: Path) -> None:
    """THE FALSE-POSITIVE GUARD. A roster of live forks imports nothing, and that is an ANSWER."""
    kit_dir, root = _plant(tmp_path, {'checkout.py': _SILENT_KIT}, {'scripts/repo/debris.py': _FORK})
    census = take_census(
        {'scripts/repo/debris.py': 'moves'},
        kit_modules(kit_dir),
        root=root,
        package=PACKAGE,
        row_floor=1,
        module_floor=1,
    )
    assert census.claims[0].grade == UNTOUCHED


# -- HOLE 4: a kit module the IMPORT detector cannot be reached by. --------------------------------


#: Below the kit's published module count, and separately below the count of modules living one
#: level down. A round-trip over ZERO modules passes, and a round-trip over only top-level ones
#: passes today while the sub-package half is exactly what was broken.
NESTED_FLOOR = 3


def _import_forms(module_path: Path) -> tuple[str, ...]:
    """The two ways a consumer spells an import of one published kit module, as SOURCE."""
    dotted = '.'.join((PACKAGE, *module_path.relative_to(DEV_DIR).with_suffix('').parts))
    parent, stem = dotted.rsplit('.', 1)
    return (f'from {parent} import {stem}\n', f'import {dotted}\n')


def test_every_published_kit_module_is_reachable_by_the_import_detector() -> None:
    """THE ARM THAT WOULD HAVE CAUGHT IT: what `kit_modules` PUBLISHES, `imported_kit_modules` must NAME.

    The two halves are one agreement and nothing held them to it. `kit_modules` recurses and
    publishes `famtests.rulespages` under the stem `rulespages`; `imported_kit_modules` took only
    the first segment below the package and answered `famtests`. A token no module answers to is a
    detector that never fires, and a detector that never fires costs no red -- all SIX `famtests`
    consumers graded NAMED_ONLY, the grade that means nothing corroborates the claim, while each of
    them imported the very module superseding it.

    It is a ROUND TRIP rather than a scan of consumer trees, which is the only form available here:
    this repo's suite cannot read the four consumer repos. It is also the stronger form, because it
    holds for every module published TODAY rather than for whichever ones somebody wrote a row for.
    """
    modules = sorted(
        path
        for path in DEV_DIR.rglob('*.py')
        if not any(part.startswith('_') for part in path.relative_to(DEV_DIR).parts)
    )
    assert len(modules) >= KIT_FLOOR, 'a round trip over a directory the walk did not reach proves nothing'
    nested = [path for path in modules if len(path.relative_to(DEV_DIR).parts) > 1]
    assert len(nested) >= NESTED_FLOOR, (
        f'{len(nested)} kit modules live below the top level, under a floor of {NESTED_FLOOR}. The '
        f'defect this arm exists for is reachable ONLY through a sub-package, so a corpus of '
        f'top-level modules would pass it while blind.'
    )
    unreachable = {
        path.stem: form
        for path in modules
        for form in _import_forms(path)
        if path.stem not in imported_kit_modules(ast.parse(form), package=PACKAGE)
    }
    assert not unreachable, (
        f'these published kit modules cannot be NAMED by the import form a consumer writes, so the '
        f'IMPORT detector is blind to every file that adopted them: {unreachable}. Widen '
        f'`imported_kit_modules`; do not narrow what `kit_modules` publishes.'
    )


def test_the_round_trip_refuses_a_resolver_that_stops_one_level_short() -> None:
    """THE PLANT, and it is the real bug rather than an imitation of it.

    `package='lab_commons'` is one level short of the kit, which is the same mistake one level up:
    every sub-package module resolves to a token it is not named by. If this passed, the arm above
    would be asserting a property of the strings rather than of the resolver.
    """
    form = 'from lab_commons.dev.famtests import rulespages\n'
    assert 'rulespages' not in imported_kit_modules(ast.parse(form), package='lab_commons')
    assert 'rulespages' in imported_kit_modules(ast.parse(form), package=PACKAGE)


def test_a_name_no_kit_module_answers_to_is_not_manufactured() -> None:
    """THE CONTROL IN THE OTHER DIRECTION. Widening the resolver must not make every import a hit.

    The candidate set may over-emit -- it yields sub-package tokens and imported function names --
    and that is only safe because it is intersected with what `kit_modules` published. An import of
    another library must contribute NOTHING, or the IMPORT detector would corroborate every claim
    and the census would flag the whole roster.
    """
    form = 'import pathlib\nfrom collections.abc import Mapping\nfrom lab_commons import paths\n'
    assert imported_kit_modules(ast.parse(form), package=PACKAGE) == frozenset()
