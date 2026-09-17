"""``lab_commons.dev.testfacts`` -- driven over REAL test files planted on disk.

WHY PLANTED FILES AND NOT AST FRAGMENTS. The claim this module makes is about what a repo's ``tests/``
tree says, and the two things that have actually gone wrong in the prior art are both file-shaped: a
mark spelled the other way, and a glob that quietly stopped matching. So every case here writes real
``.py`` files into a real tree and calls the real reader over them.

THE ONE CONTROL THAT MATTERS MOST IS THE NEGATIVE ONE. The whole reason this reads an AST is that
importing a test module can start a live engine. A test that only checked the numbers would pass
just as happily over an implementation that imported everything. So a planted module here performs a
SIDE EFFECT at module scope -- it writes a file -- and the case asserts that the side effect did not
happen. That is the property, and it is the one a reader can accidentally delete.

EVERY SCAN HAS A FLOOR, and the floor has its own case in both directions: it fires on an empty tree
and it does not fire on a populated one. A guard that could not fail is the defect this family cares
most about, and a floor is exactly the kind of guard that silently stops mattering.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from lab_commons.dev.testfacts import (
    Bucket,
    FileFacts,
    VacuousScanError,
    census,
    collect,
    count_test_functions,
    mark_names,
    pytest_files,
    read_facts,
    timeout_ceilings,
)

#: A file that declares BOTH mark spellings, a ceiling and two tests. One file carrying every
#: reading at once is deliberate: it is the shape a reader of a real suite meets.
_RICH = """\
import pytest
from pytest import mark

pytestmark = pytest.mark.slow


@pytest.mark.jmag
@mark.timeout(900)
def test_one() -> None:
    assert True


@mark.ngspice
async def test_two() -> None:
    assert True


def helper() -> None:
    pass
"""

#: A file that declares nothing at all: in whatever population a caller claims it for, it has no
#: stated reason to be there. This is the row the whole census exists to surface.
_BARE = """\
def test_plain() -> None:
    assert True
"""

#: A file whose IMPORT would be observable. If anything here imports rather than parses, the marker
#: file appears and the negative control below fails -- which is the only way that regression is
#: visible at all.
_SIDE_EFFECT = """\
from pathlib import Path

Path(__file__).with_name('IMPORTED').write_text('a module was imported', encoding='utf-8')


@pytest.mark.femm
def test_needs_a_live_engine() -> None:
    assert True
