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
    FAILING_CONTEXTS,
    VACUOUS_ASSERT_METHODS,
    Bucket,
    FileFacts,
    VacuousScanError,
    census,
    collect,
    count_test_functions,
    is_assertion,
    is_vacuous_assert,
    mark_names,
    pytest_files,
    read_facts,
    site_ledger,
    timeout_ceilings,
    vacuous_test_functions,
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
    rows = (FileFacts(name='tests/test_a.py', tests=1, mark_uses=(), call_uses=(), ceilings_s=(), vacuous_sites=()),)
    with pytest.raises(ValueError, match='distinct'):
        census(rows, selects=bool, rules=[('x', bool), ('x', bool)], residual='r', floor=1)
    with pytest.raises(ValueError, match='distinct'):
        census(rows, selects=bool, rules=[('r', bool)], residual='r', floor=1)
    with pytest.raises(VacuousScanError, match='below the 2 floor'):
        census(rows, selects=bool, rules=[], residual='r', floor=2)


def test_a_missing_bucket_name_raises_rather_than_reading_clean() -> None:
    """A misspelled lookup returning an empty bucket would report a typo as a healthy population."""
    empty = Bucket('nothing', ())
    assert empty.files == 0
    assert empty.tests == 0
    assert empty.by_directory() == {}
    with pytest.raises(KeyError):
        census(
            (FileFacts(name='tests/test_a.py', tests=1, mark_uses=(), call_uses=(), ceilings_s=(), vacuous_sites=()),),
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


# ------------------------------------------------- order and multiplicity: what a set cannot hold

#: THE SPELLINGS ARE ASSEMBLED, NEVER WRITTEN OUT, and that is the trap this subject has already
#: sprung twice. A fixture naming an imperative waiver in full makes the scanner count ITSELF: the
#: consumer guard that first hit this scored zero against its own file for exactly that reason. So
#: the constants below are built from `_PYTEST` plus a verb, and every planted site lives in a file
#: this module writes on purpose -- the only place the reader is ever pointed at.
_PYTEST = 'pytest'
_WAIVE = 'skip'
_WAIVE_IF = 'skipif'

#: One file, THREE waiver sites, TWO spellings. A set-valued reading cannot tell it from a file
#: holding one of each, which is the whole of the multiplicity gap.
_CROWDED = (
    f'import {_PYTEST}\n\n\n'
    f'@{_PYTEST}.mark.{_WAIVE_IF}(True, reason="one")\n'
    f'def test_a() -> None: ...\n\n\n'
    f'@{_PYTEST}.mark.{_WAIVE_IF}(True, reason="two")\n'
    f'def test_b() -> None: ...\n\n\n'
    f'def test_c() -> None:\n'
    f'    {_PYTEST}.{_WAIVE}("three")\n'
)

#: The same two spellings ONCE each. Its `marks` differs from `_CROWDED`'s by nothing at all.
_SPARSE = (
    f'import {_PYTEST}\n\n\n'
    f'@{_PYTEST}.mark.{_WAIVE_IF}(True, reason="one")\n'
    f'def test_a() -> None: ...\n\n\n'
    f'def test_b() -> None:\n'
    f'    {_PYTEST}.{_WAIVE}("two")\n'
)

#: The imperative call reached through an alias import, which a qualified-only reading misses.
_ALIASED = f'from {_PYTEST} import {_WAIVE}\n\n\ndef test_a() -> None:\n    {_WAIVE}("aliased")\n'

#: A file that only TALKS about waivers -- in a docstring, a comment and a string constant. It is
#: the self-count trap planted where the scan is pointed deliberately, and it must read as zero.
_PROSE = (
    f'"""Never write the {_WAIVE_IF} decorator here, and never call {_PYTEST}.{_WAIVE}() either."""\n\n'
    f'# {_PYTEST}.mark.{_WAIVE} and {_PYTEST}.mark.{_WAIVE_IF} are the decorator spellings.\n'
    f'DOC = "{_PYTEST}.{_WAIVE}(reason)"\n\n\n'
    f'def test_a() -> None: ...\n'
)


def _plant_sites(root: Path) -> Path:
    """A real ``tests/`` tree whose four files differ only in HOW MANY waivers they hold."""
    unit = root / 'tests' / 'unit'
    unit.mkdir(parents=True)
    (unit / 'test_crowded.py').write_text(_CROWDED, encoding='utf-8')
    (unit / 'test_sparse.py').write_text(_SPARSE, encoding='utf-8')
    (unit / 'test_aliased.py').write_text(_ALIASED, encoding='utf-8')
    (unit / 'test_prose.py').write_text(_PROSE, encoding='utf-8')
    return root


def test_two_files_with_the_same_spellings_and_different_counts_are_told_apart(tmp_path: Path) -> None:
    """A ``frozenset`` answers WHICH spellings and never HOW MANY, so a ceiling cannot be read off it.

    Both files below declare the identical mark set. The count is the only reading that separates
    them, and it is exactly what a site ceiling is: without it an already-pinned module absorbs any
    number of new waivers while the NAME set sits still.
    """
    root = _plant_sites(tmp_path)
    crowded = read_facts(root / 'tests' / 'unit' / 'test_crowded.py', name='crowded')
    sparse = read_facts(root / 'tests' / 'unit' / 'test_sparse.py', name='sparse')

    assert crowded.marks == sparse.marks, 'the premise: the SET reading cannot separate these two'
    assert crowded.sites(_WAIVE, _WAIVE_IF) == 3
    assert sparse.sites(_WAIVE, _WAIVE_IF) == 2
    assert crowded.mark_uses == (_WAIVE_IF, _WAIVE_IF)


def test_the_imperative_call_is_read_and_the_decorator_is_not_counted_twice(tmp_path: Path) -> None:
    """A waiver RAISED in a body is a statement, not a decoration, and it waives just as fully.

    A decorator-only reading reports the aliased file as waiver-free while it waives at run time.
    The ``mark.``-owned attribute is excluded from the call reading because ``mark_names`` already
    holds it -- counting it in both would double every decorator and halve any ceiling built here.
    """
    root = _plant_sites(tmp_path)
    aliased = read_facts(root / 'tests' / 'unit' / 'test_aliased.py', name='aliased')
    crowded = read_facts(root / 'tests' / 'unit' / 'test_crowded.py', name='crowded')

    assert aliased.calls == frozenset({_WAIVE})
    assert aliased.marks == frozenset(), 'nothing here is a decoration'
    assert aliased.sites(_WAIVE, _WAIVE_IF) == 1
    assert crowded.call_uses == (_WAIVE,), 'the two decorators are marks, counted once and there'


def test_a_waiver_that_is_only_text_is_not_a_site(tmp_path: Path) -> None:
    """THE SELF-COUNT TRAP, planted where the scan is pointed on purpose.

    Every spelling in that fixture sits in a docstring, a comment or a string constant. A text scan
    would score the file that EXPLAINS the rule above the file that breaks it; a parser sees
    declarations and nothing else.
    """
    root = _plant_sites(tmp_path)
    prose = read_facts(root / 'tests' / 'unit' / 'test_prose.py', name='prose')
    assert prose.sites(_WAIVE, _WAIVE_IF) == 0
    assert prose.mark_uses == ()
    assert prose.call_uses == ()


def test_the_ledger_moves_in_both_directions(tmp_path: Path) -> None:
    """A RATCHET HAS TWO SIDES, and one reading carries both: the KEYS and the VALUES.

    The keys are the named set -- a file that stops waiving drops out, and a declaration naming it
    reds. The values are the ceiling -- a file already in the set absorbing one more moves the sum,
    which is the half the named set alone is blind to.
    """
    root = _plant_sites(tmp_path)
    facts = collect(pytest_files(root), root=root, floor=4)
    ledger = site_ledger(facts, _WAIVE, _WAIVE_IF)

    assert ledger == {
        'tests/unit/test_aliased.py': 1,
        'tests/unit/test_crowded.py': 3,
        'tests/unit/test_sparse.py': 2,
    }, 'a clean file is absent rather than present with a zero'
    assert sum(ledger.values()) == 6

    (root / 'tests' / 'unit' / 'test_sparse.py').write_text(_CROWDED, encoding='utf-8')
    risen = site_ledger(collect(pytest_files(root), root=root, floor=4), _WAIVE, _WAIVE_IF)
    assert set(risen) == set(ledger), 'THE POINT: the named set did not move'
    assert sum(risen.values()) == 7, 'and the count is the only reading that saw it'

    (root / 'tests' / 'unit' / 'test_aliased.py').write_text(_BARE, encoding='utf-8')
    vanished = site_ledger(collect(pytest_files(root), root=root, floor=4), _WAIVE, _WAIVE_IF)
    assert set(ledger) - set(vanished) == {'tests/unit/test_aliased.py'}


def test_a_ledger_over_no_names_is_refused_rather_than_answered_empty() -> None:
    """A scan for nothing finds nothing and agrees with every claim anybody makes about it."""
    with pytest.raises(ValueError, match='at least one name'):
        site_ledger(())


def test_the_count_and_the_names_come_from_one_read_of_the_file(tmp_path: Path) -> None:
    """ONE PARSE, both readings: a count and a name set taken in two passes can disagree.

    The file is REWRITTEN between the two questions. A reading that re-opened the file for the count
    would answer about the new bytes and the old spellings at once -- a disagreement whose two
    halves are each individually defensible, which is why it would never be diagnosed.
    """
    path = tmp_path / 'test_moving.py'
    path.write_text(_CROWDED, encoding='utf-8')
    facts = read_facts(path, name='moving')
    path.write_text(_BARE, encoding='utf-8')

    assert facts.sites(_WAIVE, _WAIVE_IF) == 3
    assert facts.marks == frozenset({_WAIVE_IF})


_SHAPES = """import unittest


def test_vacuous():
    assert build() is not None


def test_precondition_plus_real():
    v = build()
    assert v is not None
    assert v.torque > 0.0


def test_real_only():
    assert build().torque > 0.0


def test_no_assertions_at_all():
    build()


def test_helper_named_for_asserting():
    _assert_the_declared_gap_is_a_gap(build())
    assert build() is not None


def test_raises_block():
    with pytest.raises(ValueError):
        build()
    assert build() is not None


def test_skip_does_not_license_it():
    pytest.skip('reason')
    assert build() is not None


class T(unittest.TestCase):
    def test_unittest_vacuous(self):
        self.assertIsNotNone(build())

    def test_unittest_real(self):
        self.assertEqual(build(), 1)
        self.assertIsNotNone(build())
"""


def test_the_shape_reader_names_only_the_tests_that_prove_nothing() -> None:
    """Every distinction at once.

    A change that stops seeing the shape -- or starts seeing too much -- cannot pass here by
    agreeing with a single example.
    """
    sites = vacuous_test_functions(ast.parse(_SHAPES))
    assert sites == ('4:test_vacuous', '33:test_skip_does_not_license_it', '39:test_unittest_vacuous'), (
        f'got {sites}: a precondition beside a real assertion, a real-only test, a test with NO '
        f'assertions, a helper named for asserting and a raises block must all be left alone -- while '
        f'the SKIPPED one must be named, because a skipped test proves nothing and may not license '
        f'the vacuous assertion under it'
    )


def test_the_shape_reader_is_blind_to_a_compound_test() -> None:
    """``x is not None and x.torque > 0`` is a BoolOp, not this shape -- it constrains the value."""
    assert vacuous_test_functions(ast.parse('def test_c():\n    assert build() is not None and build().t > 0\n')) == ()


def test_the_vacuous_sites_ride_on_the_same_single_read_as_the_declarations(tmp_path: Path) -> None:
    """A SHAPE and a DECLARATION off ONE parse: two reads of one file can answer about two files."""
    path = tmp_path / 'test_shapes.py'
    path.write_text(_SHAPES, encoding='utf-8')
    facts = read_facts(path, name='tests/test_shapes.py')
    path.write_text(_BARE, encoding='utf-8')
    assert facts.vacuous_sites == ('4:test_vacuous', '33:test_skip_does_not_license_it', '39:test_unittest_vacuous')
    assert facts.tests == 9, 'the function count and the shapes are read off the same tree'


def test_a_file_that_does_not_parse_reports_no_shapes_and_says_so(tmp_path: Path) -> None:
    """An unreadable file must not silently contribute an empty offender set that reads as clean."""
    path = tmp_path / 'test_broken.py'
    path.write_text('def (:\n', encoding='utf-8')
    facts = read_facts(path, name='tests/test_broken.py')
    assert facts.vacuous_sites == ()
    assert facts.parse_error, 'the empty reading is only honest because the file is FLAGGED unreadable'


def test_the_vacuous_method_set_is_named_and_the_failing_contexts_are_too() -> None:
    """Named SETS, not counts: a member that silently leaves is a hole with no symptom."""
    assert frozenset({'assertIsNotNone'}) == VACUOUS_ASSERT_METHODS
    assert frozenset({'assertRaises', 'deprecated_call', 'raises', 'warns'}) == FAILING_CONTEXTS
    assert is_vacuous_assert(ast.parse('self.assertIsNotNone(x)').body[0])
    assert is_assertion(ast.parse('with pytest.raises(ValueError):\n    f()\n').body[0])
    assert not is_assertion(ast.parse('pytest.skip("reason")').body[0]), 'a skip proves nothing'
