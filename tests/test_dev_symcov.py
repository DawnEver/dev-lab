"""Symbol coverage driven over REAL Python files on disk, parsed by the real parser.

EVERY FIXTURE HERE IS A MODULE THAT WOULD IMPORT. The subject is an AST reading, so a test that
hands the scanner a hand-built tree or a string constant is measuring the fixture's author rather
than the scanner; each arm below writes ``.py`` files into ``tmp_path`` and lets ``ast`` do the
reading, including the arms about files that will NOT parse, which are real syntax errors rather
than a mocked failure.

THE TWO DIRECTIONS THIS MEASUREMENT CAN FLATTER ITSELF are what most of the arms are about, because
they are the reason the module re-expresses its original rather than copying it. An unreadable file
on the SOURCE side shrinks the denominator and raises the percentage; an unreadable file on the
TARGET side shrinks the universe every name is looked up in and lowers it. Both are planted, in both
directions, so a scanner that reported everything readable and one that reported nothing would each
fail here.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

import lab_commons.dev.symcov as symcov_module
from lab_commons.dev.symcov import (
    IGNORED_DIRECTORIES,
    Coverage,
    Unreadable,
    definitions,
    mentions,
    python_files,
    read_module,
    survey,
    symbols_under,
)
from lab_commons.dev.testfacts import VacuousScanError


def _plant(root: Path, name: str, body: str) -> Path:
    """Write one REAL source file, creating parents. Returns its path."""
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding='utf-8')
    return path


def _first_letter(path: Path) -> str:
    """A grouping key that is a fact about the FIXTURE, standing in for a caller's own."""
    return path.stem[0]


# ---------------------------------------------------------------- reading one file


def test_a_module_that_parses_is_returned_as_a_tree(tmp_path: Path) -> None:
    """The ordinary case, so the refusal arms below are not the only thing exercised."""
    path = _plant(tmp_path, 'ok.py', 'def alpha() -> None:\n    """d."""\n')
    got = read_module(path)
    assert not isinstance(got, Unreadable)
    assert definitions(got, top_level_only=True) == ['alpha']


def test_a_file_that_will_not_parse_comes_back_as_DATA_and_not_as_a_line_on_stderr(tmp_path: Path) -> None:
    """The improvement this module exists for: a caller can BRANCH on it, a stderr line is not that."""
    path = _plant(tmp_path, 'broken.py', 'def alpha(:\n')
    got = read_module(path)
    assert isinstance(got, Unreadable)
    assert got.path == path
    assert got.reason, 'an unreadable file with no reason is a refusal that names nothing'


def test_a_file_that_is_not_utf8_is_unreadable_rather_than_silently_mangled(tmp_path: Path) -> None:
    """Decoding with a replacement character invents source nobody wrote, and it parses."""
    path = tmp_path / 'latin.py'
    path.write_bytes(b'alpha = "\xff\xfe not utf-8"\n')
    assert isinstance(read_module(path), Unreadable)


def test_a_directory_that_cannot_be_read_as_a_file_is_unreadable_rather_than_raising(tmp_path: Path) -> None:
    """``OSError`` is the third way a walk meets a path it cannot use, and it is the same answer."""
    (tmp_path / 'pkg').mkdir()
    assert isinstance(read_module(tmp_path / 'pkg'), Unreadable)


# ---------------------------------------------------------------- what counts as a definition


def test_top_level_public_classes_and_functions_are_the_denominator(tmp_path: Path) -> None:
    """Sync, async and class, and nothing private -- the four facts the source side stands on."""
    body = (
        'import os\n\n\n'
        'def public() -> None:\n    """d."""\n\n\n'
        'async def apublic() -> None:\n    """d."""\n\n\n'
        'class Public:\n    """d."""\n\n\n'
        'def _private() -> None:\n    """d."""\n'
    )
    tree = read_module(_plant(tmp_path, 'm.py', body))
    assert not isinstance(tree, Unreadable)
    assert sorted(definitions(tree, top_level_only=True)) == ['Public', 'apublic', 'public']


