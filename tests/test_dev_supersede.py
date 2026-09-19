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

THE FOURTH WAS CLOSED TWICE, and the second closing is why this file's round trip is a CROSS PRODUCT.
`1aa2738` fixed `from lab_commons.dev.famtests import allowguard` and shipped an arm holding
`kit_modules` and `imported_kit_modules` to one agreement -- driven with the two spellings that fix
had just taught the reader. `from lab_commons.dev.famtests.citedtests import take_scan` was a third
spelling nobody had written down, it stayed unresolved, and the arm stayed green: a module can be
imported in more than one way, so parametrising over MODULES alone measures the resolver against
itself. The spellings are now DATA in the kit (`IMPORT_SPELLINGS`) and the corpus is modules x
spellings, floored on both sides through `lab_commons.dev.floors` because an empty parametrisation
collects nothing and reports what a full green reports.

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
from lab_commons.dev import supersede
from lab_commons.dev.floors import assert_floor, assert_floor_still_binds
from lab_commons.dev.supersede import (
    CONSULTS,
    IMPORT,
    IMPORT_SPELLINGS,
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
    kit_subpackages,
    provenance_rows,
    public_names,
    take_census,
    undeclared_modules,
)

#: The shipped kit, read as source. This is the half of the fixture that can rot, so it is not pinned.
DEV_DIR = Path(dev_pkg.__file__).resolve().parent

#: The published kit, MEASURED 2026-09-18 at 54 modules (`kit_modules` recurses, so the sub-packages
#: are in it). RE-MEASURED from 15, which had been left behind by a tree that grew past it: a floor
#: 39 clear of its population refuses only a total collapse, and the remedy for that is the floor,
#: never the headroom.
# RE-MEASURED 2026-09-19 at 69 published modules (the walk skips every `_`-prefixed part, so
# `__init__.py` is not one). The floor stood at 40 while the tree held 69, which is 4 past the
# headroom -- a floor the population has outgrown refuses only a total collapse and passes a walk
# that lost a third of its corpus. RE-TAKEN rather than the headroom widened; that direction is the
# waiver nothing uses.
KIT_FLOOR = 60
KIT_HEADROOM = 25

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
    assert_floor(len(modules), floor=KIT_FLOOR, what='published kit module')
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
    assert_floor(len(modules), floor=KIT_FLOOR, what='published kit module')
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


# -- HOLE 4: a kit module the IMPORT detector cannot be reached by, BY SOME SPELLING. --------------


#: The modules living below the top level, MEASURED 2026-09-18 at 13 across `famtests` and
#: `githooks`. Its own floor because the defect this section exists for is reachable ONLY through a
#: sub-package: a corpus of top-level modules would pass every arm here while blind.
# RE-MEASURED 2026-09-19 at 22 sub-package modules, 2 past the old ceiling of 8 + 12.
NESTED_FLOOR = 18
NESTED_HEADROOM = 12

#: The declared spellings. A floor rather than a pin, because the remedy for a spelling nobody
#: resolved is to ADD a row and widen the reader -- which must not red the guard that demanded it.
SPELLING_FLOOR = 3
SPELLING_HEADROOM = 3

#: Modules x spellings, MEASURED 2026-09-18 at 162. The cross product is the corpus, so it carries
#: the floor rather than either factor alone: a parametrisation that lost one whole spelling still
#: reports a full green over the other two, which is the shape that let this defect live twice.
# RE-MEASURED 2026-09-19 at 207 (69 modules x 3 spellings), 7 past the old ceiling of 110 + 90.
CASE_FLOOR = 180
CASE_HEADROOM = 90

#: The sub-packages of the kit under measurement, read from the same walk `kit_modules` does.
SUBPACKAGES = kit_subpackages(DEV_DIR)


def _published_modules() -> tuple[Path, ...]:
    """Every module `kit_modules` publishes, as PATHS -- the same walk, re-derived for the round trip."""
    return tuple(
        sorted(
            path
            for path in DEV_DIR.rglob('*.py')
            if not any(part.startswith('_') for part in path.relative_to(DEV_DIR).parts)
        )
    )