"""

#: A file that does not parse. It must be REPORTED, never dropped.
_BROKEN = 'def test_unclosed(:\n'


def _plant(root: Path) -> Path:
    """A small but real `tests/` tree: four files across two directories."""
    unit = root / 'tests' / 'unit'
    integration = root / 'tests' / 'integration'
    unit.mkdir(parents=True)
    integration.mkdir(parents=True)
    (unit / 'test_rich.py').write_text(_RICH, encoding='utf-8')
    (unit / 'test_bare.py').write_text(_BARE, encoding='utf-8')
    (integration / 'test_side_effect.py').write_text(_SIDE_EFFECT, encoding='utf-8')
    (integration / 'test_broken.py').write_text(_BROKEN, encoding='utf-8')
    return root


def test_the_scan_never_imports_what_it_reads(tmp_path: Path) -> None:
    """THE NEGATIVE CONTROL: a module whose import writes a file is read, and the file never appears.

    Fails in the direction that matters -- an implementation that collected or imported instead of
    parsing would leave `IMPORTED` behind and would also have started whatever the module starts.
    """
    root = _plant(tmp_path)
    facts = collect(pytest_files(root), root=root, floor=4)
    assert len(facts) == 4, 'the plant itself is the floor for this case'
    marker = root / 'tests' / 'integration' / 'IMPORTED'
    assert not marker.exists(), (
        f'{marker} exists, so the scan IMPORTED a test module. That is the failure this module was '
        f'written to make impossible: an import is what starts a live engine.'
    )
    by_name = {row.name: row for row in facts}
    assert 'femm' in by_name['tests/integration/test_side_effect.py'].marks


def test_both_mark_spellings_and_the_ceiling_are_read(tmp_path: Path) -> None:
    """A file that did `from pytest import mark` declares marks just as surely as one that did not."""
    root = _plant(tmp_path)
    rich = read_facts(root / 'tests' / 'unit' / 'test_rich.py', name='tests/unit/test_rich.py')
    assert {'slow', 'jmag', 'ngspice'} <= rich.marks, f'read only {sorted(rich.marks)}'
    assert rich.max_ceiling_s == 900
    assert rich.tests == 2, 'an async test counts, and a plain helper does not'
    assert rich.directory == 'tests/unit'
    assert not rich.parse_error


def test_a_file_with_no_declaration_reads_as_having_none(tmp_path: Path) -> None:
    """The other side: no marks, no ceiling, and `max_ceiling_s` answers 0 rather than None."""
    root = _plant(tmp_path)
    bare = read_facts(root / 'tests' / 'unit' / 'test_bare.py', name='tests/unit/test_bare.py')
    assert bare.marks == frozenset()
    assert bare.max_ceiling_s == 0
    assert bare.tests == 1


def test_an_unparseable_file_is_reported_and_not_dropped(tmp_path: Path) -> None:
    """A dropped file silently shrinks every population it belonged to, which reads as progress."""
    root = _plant(tmp_path)
    facts = collect(pytest_files(root), root=root, floor=4)
    broken = [row for row in facts if row.parse_error]
    assert [row.name for row in broken] == ['tests/integration/test_broken.py']


def test_the_floor_refuses_an_empty_tree_and_passes_a_populated_one(tmp_path: Path) -> None:
    """BOTH SIDES of the floor, through the REAL function. A floor nothing can trip is decoration."""
    empty = tmp_path / 'empty'
    (empty / 'tests').mkdir(parents=True)
    with pytest.raises(VacuousScanError, match='below the 1 floor'):
        collect(pytest_files(empty), root=empty, floor=1)
    root = _plant(tmp_path / 'full')
    assert len(collect(pytest_files(root), root=root, floor=4)) == 4


def _vendor(row: FileFacts) -> bool:
    return bool(row.marks & {'femm', 'jmag'})


def _priced(row: FileFacts) -> bool:
    return row.max_ceiling_s > 300


def test_the_census_cuts_first_match_wins_and_keeps_the_residual(tmp_path: Path) -> None:
    """THE CENSUS over the planted tree, with a tier claim that is the caller's and not this module's.

    `test_rich.py` matches BOTH rules and is counted once, under the first -- a file counted twice
    would make the buckets outsum the population and hide the residual, which is the only bucket
    anybody reads this for.
    """
    root = _plant(tmp_path)
    facts = collect(pytest_files(root), root=root, floor=4)
    out = census(
        facts,
        selects=lambda row: not row.parse_error,
        rules=[('vendor', _vendor), ('priced', _priced)],
        residual='no stated reason',
        floor=4,
        population='claimed',
    )
    assert out.scanned.files == 4, 'the unparseable file is still SCANNED'
    assert out.population.files == 3
    assert out.bucket('vendor').names == ('tests/integration/test_side_effect.py', 'tests/unit/test_rich.py')
    assert out.bucket('priced').names == (), 'test_rich.py already went to vendor: first match wins'
    residual = out.bucket('no stated reason')
    assert residual.names == ('tests/unit/test_bare.py',)
    assert residual.by_directory() == {'tests/unit': 1}
    assert sum(b.files for b in out.buckets) == out.population.files, 'the cut must be a partition'
    assert 'no stated reason' in out.render()


def test_a_rule_order_swap_moves_the_file_and_the_totals_hold(tmp_path: Path) -> None:
    """The control for first-match-wins: swap the rules and the same file lands in the other bucket."""
    root = _plant(tmp_path)
    facts = collect(pytest_files(root), root=root, floor=4)
    out = census(
        facts,
        selects=lambda row: not row.parse_error,
        rules=[('priced', _priced), ('vendor', _vendor)],
        residual='none',
        floor=4,
    )
    assert out.bucket('priced').names == ('tests/unit/test_rich.py',)
    assert out.bucket('vendor').names == ('tests/integration/test_side_effect.py',)
    assert sum(b.files for b in out.buckets) == out.population.files


def test_the_census_refuses_a_duplicate_bucket_name_and_an_empty_corpus() -> None:
    """Two refusals that would otherwise surface far from the mistake."""
    rows = (FileFacts(name='tests/test_a.py', tests=1, marks=frozenset(), ceilings_s=()),)
    with pytest.raises(ValueError, match='distinct'):
        census(rows, selects=bool, rules=[('x', bool), ('x', bool)], residual='r', floor=1)
    with pytest.raises(ValueError, match='distinct'):
        census(rows, selects=bool, rules=[('r', bool)], residual='r', floor=1)
    with pytest.raises(VacuousScanError, match='below the 2 floor'):
        census(rows, selects=bool, rules=[], residual='r', floor=2)


def test_a_missing_bucket_name_raises_rather_than_reading_clean() -> None:
    """A misspelled lookup returning an empty bucket would report a typo as a healthy population."""
    empty = Bucket('nothing', ())
    assert empty.files == 0 and empty.tests == 0 and empty.by_directory() == {}
    with pytest.raises(KeyError):
        census(
            (FileFacts(name='tests/test_a.py', tests=1, marks=frozenset(), ceilings_s=()),),
            selects=bool,
            rules=[('real', bool)],
            residual='r',
            floor=1,
        ).bucket('reel')


def test_a_computed_timeout_is_not_read_as_a_declared_ceiling() -> None:
    """LITERALS ONLY: a ceiling nobody typed is a figure this census must not put on record."""
    tree = ast.parse('import pytest\nWALL = 30 * 60\n\n\n@pytest.mark.timeout(WALL)\ndef test_x(): pass\n')
    assert timeout_ceilings(tree) == ()
    assert mark_names(tree) == ('timeout',)
    assert count_test_functions(tree) == 1
