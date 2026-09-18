"""The controls for :mod:`lab_commons.dev.famtests.citedtests` -- every reader and arm, both ways.

A GUARD THAT NEVER FIRES REPORTS EXACTLY WHAT A CLEAN TREE REPORTS, so nothing here asserts only that
a scan came back empty: every arm is planted against, in both directions, over a real tree on disk.
The readers are driven THROUGH the published surface rather than re-implemented, which is what makes
these controls rather than a second copy agreeing with the first.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from lab_commons.dev import floors
from lab_commons.dev.famtests.citedtests import (
    CitedScan,
    DanglingCitation,
    VacuousExemption,
    assert_every_exemption_is_real,
    assert_no_dangling_function_citation,
    assert_no_dangling_path_citation,
    assert_the_prose_half_is_reached,
    assert_the_readers_still_convict,
    comment_blocks,
    defined_test_functions,
    defined_test_modules,
    docstring_citation_count,
    prose_lines,
    resolves,
    scanned_files,
    take_scan,
)

_MARKERS = ('was DELETED', 'Split out of ')
_VOCABULARY = frozenset({'test_files', 'test_module'})
_WALK = {
    'pointer_dirs': ('src',),
    'root_configs': ('ruff.toml',),
    'waiver_header': 'ratcheted by',
    'waiver_dirs': ('tests',),
    'test_dir': 'tests',
    'history_keepers': (),
    'history_markers': _MARKERS,
    'not_citations': _VOCABULARY,
}


def _tree(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')


def test_prose_lines_read_comments_AND_docstrings_and_stop_at_code_strings(tmp_path: Path) -> None:
    """The scope claim, measured: a docstring is prose addressed to a human; a string literal is data."""
    path = tmp_path / 'm.py'
    path.write_text(
        '"""A module docstring line.\n\nA second line.\n"""\n# a comment\nX = "a plain string"\n\n\ndef f():\n'
        '    """A function docstring."""\n',
        encoding='utf-8',
    )
    read = dict(prose_lines(path))
    assert read[5] == '# a comment'
    assert read[1].startswith('"""A module docstring')
    assert 6 not in read, 'a plain string literal is DATA and must not be read as prose'
    assert read[10] == '"""A function docstring."""'


def test_prose_lines_keep_the_comments_of_a_file_that_does_not_parse(tmp_path: Path) -> None:
    """A syntax error costs the docstrings and must not cost the whole file -- the walk keeps going."""
    path = tmp_path / 'broken.py'
    path.write_text('# see tests/unit/test_x.py\ndef (:\n', encoding='utf-8')
    assert dict(prose_lines(path)) == {1: '# see tests/unit/test_x.py'}


def test_comment_blocks_join_a_run_and_break_on_a_gap() -> None:
    """Block granularity is what lets a marker on one line excuse a name on the next."""
    blocks = comment_blocks([(1, '# a'), (2, '# b'), (7, '# c')])
    assert [text for _, text in blocks] == ['# a # b', '# c']
    assert [sorted(nums) for nums, _ in blocks] == [[1, 2], [7]]


def test_a_history_marker_excuses_its_own_SENTENCE_and_not_the_whole_block(tmp_path: Path) -> None:
    """THE CORRECTION THAT MATTERS: a block-wide exemption silenced a LIVE pointer next to it."""
    _tree(
        tmp_path,
        {
            'tests/test_seed.py': 'def test_something_real():\n    assert True\n',
            'src/a.py': (
                '# test_the_old_name was DELETED in the consolidation.\n# Pinned by test_a_live_but_missing_guard.\n'
            ),
        },
    )
    scan = take_scan(tmp_path, **_WALK)
    assert scan.dangling_functions == ('src/a.py:1 -> test_a_live_but_missing_guard',), (
        'the marker must excuse only the sentence it sits in -- a block-wide exemption is how a live '
        'pointer three lines down stops being reported'
    )


def test_the_vocabulary_set_removes_a_shape_and_not_a_real_citation(tmp_path: Path) -> None:
    """Both directions of ``not_citations``: the word goes, the citation beside it stays."""
    _tree(
        tmp_path,
        {
            'tests/test_seed.py': 'def test_something_real():\n    assert True\n',
            'src/a.py': '# every test_module here, and test_a_guard_that_is_gone.\n',
        },
    )
    assert take_scan(tmp_path, **_WALK).dangling_functions == ('src/a.py:1 -> test_a_guard_that_is_gone',)


def test_resolution_takes_a_stem_a_prefix_and_a_suffix_and_refuses_a_stranger() -> None:
    """The deliberate weakening, pinned so it cannot widen further without this test moving."""
    defined = frozenset({'test_the_march_dissipates_and_the_loss_waveform_is_read'})
    modules = frozenset({'test_backend_table'})
    assert resolves('test_backend_table', defined=defined, modules=modules)
    assert resolves('test_backend_table.py', defined=defined, modules=modules)
    assert resolves('test_the_march_dissipates_and_the_loss', defined=defined, modules=modules)
    assert resolves('waveform_is_read', defined=defined, modules=modules), 'a wrap can fall on either side'
    assert not resolves('test_no_such_guard_at_all', defined=defined, modules=modules)