def _spelled(path: Path, spelling: str) -> str:
    """One published module, written the way *spelling* says a consumer writes it, as SOURCE."""
    dotted = '.'.join((PACKAGE, *path.relative_to(DEV_DIR).with_suffix('').parts))
    parent, stem = dotted.rsplit('.', 1)
    names = sorted(public_names(ast.parse(path.read_text(encoding='utf-8'))))
    name = names[0] if names else 'anything'
    return spelling.format(dotted=dotted, parent=parent, stem=stem, name=name) + '\n'


#: `(module path, spelling)` -- the corpus, built at import so the arms below are one case per pair
#: and a failure NAMES the module and the spelling instead of returning a dict of them.
REACHABILITY_CASES = tuple((path, spelling) for path in _published_modules() for spelling in IMPORT_SPELLINGS)

#: The same, restricted to the sub-package half, where the defect lives and where a top-level corpus
#: would prove nothing.
NESTED_CASES = tuple((path, spelling) for path, spelling in REACHABILITY_CASES if path.parent != DEV_DIR)


def _case_id(case: tuple[Path, str]) -> str:
    path, spelling = case
    return f'{path.stem}::{spelling}'


def test_the_reachability_corpus_is_floored_on_both_sides() -> None:
    """THE FLOOR, BOTH SIDES, for the parametrisation below -- which cannot floor itself.

    A `pytest.mark.parametrize` over an empty sequence does not fail, it COLLECTS NOTHING, and a
    suite that ran zero cases reports exactly what a suite whose cases all passed reports. So the
    corpus is measured here: the modules, the sub-package half of them, the declared spellings, and
    the cross product that is the real population. The high side is in because a floor the tree has
    outgrown stops separating a clean walk from a broken one -- both readings come from
    `lab_commons.dev.floors` rather than being written by hand a ninth time.
    """
    modules = _published_modules()
    assert_floor(len(modules), floor=KIT_FLOOR, what='published kit module')
    assert_floor_still_binds(len(modules), floor=KIT_FLOOR, headroom=KIT_HEADROOM, what='published kit module')
    nested = [path for path in modules if path.parent != DEV_DIR]
    assert_floor(len(nested), floor=NESTED_FLOOR, what='sub-package kit module')
    assert_floor_still_binds(len(nested), floor=NESTED_FLOOR, headroom=NESTED_HEADROOM, what='sub-package kit module')
    assert_floor(len(IMPORT_SPELLINGS), floor=SPELLING_FLOOR, what='declared import spelling')
    assert_floor_still_binds(
        len(IMPORT_SPELLINGS), floor=SPELLING_FLOOR, headroom=SPELLING_HEADROOM, what='declared import spelling'
    )
    assert_floor(len(REACHABILITY_CASES), floor=CASE_FLOOR, what='module x spelling reachability')
    assert_floor_still_binds(
        len(REACHABILITY_CASES), floor=CASE_FLOOR, headroom=CASE_HEADROOM, what='module x spelling reachability'
    )
    assert NESTED_CASES, 'the sub-package half of the corpus is empty, so the arms below are about top-level modules'
    assert SUBPACKAGES, 'the kit published no sub-package, so the bound the reader is gated on is vacuous here'


@pytest.mark.parametrize('case', REACHABILITY_CASES, ids=_case_id)
def test_every_published_kit_module_is_named_by_every_import_spelling(case: tuple[Path, str]) -> None:
    """THE ARM THAT WOULD HAVE CAUGHT IT: what `kit_modules` PUBLISHES, `imported_kit_modules` NAMES.

    The two halves are one agreement, and the version of this arm that shipped on 2026-09-17 held
    them to it over ONE spelling each. That is why it passed while the defect was live: it drove
    `import <dotted>` and `from <parent> import <stem>`, the two forms the fix of that day had just
    taught the reader, and the third -- `from <dotted> import <name>`, how a consumer imports a
    FUNCTION out of a sub-package module -- was never written down. A module can be imported in more
    than one way, so the corpus is MODULES x SPELLINGS, and the declared set of spellings is
    `IMPORT_SPELLINGS`, which lives in the kit and not in this file: a spelling the reader must
    resolve is a fact about the reader.

    MEASURED: `from lab_commons.dev.famtests.citedtests import take_scan` answered `{'famtests'}`,
    a token no published module is named by, so every consumer adopting a `famtests` module in the
    natural form graded NAMED_ONLY forever -- the grade that means nothing corroborates the claim.
    It cost no red anywhere, because a detector that never fires reports what a clean tree reports.
    """
    path, spelling = case
    named = imported_kit_modules(ast.parse(_spelled(path, spelling)), package=PACKAGE, subpackages=SUBPACKAGES)
    assert path.stem in named, (
        f'`{path.stem}` is published by `kit_modules` and is not NAMED by `imported_kit_modules` when '
        f'a consumer writes `{_spelled(path, spelling).strip()}` -- it answered {sorted(named)}. The '
        f'IMPORT detector is blind to every file that adopted it by this spelling. Widen the reader; '
        f'do not narrow what `kit_modules` publishes, and do not delete the spelling.'
    )