def test_a_nested_definition_is_invisible_to_the_source_side_and_visible_to_the_target_side(tmp_path: Path) -> None:
    """ONE FIXTURE, BOTH READINGS, which is the only way the asymmetry can be seen to be deliberate.

    A migrated helper often lands as a method or a closure, so the TARGET walk must find it or the
    measurement undercounts twice over; the SOURCE walk must not, or a helper inside a function
    would be counted as a public symbol somebody owes a migration for.
    """
    body = 'class Holder:\n    """d."""\n\n    def method(self) -> None:\n        """d."""\n'
    tree = read_module(_plant(tmp_path, 'm.py', body))
    assert not isinstance(tree, Unreadable)
    assert definitions(tree, top_level_only=True) == ['Holder']
    assert sorted(definitions(tree, top_level_only=False)) == ['Holder', 'method']


def test_top_level_only_is_a_REQUIRED_KEYWORD() -> None:
    """The two readings above differ by this flag alone, so a default would pick one silently."""
    parameter = inspect.signature(definitions).parameters['top_level_only']
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty


# ---------------------------------------------------------------- the walk


def test_the_walk_is_sorted_and_skips_the_ignored_directories(tmp_path: Path) -> None:
    """Determinism, and the one exclusion that is a fact about PYTHON rather than about a repo."""
    _plant(tmp_path, 'b.py', '')
    _plant(tmp_path, 'a.py', '')
    _plant(tmp_path, 'pkg/__pycache__/a.py', '')
    _plant(tmp_path, 'notes.txt', '')
    assert python_files(tmp_path) == (tmp_path / 'a.py', tmp_path / 'b.py')
    assert '__pycache__' in IGNORED_DIRECTORIES


def test_the_ignored_set_is_a_DECLARATION_the_walk_consults(tmp_path: Path) -> None:
    """A caller may widen it, and the planted control proves the argument reaches the filter."""
    _plant(tmp_path, 'vendor/a.py', '')
    _plant(tmp_path, 'b.py', '')
    assert python_files(tmp_path, ignore=frozenset({'vendor'})) == (tmp_path / 'b.py',)
    assert len(python_files(tmp_path, ignore=frozenset())) == 2


# ---------------------------------------------------------------- the target universe


def test_the_target_universe_is_every_public_name_defined_anywhere_under_the_root(tmp_path: Path) -> None:
    """Nested included, across files, with the unreadable list EMPTY so the arm below means something."""
    _plant(tmp_path, 'one.py', 'def alpha() -> None:\n    """d."""\n')
    _plant(tmp_path, 'sub/two.py', 'class Beta:\n    """d."""\n\n    def gamma(self) -> None:\n        """d."""\n')
    found = symbols_under(tmp_path)
    assert found.names == frozenset({'alpha', 'Beta', 'gamma'})
    assert found.unreadable == ()
    assert found.complete


def test_an_unreadable_TARGET_file_is_named_rather_than_shrinking_the_universe_in_silence(tmp_path: Path) -> None:
    """The bias that reads as MORE work remaining: names the tree holds become absent by accident."""
    _plant(tmp_path, 'one.py', 'def alpha() -> None:\n    """d."""\n')
    _plant(tmp_path, 'broken.py', 'class Beta(:\n')
    found = symbols_under(tmp_path)
    assert found.names == frozenset({'alpha'})
    assert [item.path.name for item in found.unreadable] == ['broken.py']
    assert not found.complete


# ---------------------------------------------------------------- the survey


def _library(root: Path) -> Path:
    """A source tree of four public symbols across two grouping keys."""
    _plant(root, 'alpha.py', 'def landed() -> None:\n    """d."""\n\n\nclass AlsoLanded:\n    """d."""\n')
    _plant(root, 'beta.py', 'def missing() -> None:\n    """d."""\n\n\ndef _ignored() -> None:\n    """d."""\n')
    _plant(root, 'brava.py', 'def also_missing() -> None:\n    """d."""\n')
    return root


def test_a_survey_counts_the_source_and_looks_every_name_up_in_the_target(tmp_path: Path) -> None:
    """The whole mechanism in one arm: per-key totals, per-key landings, and the names that did not."""
    source = _library(tmp_path / 'src')
    target = tmp_path / 'dst'
    _plant(target, 'x.py', 'class Wrapper:\n    """d."""\n\n    def landed(self) -> None:\n        """d."""\n')
    _plant(target, 'y.py', 'class AlsoLanded:\n    """d."""\n')
    got = survey(source, target, _first_letter, floor=4)
    assert dict(got.total) == {'a': 2, 'b': 2}
    assert dict(got.landed) == {'a': 2, 'b': 0}
    assert got.absent == {'b': ('also_missing', 'missing')}
    assert (got.matched, got.counted) == (2, 4)
    assert got.complete


