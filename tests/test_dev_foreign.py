"""PLANTED CONTROLS for the foreign-data scan: every refusal is driven through the REAL arm.

A scope claim needs its own test -- one that PLANTS the thing in the region and calls the REAL
guard. So nothing here re-implements the classification: each case writes a real module into a
temporary tree, runs :func:`lab_commons.dev.foreign.scan` over it, and asserts on what came back.

The live reading over this repo is the OTHER file, `test_the_leaf_carries_no_foreign_data.py`. That
one can go green because the tree is clean; these cannot, because the hazard is planted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lab_commons.dev.floors import FloorUnmet
from lab_commons.dev.foreign import (
    DATA,
    PATH,
    PROSE,
    ForeignData,
    StaleWaiver,
    assert_no_foreign_data,
    assert_prose_is_falling,
    classify_text,
    is_unresolved_path,
    kinds,
    modules_read,
    scan,
)

SIBLINGS = ('motronics-studio', 'wdg-lab', 'optimi-lab', 'motronics')


def _tree(root: Path, name: str, body: str) -> Path:
    src = root / 'src' / 'pkg'
    src.mkdir(parents=True, exist_ok=True)
    (src / name).write_text(body, encoding='utf-8')
    return src


def _scan(root: Path, src: Path) -> tuple:
    return scan(src, repo_root=root, siblings=SIBLINGS, exclude=())


def test_the_longest_spelling_wins_so_a_finding_names_the_right_tree() -> None:
    """``motronics`` is a prefix of ``motronics-studio``; a misnamed finding sends a reader wrong."""
    assert classify_text('rows for motronics-studio', SIBLINGS) == 'motronics-studio'
    assert classify_text('motronics only', SIBLINGS) == 'motronics'
    assert classify_text('nothing here', SIBLINGS) is None


def test_a_unit_and_a_mime_type_are_path_shaped_and_are_not_paths(tmp_path: Path) -> None:
    """THE EXTENSION IS LOAD-BEARING: without it the reading swallows `A/m` and `application/json`."""
    for text in ('A/m', 'rad/s', 'application/json', 'refs/remotes/origin', 'feat/second'):
        assert not is_unresolved_path(text, tmp_path), text


def test_a_path_that_resolves_here_is_not_foreign(tmp_path: Path) -> None:
    """The definition is DOES NOT RESOLVE, so a file that exists is never reported."""
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests' / 'test_x.py').write_text('', encoding='utf-8')
    assert not is_unresolved_path('tests/test_x.py', tmp_path)
    assert is_unresolved_path('tests/test_gone.py', tmp_path)


def test_a_template_and_a_glob_are_not_read(tmp_path: Path) -> None:
    """A brace or a star names a SHAPE, so "does it resolve" is not a question about it."""
    assert not is_unresolved_path('tests/{name}/test_x.py', tmp_path)
    assert not is_unresolved_path('tests/*/test_x.py', tmp_path)


def test_a_parent_escape_is_not_read(tmp_path: Path) -> None:
    """``../bin/bash.exe`` is a relative launcher spelling, not a mechanism in another repo."""
    assert not is_unresolved_path('../bin/bash.exe', tmp_path)


def test_the_three_kinds_are_told_apart(tmp_path: Path) -> None:
    """THE WHOLE CLAIM, planted: a docstring, a short value and an unresolvable path in one module."""
    src = _tree(
        tmp_path,
        'm.py',
        '"""A docstring naming wdg-lab."""\n\nREPO = "optimi-lab"\nMECH = "tests/architecture/gone.py"\n',
    )
    found = _scan(tmp_path, src)
    assert [f.kind for f in found] == [PROSE, DATA, PATH]
    assert kinds(found, DATA)[0].sibling == 'optimi-lab'
    assert kinds(found, PROSE)[0].sibling == 'wdg-lab'


def test_a_sentence_in_executable_position_is_prose(tmp_path: Path) -> None:
    """A row's ``why=`` is a paragraph explaining a decision -- prose by SUBJECT, wherever it sits."""
    sentence = 'x' * 130 + ' motronics-studio'
    src = _tree(tmp_path, 'm.py', f'WHY = {sentence!r}\n')
    assert [f.kind for f in _scan(tmp_path, src)] == [PROSE]