@pytest.mark.parametrize('case', NESTED_CASES, ids=_case_id)
def test_a_resolver_one_level_short_names_no_kit_module_by_any_spelling(case: tuple[Path, str]) -> None:
    """THE PLANT, over the same cross product, and it is the real bug rather than an imitation of it.

    `package='lab_commons'` is one level short of the kit. Under it every module resolves one segment
    deeper than it is, and the repair that would make the arm above pass by reading EVERY segment is
    exactly the repair that makes `lab_commons.dev.bounded` answer `bounded` here -- at which point
    `_refuse_mismatch` sees a match, the wrong depth stops being refusable, and the fix has switched
    off the guard it repairs. So the bound is TWO segments below the package with the second one
    gated on `kit_subpackages`: `famtests` is a directory in the kit and `dev` is not, which is the
    only fact that tells the two cases apart.

    Restricted to the sub-package half because that is where a widening would land. Without this
    plant the arm above would be asserting a property of the strings rather than of the resolver.
    """
    path, spelling = case
    named = imported_kit_modules(ast.parse(_spelled(path, spelling)), package='lab_commons', subpackages=SUBPACKAGES)
    assert named == frozenset({'dev'}), (
        f'a resolver one level short of the kit answered {sorted(named)} for '
        f'`{_spelled(path, spelling).strip()}`; it must reach no further than `dev`. Anything else '
        f'means the two-segment bound was widened, and `_refuse_mismatch` can no longer see a '
        f'`package` resolving at the wrong depth.'
    )


@pytest.mark.parametrize(
    'spelling', ['from lab_commons.dev.bounded import run_bounded', 'import lab_commons.dev.bounded']
)
def test_the_short_package_is_refused_in_either_spelling(tmp_path: Path, spelling: str) -> None:
    """THE PLANT AT THE OTHER DEPTH, driven through the REAL census, in BOTH spellings of one import.

    `test_a_package_that_resolves_onto_nothing_is_refused` plants exactly one of them. MEASURED
    2026-09-18: under the OLD reader the `import lab_commons.dev.bounded` spelling of that same
    consumer resolved to `{'dev', 'bounded'}` and the refusal did NOT fire -- the same
    spelling-bound blindness as the round trip, this time inside the guard rather than the detector.
    """
    kit_dir, root = _plant(tmp_path, {'bounded.py': _SILENT_KIT}, {'scripts/gate/runner.py': f'{spelling}\n'})
    with pytest.raises(PackageMismatch, match='wrong depth'):
        take_census(
            {'scripts/gate/runner.py': 'stays'},
            kit_modules(kit_dir),
            root=root,
            package='lab_commons',
            row_floor=1,
            module_floor=1,
        )


def test_a_name_no_kit_module_answers_to_is_not_manufactured() -> None:
    """THE CONTROL IN THE OTHER DIRECTION. Widening the resolver must not make every import a hit.

    The candidate set may over-emit -- it yields sub-package tokens and imported function names --
    and that is only safe because it is intersected with what `kit_modules` published. An import of
    another library must contribute NOTHING, or the IMPORT detector would corroborate every claim
    and the census would flag the whole roster.
    """
    form = 'import pathlib\nfrom collections.abc import Mapping\nfrom lab_commons import paths\n'
    assert imported_kit_modules(ast.parse(form), package=PACKAGE, subpackages=SUBPACKAGES) == frozenset()


