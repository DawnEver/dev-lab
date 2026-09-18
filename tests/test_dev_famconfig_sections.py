r"""The SECTION-scoped family base: it owns one TOML table and leaves the rest of the file alone.

WHY THIS FILE EXISTS RATHER THAN A ROW IN `test_dev_famconfig.py`. `famconfig`'s base is a WHOLE
FILE keyed by FILENAME, and MEASURED 2026-09-18 against the live kit `artefact_base('[tool.ruff]')`,
`artefact_base('ruff.toml')` and `artefact_base('pyproject.toml')` all raise `ForkedDelta`. Pointing
the whole-file mechanism at `pyproject.toml` is not the workaround either: `RENDERED` would then
demand the base own `[build-system]`, `[project]` and every other table in that file. So the ruff arm
needs a base whose SUBJECT is a table.

THE TWO CONTROLS THIS ARM IS FOR, and they are the reason `REQUIRED` mode could not serve. `REQUIRED`
asserts PRESENCE, so it is blind in both directions that matter here:

* `test_planted_a_consumer_adding_an_ignore_entry_reds` -- an undeclared waiver appearing in a
  consumer's ignore list is the whole point of the arm, and a presence check cannot see an ADDITION;
* `test_planted_a_consumer_dropping_a_selector_reds` -- the other side of the ratchet, and the one
  R1 spent a sweep establishing.

Both drive `inspect_section` over a planted file, and the clean control beside them
(`test_a_declared_delta_is_owned`) proves the same function can still pass, so neither is vacuous.

THE FILE IS NOT THE ARTEFACT, which is the second decision this arm carries. motronics keeps its
rules in `ruff.toml`; the other three keep `[tool.ruff]*` inside `pyproject.toml`. A base keyed by
filename cannot serve both, and the kit already declared that the PATH is per-repo data twice --
`lab_commons.dev.profile.DEFAULT_LINT_CONFIG` and `lab_commons.dev.rules.lint_selection`, which reads
both shapes on purpose. So this base is keyed by the TABLE and resolves the file, and
`test_both_spellings_resolve_to_the_same_table` pins that both ways.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Final

import pytest

from lab_commons.dev._famconfig_ruff_rows import (
    RUFF_IGNORE_CORE,
    RUFF_LINE_LENGTH,
    RUFF_SECTION_PREFIX,
    RUFF_SELECT,
    RUFF_SELECT_FLOOR,
    RUFF_TARGET_VERSIONS,
)
from lab_commons.dev.famconfig import (
    DIVERGED,
    NO_FILE,
    NO_TABLE,
    OWNED,
    AmbiguousSection,
    ForkedSectionDelta,
    SectionBase,
    SectionDelta,
    VacuousBase,
    expected_entries,
    inspect_section,
    locate_section,
    ruff_config_path,
    ruff_section_base,
    section_problems,
)

#: The kit's OWN delta against the ruff section base: EMPTY, and that is the measurement rather than
#: the default. lab-commons selects the family 58, ignores exactly the 10-code core, and sets
#: `line-length = 120` -- so there is nothing to add and nothing to drop. Declared here rather than
#: in `tests/_famconfig_delta.py` because that module is the WHOLE-FILE deltas and this is a section.
KIT_DELTA: Final = SectionDelta(repo='lab-commons', added={}, dropped={}, ceiling=0)

#: A planted lint section: the smallest base that can carry both controls. Two set-valued keys and
#: one scalar, which is the shape of the real `[tool.ruff.lint]` without its 58 rows.
PLANTED: Final = SectionBase(
    artefact='[tool.plant.lint]',
    table=('tool', 'plant', 'lint'),
    prefix=('tool', 'plant'),
    scalars={'line-length': 120},
    sets={'select': ('E', 'F'), 'ignore': ('E501',)},
)

#: What a repo with one extra waiver declares. The ceiling is the measurement, stated.
PLANTED_DELTA: Final = SectionDelta(repo='planted', added={'ignore': ('D203',)}, dropped={}, ceiling=1)


def _write(tmp_path: Path, body: str, *, name: str = 'pyproject.toml') -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(body).lstrip(), encoding='utf-8')
    return path


def _clean_file(tmp_path: Path, *, ignore: str = '"E501", "D203"', select: str = '"E", "F"') -> Path:
    return _write(
        tmp_path,
        f"""
        [project]
        name = "planted"

        [tool.plant.lint]
        line-length = 120
        select = [{select}]
        ignore = [{ignore}]
        """,
    )


# ------------------------------------------------------------------ the two controls the arm is for


def test_a_declared_delta_is_owned(tmp_path: Path) -> None:
    """THE CLEAN CONTROL. Base plus the declared delta, and nothing else, reads OWNED."""
    report = inspect_section(_clean_file(tmp_path), PLANTED, PLANTED_DELTA)
    assert report.status == OWNED, (report.status, report.detail, report.offending)
    assert report.ok


def test_planted_a_consumer_adding_an_ignore_entry_reds(tmp_path: Path) -> None:
    """THE CONTROL `REQUIRED` COULD NOT GIVE: an undeclared waiver in the ignore list is named."""
    path = _clean_file(tmp_path, ignore='"E501", "D203", "S101"')
    report = inspect_section(path, PLANTED, PLANTED_DELTA)
    assert report.status == DIVERGED, report.detail
    assert any('S101' in line and 'ignore' in line for line in report.offending), report.offending


def test_planted_a_consumer_dropping_a_selector_reds(tmp_path: Path) -> None:
    """THE OTHER SIDE. A base selector gone with no declared drop is named."""
    path = _clean_file(tmp_path, select='"E"')
    report = inspect_section(path, PLANTED, PLANTED_DELTA)
    assert report.status == DIVERGED, report.detail
    assert any("'F'" in line and 'select' in line for line in report.offending), report.offending


def test_a_drop_with_a_reason_makes_the_same_file_owned(tmp_path: Path) -> None:
    """THE RATCHET'S OTHER SIDE: a removal is legal only through a declaration that says why."""
    path = _clean_file(tmp_path, select='"E"')
    delta = SectionDelta(
        repo='planted',
        added={'ignore': ('D203',)},
        dropped={('select', 'F'): 'MEASURED: this tree has no f-string rule subject'},
        ceiling=1,
    )
    assert inspect_section(path, PLANTED, delta).status == OWNED