def test_the_grouping_key_is_the_CALLERS_and_the_module_learns_nothing_from_it(tmp_path: Path) -> None:
    """How a tree divides into modules is a fact about that tree, so a second key regroups the same run."""
    source = _library(tmp_path / 'src')
    target = tmp_path / 'dst'
    _plant(target, 'x.py', 'def landed() -> None:\n    """d."""\n')
    got = survey(source, target, lambda _path: 'all', floor=4)
    assert dict(got.total) == {'all': 4}
    assert got.counted == 4


def test_an_unreadable_SOURCE_file_is_named_rather_than_shrinking_the_denominator(tmp_path: Path) -> None:
    """The bias that FLATTERS: the original's docstring forbade it and its own ``continue`` did it."""
    source = _library(tmp_path / 'src')
    _plant(source, 'crash.py', 'def hidden(:\n')
    target = tmp_path / 'dst'
    _plant(target, 'x.py', 'def landed() -> None:\n    """d."""\n\n\nclass AlsoLanded:\n    """d."""\n')
    got = survey(source, target, _first_letter, floor=4)
    assert got.counted == 4, 'the unreadable file must not be counted as symbols it does not have'
    assert [item.path.name for item in got.unreadable_source] == ['crash.py']
    assert not got.complete, 'a caller that cannot tell is the forbidden shape'


def test_a_complete_survey_says_so_so_the_incompleteness_flag_is_not_always_false(tmp_path: Path) -> None:
    """THE CONTROL IN THE OTHER DIRECTION for both unreadable lists at once."""
    source = _library(tmp_path / 'src')
    target = tmp_path / 'dst'
    _plant(target, 'x.py', 'def landed() -> None:\n    """d."""\n')
    got = survey(source, target, _first_letter, floor=4)
    assert (got.unreadable_source, got.unreadable_target) == ((), ())
    assert got.complete


# ---------------------------------------------------------------- the floor


def test_a_source_below_its_floor_refuses_rather_than_reporting_a_percentage(tmp_path: Path) -> None:
    """The floor's whole point: a tree that moved must not survey into a number about nothing."""
    source = _plant(tmp_path / 'src', 'alpha.py', 'def one() -> None:\n    """d."""\n').parent
    target = _plant(tmp_path / 'dst', 'x.py', 'def one() -> None:\n    """d."""\n').parent
    with pytest.raises(VacuousScanError, match='below the 9 floor'):
        survey(source, target, _first_letter, floor=9)


def test_a_source_exactly_at_its_floor_is_surveyed_so_the_refusal_is_not_unconditional(tmp_path: Path) -> None:
    """THE CONTROL: the same call one number apart, and it must say yes at the boundary."""
    source = _plant(tmp_path / 'src', 'alpha.py', 'def one() -> None:\n    """d."""\n').parent
    target = _plant(tmp_path / 'dst', 'x.py', 'def one() -> None:\n    """d."""\n').parent
    assert survey(source, target, _first_letter, floor=1).counted == 1


def test_an_EMPTY_source_tree_refuses_instead_of_answering_a_hundred_percent(tmp_path: Path) -> None:
    """Zero of zero is the vacuous green arriving through the arithmetic, which is the defect class."""
    source = tmp_path / 'src'
    source.mkdir()
    target = _plant(tmp_path / 'dst', 'x.py', 'def one() -> None:\n    """d."""\n').parent
    with pytest.raises(VacuousScanError, match='below the 1 floor'):
        survey(source, target, _first_letter, floor=1)


def test_a_floor_of_zero_is_refused_because_a_floor_of_zero_is_not_a_floor(tmp_path: Path) -> None:
    """The declaration is refused at the call, not quietly honoured -- zero is the vacuity written down."""
    source = _library(tmp_path / 'src')
    target = _plant(tmp_path / 'dst', 'x.py', 'def landed() -> None:\n    """d."""\n').parent
    with pytest.raises(VacuousScanError, match='floor of 0'):
        survey(source, target, _first_letter, floor=0)


