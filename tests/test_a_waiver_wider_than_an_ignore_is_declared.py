"""THE TWO WAIVERS THAT ARE WIDER THAN AN IGNORE: the kit's reader, its refusal, and the kit's own rows.

``exclude`` drops every selector over a subtree and names no code; ``per-file-ignores`` drops a named
code over a glob. Every arm stated over the GLOBAL ignore list is blind to both, which is why
:mod:`lab_commons.dev.ruffwaivers` exists.

WHAT THIS FILE NO LONGER DOES, AND WHY. It used to read three sibling checkouts and hold their rows
under neutral names, which made this public tree carry facts about repos it does not own -- and those
facts went stale against the real trees, because the names were not theirs. Each consumer now
declares its own excludes and per-file waivers, with real names, in its own tests, and calls
:func:`~lab_commons.dev.ruffwaivers.assert_waivers_declared`. What stays here is the MECHANISM, driven
by planted controls, and the kit's own rows judged by the same call a consumer makes.

THE AXIS THE CONTROLS ARE PARAMETRIZED OVER IS SPELLING, not repos: ruff honours ``lint.extend-ignore``
and a deprecated top-level ``ignore`` as well, so a reader of one spelling would empty the reading the
day an entry moved across spellings while changing nothing ruff does.

THE RATCHET HAS TWO SIDES, mechanised rather than described: a row that is not declared reds NAMED,
and a declared row no live config needs reds too.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest
from _config_census_rows import KIT_PER_FILE_WAIVERS

from lab_commons.dev.floors import FloorUnmet, SlackFloor, assert_floor, assert_floor_still_binds
from lab_commons.dev.ruffwaivers import (
    MACHINE_EXCLUDES,
    UndeclaredWaiverError,
    WaiverKindError,
    assert_waivers_declared,
    ruff_config,
    ruff_waivers,
    waiver_drift,
    waiver_entries,
)

#: The tree under verification: its WORKING TREE is the authority for its own rows.
ROOT: Final = Path(__file__).resolve().parents[1]

#: THE KIT'S OWN per-file waivers. MEASURED 2026-09-18 at 10 rows, all of them `tests/**`. Band
#: [8, 12]: a reader that returned nothing reds on the low side, and the kit's own escape hatch growing
#: past twelve reds on the high side with the remedy being to re-measure rather than to widen.
KIT_WAIVER_FLOOR: Final[int] = 8
KIT_WAIVER_HEADROOM: Final[int] = 4


def _plant(tmp_path: Path, text: str) -> Path:
    (tmp_path / 'pyproject.toml').write_text(text, encoding='utf-8')
    return tmp_path


# ------------------------------------------------------------------------- the kit's own rows


def test_the_kit_excludes_nothing_which_is_what_makes_the_zero_reachable() -> None:
    """A ceiling over a consumer's excludes is only a ceiling if zero is attainable -- and here it is.

    Stated with NO machine subtraction: the repo that ships the standard opens every file it tracks.
    """
    assert assert_waivers_declared(ROOT, 'exclude', ()) == frozenset()


def test_every_per_file_waiver_the_kit_holds_is_a_declared_row() -> None:
    """The kit's rows, judged by exactly the call a consumer makes over its own -- both sides."""
    assert assert_waivers_declared(ROOT, 'per-file-ignores', KIT_PER_FILE_WAIVERS) == frozenset(KIT_PER_FILE_WAIVERS)


def test_the_kits_own_per_file_waivers_still_bind_their_floor() -> None:
    """The floor under the kit's own rows, BOTH SIDES."""
    found = len(ruff_waivers(ROOT, 'per-file-ignores', at_head=False))
    what = "lab-commons' own ruff per-file waiver"
    assert_floor(found, floor=KIT_WAIVER_FLOOR, what=what)
    assert_floor_still_binds(found, floor=KIT_WAIVER_FLOOR, headroom=KIT_WAIVER_HEADROOM, what=what)


def test_the_resolved_config_is_what_is_read_so_the_arms_do_not_care_which_file_holds_it(tmp_path: Path) -> None:
    """A ``ruff.toml`` beside a ``pyproject.toml`` WINS, as it does for ruff itself."""
    _plant(tmp_path, '[tool.ruff]\nexclude = ["loser"]\n')
    (tmp_path / 'ruff.toml').write_text('exclude = ["winner"]\n', encoding='utf-8')
    assert ruff_waivers(tmp_path, 'exclude', at_head=False) == frozenset({'winner'})
    assert ruff_config(ROOT, at_head=False), 'the kit`s own resolved ruff config read EMPTY'


# ------------------------------------------------------------------------------ planted controls