def test_planted_a_changed_scalar_reds(tmp_path: Path) -> None:
    """A scalar the base owns is EXACT -- a repo that widened its line length is named, not waived."""
    path = _write(
        tmp_path,
        """
        [tool.plant.lint]
        line-length = 200
        select = ["E", "F"]
        ignore = ["E501", "D203"]
        """,
    )
    report = inspect_section(path, PLANTED, PLANTED_DELTA)
    assert report.status == DIVERGED
    assert any('line-length' in line for line in report.offending), report.offending


# ------------------------------------------------------------------------------- the file questions


def test_the_section_mechanism_leaves_the_rest_of_the_file_alone(tmp_path: Path) -> None:
    """THE DELIVERABLE'S DEFINING PROPERTY. Tables the base does not name are not its business."""
    path = _write(
        tmp_path,
        """
        [build-system]
        requires = ["hatchling"]

        [project]
        name = "planted"

        [tool.pyright]
        strict = ["src"]

        [tool.plant.lint]
        line-length = 120
        select = ["E", "F"]
        ignore = ["E501", "D203"]

        [tool.plant.format]
        quote-style = "double"
        """,
    )
    assert inspect_section(path, PLANTED, PLANTED_DELTA).status == OWNED


def test_both_spellings_resolve_to_the_same_table(tmp_path: Path) -> None:
    """A dedicated config file drops the prefix, and the base binds on BOTH -- measured, not assumed."""
    dedicated = _write(
        tmp_path,
        """
        [lint]
        line-length = 120
        select = ["E", "F"]
        ignore = ["E501", "D203"]
        """,
        name='plant.toml',
    )
    assert inspect_section(dedicated, PLANTED, PLANTED_DELTA).status == OWNED