def test_a_comment_is_prose(tmp_path: Path) -> None:
    """Comments are read too, or the cheapest place to hide a sibling name would be unscanned."""
    src = _tree(tmp_path, 'm.py', '# a note about wdg-lab\nX = 1\n')
    assert [f.kind for f in _scan(tmp_path, src)] == [PROSE]


def test_an_excluded_module_is_not_read(tmp_path: Path) -> None:
    """The registry of the violation cannot record who the siblings are without spelling them."""
    src = _tree(tmp_path, 'rows.py', 'REPO = "wdg-lab"\n')
    assert scan(src, repo_root=tmp_path, siblings=SIBLINGS, exclude=('src/pkg/rows.py',)) == ()
    assert modules_read(src, ('src/pkg/rows.py',), tmp_path) == 0


def test_the_handle_is_module_and_kind(tmp_path: Path) -> None:
    """One waiver per module per kind: a line number moves, and a module alone admits a new kind."""
    src = _tree(tmp_path, 'm.py', 'REPO = "wdg-lab"\n')
    assert _scan(tmp_path, src)[0].handle == 'src/pkg/m.py::data'


def test_an_unwaived_finding_reds(tmp_path: Path) -> None:
    """THE HIGH SIDE: nothing new arrives under the waiver set."""
    src = _tree(tmp_path, 'm.py', 'REPO = "wdg-lab"\n')
    with pytest.raises(ForeignData, match='nothing has evicted'):
        assert_no_foreign_data(_scan(tmp_path, src), evicted={}, synthetic={}, read=99, floor=1)


def test_a_waived_finding_passes(tmp_path: Path) -> None:
    """The waiver is what makes this pass non-breaking: the row still runs, and it is NAMED."""
    src = _tree(tmp_path, 'm.py', 'REPO = "wdg-lab"\n')
    assert_no_foreign_data(
        _scan(tmp_path, src),
        evicted={'src/pkg/m.py::data': 'blocked on the consumer'},
        synthetic={},
        read=99,
        floor=1,
    )


def test_a_waiver_whose_row_is_gone_reds(tmp_path: Path) -> None:
    """THE OTHER SIDE, and it is what makes the later deletion mechanical rather than optional."""
    src = _tree(tmp_path, 'm.py', 'X = 1\n')
    with pytest.raises(StaleWaiver, match='no longer finds'):
        assert_no_foreign_data(
            _scan(tmp_path, src),
            evicted={'src/pkg/m.py::data': 'blocked on the consumer'},
            synthetic={},
            read=99,
            floor=1,
        )


def test_a_synthetic_waiver_is_honoured_and_is_also_two_sided(tmp_path: Path) -> None:
    """The second mapping means the same to the arm and something different to a reader."""
    src = _tree(tmp_path, 'm.py', 'EXAMPLE = "tests/a/test_fast.py"\n')
    assert_no_foreign_data(
        _scan(tmp_path, src), evicted={}, synthetic={'src/pkg/m.py::path': 'a worked example'}, read=99, floor=1
    )
    clean = _tree(tmp_path / 'other', 'm.py', 'X = 1\n')
    with pytest.raises(StaleWaiver):
        assert_no_foreign_data(
            scan(clean, repo_root=tmp_path / 'other', siblings=SIBLINGS, exclude=()),
            evicted={},
            synthetic={'src/pkg/m.py::path': 'a worked example'},
            read=99,
            floor=1,
        )


def test_a_scan_that_read_nothing_is_inconclusive_rather_than_clean() -> None:
    """Finding NOTHING over an unread tree reports exactly what a clean tree reports."""
    with pytest.raises(FloorUnmet):
        assert_no_foreign_data((), evicted={}, synthetic={}, read=3, floor=80)


def test_the_prose_ceiling_refuses_growth_and_demands_a_re_measure() -> None:
    """BOTH SIDES of the ceiling: it may not be exceeded, and it may not sit above its reading."""
    assert_prose_is_falling(10, ceiling=10)
    with pytest.raises(ForeignData, match='above the'):
        assert_prose_is_falling(11, ceiling=10)
    with pytest.raises(ForeignData, match='RE-MEASURE'):
        assert_prose_is_falling(9, ceiling=10)