def test_a_sub_package_the_kit_does_not_publish_is_not_read_two_deep() -> None:
    """THE BOUND'S OWN ARM: the second segment is earned by `kit_subpackages`, never by shape alone.

    Planted from the other side -- a consumer importing `lab_commons.dev.elsewhere.thing` when the
    kit publishes no `elsewhere`. If the reader took the second segment unconditionally this would
    answer `thing`, and `thing` is exactly the shape of a top-level module name read one level short.
    """
    form = 'from lab_commons.dev.elsewhere.thing import helper\n'
    assert imported_kit_modules(ast.parse(form), package=PACKAGE, subpackages=SUBPACKAGES) == frozenset({'elsewhere'})
    widened = imported_kit_modules(ast.parse(form), package=PACKAGE, subpackages=frozenset({'elsewhere'}))
    assert widened == frozenset({'elsewhere', 'thing'})


# ------------------------------- a package whose surface IS its `__init__` was invisible until today


def test_a_package_whose_whole_surface_is_its_init_is_a_kit_module(tmp_path: Path) -> None:
    """THE BLINDNESS, PLANTED AND DRIVEN THROUGH THE REAL WALK, and both of its sides.

    `_published` drops any path with a private part and `__init__.py` has one, so a package that
    publishes everything from its `__init__` was in NEITHER `kit_modules` nor `kit_subpackages`. The
    live instance is `lab_commons.dev.agenthooks`: eleven public names, seen by nothing, and a
    motronics roster row graded `untouched` purely because its one kit import names it -- while
    being 98.0% identical to optimi-lab's file of the same name.

    THE OTHER SIDE IS THE BAR, and it is what stops the repair from manufacturing agreement. An
    `__init__` that declares nothing is an INDEX, not a module: emitting it would let a bare
    `from lab_commons.dev import famtests` corroborate a row against a surface that does not exist.
    """
    (tmp_path / 'engine').mkdir()
    (tmp_path / 'engine' / '__init__.py').write_text(
        '"""E."""\n\n\ndef decide() -> int:\n    return 1\n', encoding='utf-8'
    )
    (tmp_path / 'index').mkdir()
    (tmp_path / 'index' / '__init__.py').write_text('"""I."""\n\n__all__: list[str] = []\n', encoding='utf-8')
    (tmp_path / '_hidden').mkdir()
    (tmp_path / '_hidden' / '__init__.py').write_text('"""H."""\n\n\ndef x() -> int:\n    return 1\n', encoding='utf-8')
    (tmp_path / '__init__.py').write_text('"""Root."""\n\n\ndef root() -> int:\n    return 1\n', encoding='utf-8')

    found = {path.parent.name for path in supersede.package_modules(tmp_path)}
    assert found == {'engine'}, (
        f'{sorted(found)}: the package with a real surface must be seen, the empty INDEX must not '
        f'(it would invent corroboration), the private one must not, and the ROOT must not -- a kit '
        f'is never one of its own modules.'
    )
    names = {module.name for module in supersede.kit_modules(tmp_path)}
    assert 'engine' in names, f'{sorted(names)}: the package module is named by its DIRECTORY'
    assert 'index' not in names, f'{sorted(names)}: an empty INDEX must not be a module'
    assert '__init__' not in names, f'{sorted(names)}: a package module is never named `__init__`'


def test_the_live_kit_no_longer_hides_agenthooks() -> None:
    """THE REGRESSION THIS CLOSES, on the real kit rather than on a fixture.

    Stated over the NAMED set and not a count: a total cannot say which package came back, and the
    honest-looking repair when a digit disagrees is to edit the digit.
    """
    directory = Path(supersede.__file__).resolve().parent
    modules = {module.name for module in supersede.kit_modules(directory)}
    assert {'agenthooks', 'githooks'} <= modules, (
        f'agenthooks publishes eleven names from its `__init__` and githooks sixteen; both must be '
        f'kit modules. Missing: {sorted({"agenthooks", "githooks"} - modules)}'
    )
    assert 'famtests' not in modules, (
        'famtests declares `__all__: list[str] = []` and publishes nothing, so it is an INDEX. A row '
        'for it would let a bare `from lab_commons.dev import famtests` corroborate against an empty '
        'surface -- a detector inventing the finding it reports.'
    )