#: Every row is a config ruff honours that a one-spelling reader would not see.
_SPELLING_CONTROLS: Final[tuple[tuple[str, dict, str], ...]] = (
    ('ignore', {'lint': {'ignore': ['E501']}}, 'E501'),
    ('ignore', {'lint': {'extend-ignore': ['E501']}}, 'E501'),
    ('ignore', {'ignore': ['E501']}, 'E501'),
    ('ignore', {'extend-ignore': ['E501']}, 'E501'),
    ('select', {'lint': {'extend-select': ['ANN']}}, 'ANN'),
    ('select', {'select': ['ANN']}, 'ANN'),
    ('exclude', {'exclude': ['attic']}, 'attic'),
    ('exclude', {'extend-exclude': ['attic']}, 'attic'),
    ('exclude', {'lint': {'exclude': ['attic']}}, 'attic'),
    ('exclude', {'format': {'extend-exclude': ['attic']}}, 'attic'),
    ('per-file-ignores', {'lint': {'per-file-ignores': {'tests/**': ['S101']}}}, 'tests/**::S101'),
    ('per-file-ignores', {'lint': {'extend-per-file-ignores': {'tests/**': ['S101']}}}, 'tests/**::S101'),
    ('per-file-ignores', {'per-file-ignores': {'tests/**': ['S101']}}, 'tests/**::S101'),
)


@pytest.mark.parametrize(('kind', 'config', 'entry'), _SPELLING_CONTROLS)
def test_the_reader_is_driven_over_spellings(kind: str, config: dict, entry: str) -> None:
    """PLANTED CONTROL, THROUGH THE READER A CONSUMER CALLS. Each spelling must be SEEN."""
    assert entry in waiver_entries(config, kind), f'{kind} written as {config} read empty'


@pytest.mark.parametrize('key', ['force-exclude', 'respect-gitignore', 'preview', 'line-length'])
def test_a_key_that_is_not_a_waiver_is_not_read_as_one(key: str) -> None:
    """THE OTHER SIDE: `force-exclude` contains the word and is a BOOLEAN, not an exclude."""
    assert waiver_entries({key: True, 'lint': {}}, 'exclude') == frozenset()
    assert waiver_entries({key: True, 'lint': {}}, 'per-file-ignores') == frozenset()


def test_an_undeclared_waiver_is_NAMED_by_the_refusal_and_not_merely_counted(tmp_path: Path) -> None:
    """THE REFUSAL, PLANTED, through the real call: machine excludes subtracted, the real one named."""
    root = _plant(tmp_path, '[tool.ruff]\nexclude = ["attic", ".git", "src/secret_tree"]\n')
    with pytest.raises(UndeclaredWaiverError, match=r"\['src/secret_tree'\] that no row declares"):
        assert_waivers_declared(root, 'exclude', ('attic',), machine=MACHINE_EXCLUDES)
    assert assert_waivers_declared(root, 'exclude', ('attic', 'src/secret_tree'), machine=MACHINE_EXCLUDES)


def test_a_declared_row_no_live_config_needs_is_NAMED_by_the_other_side(tmp_path: Path) -> None:
    """THE SHRINK, PLANTED: a config that gave a waiver up, read against rows that still declare it."""
    root = _plant(tmp_path, '[tool.ruff.lint.per-file-ignores]\n"examples/**" = ["T201"]\n')
    with pytest.raises(UndeclaredWaiverError, match=r"declare \['scripts/\*\.py::T201'\] that no live config"):
        assert_waivers_declared(root, 'per-file-ignores', ('examples/**::T201', 'scripts/*.py::T201'))
    assert waiver_drift({'a', 'b'}, {'b', 'c'}) == (('a',), ('c',))


def test_a_reader_that_went_silent_reds_on_the_low_side_and_a_stale_floor_on_the_high() -> None:
    """BOTH SIDES OF THE FLOOR, PLANTED, through the same `dev.floors` calls the arm makes."""
    what = 'planted waiver'
    with pytest.raises(FloorUnmet):
        assert_floor(0, floor=KIT_WAIVER_FLOOR, what=what)
    with pytest.raises(SlackFloor):
        assert_floor_still_binds(
            KIT_WAIVER_FLOOR + KIT_WAIVER_HEADROOM + 1, floor=KIT_WAIVER_FLOOR, headroom=KIT_WAIVER_HEADROOM, what=what
        )
    assert_floor(KIT_WAIVER_FLOOR, floor=KIT_WAIVER_FLOOR, what=what)


def test_a_waiver_kind_the_table_does_not_declare_is_refused_rather_than_read_empty() -> None:
    """An unsupported kind RAISES. Returning an empty set would make a typo read as a clean config."""
    with pytest.raises(WaiverKindError, match='not a declared waiver kind'):
        waiver_entries({'lint': {'ignore': ['E501']}}, 'ignores')