def test_the_walk_takes_the_declared_roots_the_configs_and_a_waiver_header_anywhere(tmp_path: Path) -> None:
    """Three populations, and the waiver header is the one that reaches INTO the test tree."""
    _tree(
        tmp_path,
        {
            'src/a.py': 'X = 1\n',
            'src/__pycache__/a.py': 'X = 1\n',
            'other/b.py': 'X = 1\n',
            'ruff.toml': 'line-length = 120\n',
            'tests/test_headed.py': '# the population is ratcheted by tests/test_x.py\n',
            'tests/test_plain.py': 'def test_plain():\n    assert True\n',
        },
    )
    found = {
        p.relative_to(tmp_path).as_posix()
        for p in scanned_files(
            tmp_path,
            pointer_dirs=('src',),
            root_configs=('ruff.toml', 'absent.toml'),
            waiver_header='ratcheted by',
            waiver_dirs=('tests',),
        )
    }
    assert found == {'src/a.py', 'ruff.toml', 'tests/test_headed.py'}


def test_the_defined_sets_read_functions_and_stems_separately(tmp_path: Path) -> None:
    _tree(
        tmp_path,
        {
            'tests/test_one.py': 'def test_alpha():\n    pass\n\n\nasync def test_beta():\n    pass\n',
            'tests/helper.py': 'def test_gamma():\n    pass\n',
        },
    )
    assert defined_test_functions(tmp_path, test_dir='tests') == {'test_alpha', 'test_beta', 'test_gamma'}
    assert defined_test_modules(tmp_path, test_dir='tests') == {'test_one'}


def test_the_docstring_counter_sees_prose_and_not_comments(tmp_path: Path) -> None:
    """The second floor's reading: it must be blind to the population the first floor already counts."""
    _tree(tmp_path, {'src/a.py': '"""See tests/unit/test_x.py."""\n# and test_a_comment_citation\n'})
    files = [tmp_path / 'src' / 'a.py']
    assert docstring_citation_count(files) == 1


def test_the_planted_control_convicts_through_the_shipped_readers(tmp_path: Path) -> None:
    """The control a CONSUMER runs, driven here so a regression in it cannot wait for a consumer."""
    assert_the_readers_still_convict(tmp_path, history_markers=_MARKERS, not_citations=_VOCABULARY)


def test_a_clean_tree_passes_every_arm(tmp_path: Path) -> None:
    """The other side of the ratchet: the arms must not simply refuse everything they are shown."""
    _tree(
        tmp_path,
        {
            'tests/test_seed.py': 'def test_something_real():\n    assert True\n',
            'src/a.py': '"""Guarded by tests/test_seed.py."""\n# and by test_something_real\n',
            'ruff.toml': 'line-length = 120\n',
        },
    )
    scan = take_scan(tmp_path, **_WALK)
    assert_no_dangling_path_citation(scan, floor=2, headroom=4)
    assert_no_dangling_function_citation(scan, floor=1, headroom=4)
    assert_the_prose_half_is_reached(scan, floor=1, headroom=4)


def test_each_arm_raises_its_own_exception_on_a_planted_offender(tmp_path: Path) -> None:
    _tree(
        tmp_path,
        {
            'tests/test_seed.py': 'def test_something_real():\n    assert True\n',
            'src/a.py': '# guarded by tests/test_gone.py and by test_a_guard_that_is_gone\n',
        },
    )
    scan = take_scan(tmp_path, **_WALK)
    with pytest.raises(DanglingCitation, match=re.escape('tests/test_gone.py')):
        assert_no_dangling_path_citation(scan, floor=1, headroom=4)
    with pytest.raises(DanglingCitation, match='test_a_guard_that_is_gone'):
        assert_no_dangling_function_citation(scan, floor=1, headroom=4)


@pytest.mark.parametrize(
    ('arm', 'field'),
    [
        (assert_no_dangling_path_citation, 'files_read'),
        (assert_no_dangling_function_citation, 'functions_defined'),
        (assert_the_prose_half_is_reached, 'prose_citations'),
    ],
)
def test_every_arm_binds_BOTH_sides_of_its_own_floor(arm, field: str) -> None:
    """Three arms, three DIFFERENT populations -- and a floor that stops binding is the missing side."""
    empty = CitedScan(files_read=0, functions_defined=0, prose_citations=0, dangling_paths=(), dangling_functions=())
    with pytest.raises(floors.FloorUnmet):
        arm(empty, floor=5, headroom=4)
    outgrown = CitedScan(
        files_read=500,
        functions_defined=500,
        prose_citations=500,
        dangling_paths=(),
        dangling_functions=(),
    )
    with pytest.raises(floors.SlackFloor):
        arm(outgrown, floor=5, headroom=4)
    assert field in vars(outgrown), 'the arm must judge the population this row names'


def test_an_exemption_naming_a_deleted_file_is_refused_and_a_real_one_is_not(tmp_path: Path) -> None:
    """A waiver nothing uses is as wrong as a capability that disappears, and it never announces itself."""
    _tree(tmp_path, {'src/keeper.py': '# a dated log\n'})
    assert_every_exemption_is_real(tmp_path, history_keepers=('src/keeper.py',))
    with pytest.raises(VacuousExemption, match=re.escape('src/gone.py')):
        assert_every_exemption_is_real(tmp_path, history_keepers=('src/keeper.py', 'src/gone.py'))


def test_a_history_keeper_is_skipped_by_BOTH_arms(tmp_path: Path) -> None:
    """One exemption list, two scans -- a keeper exempt from one arm and not the other is a half-rule."""
    _tree(
        tmp_path,
        {
            'tests/test_seed.py': 'def test_something_real():\n    assert True\n',
            'src/retired.py': '# tests/test_gone.py held this, and test_a_guard_that_is_gone before it\n',
        },
    )
    scan = take_scan(tmp_path, **{**_WALK, 'history_keepers': ('src/retired.py',)})
    assert scan.dangling_paths == ()
    assert scan.dangling_functions == ()