def test_a_file_declaring_the_table_twice_is_refused(tmp_path: Path) -> None:
    """Two spellings of one decision is the dead-block shape, and only one of them is ever read."""
    path = _write(
        tmp_path,
        """
        [lint]
        select = ["E"]

        [tool.plant.lint]
        select = ["E", "F"]
        """,
        name='plant.toml',
    )
    with pytest.raises(AmbiguousSection, match='both'):
        inspect_section(path, PLANTED, PLANTED_DELTA)


def test_a_missing_file_and_a_missing_table_are_different_answers(tmp_path: Path) -> None:
    """ABSENT is not UNCHECKED, and a file with no such table is not a file that is not there."""
    assert inspect_section(tmp_path / 'nope.toml', PLANTED, PLANTED_DELTA).status == NO_FILE
    empty = _write(tmp_path, '[project]\nname = "planted"\n')
    assert inspect_section(empty, PLANTED, PLANTED_DELTA).status == NO_TABLE


def test_ruff_config_path_takes_ruffs_own_precedence(tmp_path: Path) -> None:
    """`ruff.toml` WINS over `pyproject.toml`, both ways, and an empty tree raises rather than guesses."""
    (tmp_path / 'pyproject.toml').write_text('[project]\nname = "x"\n', encoding='utf-8')
    assert ruff_config_path(tmp_path).name == 'pyproject.toml'
    (tmp_path / 'ruff.toml').write_text('line-length = 120\n', encoding='utf-8')
    assert ruff_config_path(tmp_path).name == 'ruff.toml'
    with pytest.raises(FileNotFoundError, match='no ruff config'):
        ruff_config_path(tmp_path / 'elsewhere')


# --------------------------------------------------------------------------- the declaration refusals


def test_a_delta_that_restates_a_base_entry_is_refused() -> None:
    """A delta re-stating the base is the base copied where re-checking no longer guards it."""
    delta = SectionDelta(repo='planted', added={'ignore': ('E501',)}, dropped={}, ceiling=1)
    problems = section_problems(PLANTED, delta)
    assert any('already' in p and 'E501' in p for p in problems), problems


def test_a_delta_past_its_ceiling_is_refused() -> None:
    """An escape hatch needs a CEILING, and the ceiling counts every key's entries together."""
    delta = SectionDelta(repo='planted', added={'ignore': ('D203', 'D400')}, dropped={}, ceiling=1)
    assert any('ceiling' in p for p in section_problems(PLANTED, delta)), section_problems(PLANTED, delta)


def test_a_drop_whose_subject_the_base_lacks_is_refused() -> None:
    """A stale declaration cannot outlive its subject -- the ratchet the whole-file base already has."""
    delta = SectionDelta(repo='planted', added={}, dropped={('select', 'W'): 'gone'}, ceiling=0)
    assert any("'W'" in p for p in section_problems(PLANTED, delta)), section_problems(PLANTED, delta)
    stale = SectionDelta(repo='planted', added={}, dropped={('preview', None): 'gone'}, ceiling=0)
    assert any('preview' in p for p in section_problems(PLANTED, stale))


def test_an_addition_to_a_key_the_base_does_not_own_is_refused() -> None:
    """The base owns named KEYS; a delta cannot legislate one it never declared."""
    delta = SectionDelta(repo='planted', added={'exclude': ('attic',)}, dropped={}, ceiling=1)
    assert any('exclude' in p for p in section_problems(PLANTED, delta)), section_problems(PLANTED, delta)