def test_an_EMPTY_target_tree_refuses_because_an_empty_universe_is_not_a_comparison(tmp_path: Path) -> None:
    """Not a threshold and so not a number: every name is absent, and it says nothing about either tree."""
    source = _library(tmp_path / 'src')
    target = tmp_path / 'dst'
    target.mkdir()
    with pytest.raises(VacuousScanError, match='defines no public names'):
        survey(source, target, _first_letter, floor=4)


def test_the_floor_is_a_REQUIRED_KEYWORD() -> None:
    """A default floor is a floor nobody chose, which is how the scan gets to be vacuous again."""
    parameter = inspect.signature(survey).parameters['floor']
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty


def test_the_survey_carries_the_floor_it_was_judged_against(tmp_path: Path) -> None:
    """A result that does not say what it cleared cannot be checked by a reader who was not there."""
    source = _library(tmp_path / 'src')
    target = _plant(tmp_path / 'dst', 'x.py', 'def landed() -> None:\n    """d."""\n').parent
    assert survey(source, target, _first_letter, floor=3).floor == 3


def test_a_coverage_is_frozen_so_a_reader_cannot_edit_the_measurement(tmp_path: Path) -> None:
    """The original accumulated into a mutable counter a caller could keep writing to."""
    source = _library(tmp_path / 'src')
    target = _plant(tmp_path / 'dst', 'x.py', 'def landed() -> None:\n    """d."""\n').parent
    got = survey(source, target, _first_letter, floor=4)
    assert isinstance(got, Coverage)
    with pytest.raises(AttributeError):
        got.floor = 1


# ---------------------------------------------------------------- mentions


def test_a_name_written_in_PROSE_is_found_and_the_first_file_is_named(tmp_path: Path) -> None:
    """The evidence a blanket "this never migrated" has to survive: the tree talks about it."""
    _plant(tmp_path, 'a.py', '"""Nothing to see."""\n')
    _plant(tmp_path, 'b.py', '"""Ported from kill_jmag upstream."""\n')
    found = mentions(tmp_path, frozenset({'kill_jmag', 'never_written'}))
    assert set(found.found) == {'kill_jmag'}
    assert found.found['kill_jmag'].endswith('b.py')


def test_a_mention_matches_WHOLE_WORDS_so_a_short_name_is_not_dragged_in_by_a_longer_one(tmp_path: Path) -> None:
    """``plot_map`` must not be found inside ``plot_map2d``; the planted pair proves both directions."""
    _plant(tmp_path, 'a.py', '"""We kept plot_map2d and nothing else."""\n')
    assert mentions(tmp_path, frozenset({'plot_map'})).found == {}
    assert set(mentions(tmp_path, frozenset({'plot_map2d'})).found) == {'plot_map2d'}


def test_an_unreadable_file_in_a_MENTION_scan_is_named_rather_than_decoded_into_something_else(
    tmp_path: Path,
) -> None:
    """Replacing undecodable bytes invents text, and a search over invented text is not a reading."""
    (tmp_path / 'a_broken.py').write_bytes(b'# \xff\xfe kill_jmag\n')
    _plant(tmp_path, 'b.py', '"""kill_jmag lives here."""\n')
    found = mentions(tmp_path, frozenset({'kill_jmag'}))
    assert set(found.found) == {'kill_jmag'}
    assert [item.path.name for item in found.unreadable] == ['a_broken.py']
    assert not found.complete


def test_an_empty_name_set_is_refused_rather_than_answering_that_nothing_is_mentioned(tmp_path: Path) -> None:
    """Asking about no names and being told none were found is a search that never happened."""
    _plant(tmp_path, 'a.py', '"""text."""\n')
    with pytest.raises(VacuousScanError, match='no names'):
        mentions(tmp_path, frozenset())


def test_the_scanner_knows_no_project_and_its_own_docstrings_name_none() -> None:
    """THE PROPERTY THE ROW WAS JUDGED ON, asserted over the module's own source rather than claimed.

    The original carried this as a sentence and a note that an earlier draft had spelled two project
    names out in order to disclaim them. A sentence cannot fire; this reads the shipped file.
    """
    text = Path(symcov_module.__file__ or '').read_text(encoding='utf-8')
    forbidden = ('motronics', 'motor_jmag', 'ferrari', 'wdg_lab', 'optimi')
    assert [token for token in forbidden if token in text.lower()] == []
    assert len(text) > 1000, 'a vendor-neutrality scan over an empty read is vacuously clean'