def test_an_empty_reason_and_an_empty_addition_are_both_refused() -> None:
    """A removal and a drift are the same bytes; and an addition that adds nothing is an unused waiver."""
    silent = SectionDelta(repo='planted', added={}, dropped={('select', 'F'): '   '}, ceiling=0)
    assert any('reason' in p for p in section_problems(PLANTED, silent))
    hollow = SectionDelta(repo='planted', added={'ignore': ()}, dropped={}, ceiling=0)
    assert any('nothing' in p for p in section_problems(PLANTED, hollow))


def test_a_refused_delta_raises_rather_than_reporting_a_status(tmp_path: Path) -> None:
    """An illegal declaration is not a file verdict: it is refused before the file is read."""
    delta = SectionDelta(repo='planted', added={'ignore': ('E501',)}, dropped={}, ceiling=1)
    with pytest.raises(ForkedSectionDelta):
        inspect_section(_clean_file(tmp_path), PLANTED, delta)


# ------------------------------------------------------------------------------- floors and the kit


def test_an_empty_section_base_is_refused() -> None:
    """A base that owns no key reports every file OWNED, which is the vacuous green a floor refuses."""
    hollow = SectionBase(artefact='[tool.void]', table=('tool', 'void'), prefix=('tool',), scalars={}, sets={})
    with pytest.raises(VacuousBase):
        section_problems(hollow, SectionDelta(repo='planted', added={}, dropped={}, ceiling=0))


def test_the_ruff_base_is_the_measured_fifty_eight_and_the_ten_code_core() -> None:
    """The base is what R1 landed, with a floor under the count so an unread table cannot read clean."""
    assert len(RUFF_SELECT) >= RUFF_SELECT_FLOOR, len(RUFF_SELECT)
    assert len(RUFF_SELECT) == 58, len(RUFF_SELECT)
    assert len(RUFF_IGNORE_CORE) == 10, RUFF_IGNORE_CORE
    lint = ruff_section_base('[tool.ruff.lint]')
    assert set(lint.sets['select']) == set(RUFF_SELECT)
    assert set(lint.sets['ignore']) == set(RUFF_IGNORE_CORE)
    assert lint.prefix == RUFF_SECTION_PREFIX
    root = ruff_section_base('[tool.ruff]')
    assert root.scalars['line-length'] == RUFF_LINE_LENGTH
    assert 'target-version' not in root.scalars, (
        'target-version is a MEASURED disagreement (py312 in the kit, py313 in all three consumers) '
        'and a base that carried it would be legislating rather than sharing'
    )
    assert len(set(RUFF_TARGET_VERSIONS.values())) > 1, RUFF_TARGET_VERSIONS


def test_an_unknown_section_names_the_ones_that_exist() -> None:
    """The lookup refuses HERE with the set it could have meant, as `artefact_base` does one layer up."""
    with pytest.raises(ForkedSectionDelta, match=r'\[tool\.ruff\.lint\]'):
        ruff_section_base('[tool.ruff.isort]')


def test_the_kit_is_owned_by_the_ruff_base_with_an_empty_delta() -> None:
    """THE LIVE MEASUREMENT: this repo's own pyproject.toml is base-plus-nothing, today."""
    root = Path(__file__).resolve().parents[1]
    path = ruff_config_path(root)
    assert path.name == 'pyproject.toml', path
    for artefact in ('[tool.ruff]', '[tool.ruff.lint]'):
        report = inspect_section(path, ruff_section_base(artefact), KIT_DELTA)
        assert report.status == OWNED, f'{artefact}: {report.detail}\n  ' + '\n  '.join(report.offending)


def test_locate_and_expected_entries_are_pure_and_drive_the_report() -> None:
    """The two readings the report is built from answer on their own, so a control can drive either."""
    assert locate_section({'tool': {'plant': {'lint': {'select': ['E']}}}}, PLANTED) == {'select': ['E']}
    assert locate_section({'project': {}}, PLANTED) is None
    assert expected_entries(PLANTED, PLANTED_DELTA, 'ignore') == frozenset({'E501', 'D203'})
    assert expected_entries(PLANTED, PLANTED_DELTA, 'select') == frozenset({'E', 'F'})
