r"""`pyproject.toml` HAS A SECTION BASE, and until this module nothing owned a key of it.

WHAT WAS WRONG, MEASURED 2026-09-19. The family config census scored six artefacts. Five of them had
a base; ``pyproject.toml`` -- the BIGGEST file in the family at 169/377/223/293 lines -- had none at
all, and neither did ``docs-src/dev/``. The instrument for exactly this had existed since 2026-09-18
(`SectionBase`, `SectionDelta`, `inspect_section`) and was wired to one artefact.

WHAT THIS MODULE IS. It is the consumer of `PYPROJECT_SECTIONS`: the declarations are data in
`lab_commons.dev._famconfig_pyproject_rows` and `_famconfig_pyproject_section_delta`, and every arm
reads a real ``pyproject.toml`` off disk through the kit's own `inspect_section`. It re-implements
nothing -- a second reader agreeing with the first by construction is the vacuous green this package
refuses everywhere else.

THE DECLINE REGISTRY IS HALF THE DELIVERABLE AND IT IS TESTED LIKE ONE. Two owned tables out of the
39 the four files declare is a small base, and the thing that makes it a MEASUREMENT rather than a
shrug is `PYPROJECT_DECLINED`: every table measured and not promoted, with the number that decided
it. `TestTheDeclineRegistryIsAboutLiveTables` drives it both ways -- a decline naming a table no repo
declares is a decision nothing consults, and a table promoted while still declined is the two
halves contradicting each other.

THE EMPTY-PREFIX ROW IS WHAT MAKES `locate_section`'s OTHER BRANCH NON-VACUOUS. The ruff bases carry
``prefix=('tool','ruff')`` and exercise the dedicated-file spelling against motronics' ``ruff.toml``.
These carry an EMPTY prefix, so they take the branch that says a file is dedicated when it does not
declare the prefix at all -- the branch whose first cut made every ``pyproject.toml`` on earth
"declare" its table twice. Both branches now have a live subject.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Final

import pytest
from _config_census import reachable_repos
from _config_census_rows import REPO_PATHS, REPOS
from _famconfig_pyproject_section_delta import PYPROJECT_SECTION_DELTAS

from lab_commons.dev._famconfig_pyproject_rows import (
    PROJECT,
    PYPROJECT_DECLINED,
    PYPROJECT_FILE,
    PYPROJECT_TABLE_FLOOR,
    PYTEST_INI,
    README_NAME,
)
from lab_commons.dev.famconfig import (
    OWNED,
    PYPROJECT_SECTIONS,
    SECTION_KEY_FLOOR,
    ForkedSectionDelta,
    SectionDelta,
    inspect_section,
    locate_section,
    section_base,
    section_problems,
)

#: Every owned table, read off the live registry rather than restated, so a row added there arrives
#: here and cannot be judged by a list that stayed behind.
ARTEFACTS: Final = tuple(sorted(PYPROJECT_SECTIONS))

#: The scan's floor, stated as the PRODUCT rather than as an integer: a run that lost a repo and a
#: run that lost a table are different failures, and a bare count cannot tell them apart.
CELL_FLOOR: Final = len(REPOS) * len(ARTEFACTS)

#: The SET entry the ADD control plants. No repo collects it, so planting it is a widening that
#: would really be new -- planting one a repo already has makes the control green against a file
#: nothing changed in.
PLANTED_TESTPATH = 'src/nobody'

#: The base entry the DROP controls remove. Every repo has it and no delta drops it, so removing it
#: is a real loss rather than a line that was already dead.
BENT_TESTPATH = 'tests'


def live_tables(root: Path) -> dict[str, dict[str, object]]:
    """*root*'s owned tables, owned keys only, read through the same resolver the property arm uses.

    Read rather than fixtured, so a control cannot go on asserting against a file this repo stopped
    having. The controls bend THIS, which is why each asserts the unedited round trip is OWNED first.
    """
    document = tomllib.loads((root / PYPROJECT_FILE).read_text(encoding='utf-8'))
    found = {artefact: locate_section(document, base) or {} for artefact, base in PYPROJECT_SECTIONS.items()}
    return {
        artefact: {key: table[key] for key in PYPROJECT_SECTIONS[artefact].owned_keys if key in table}
        for artefact, table in found.items()
    }


def plant(path: Path, tables: Mapping[str, Mapping[str, object]]) -> Path:
    """*tables* written out as a ``pyproject.toml`` at *path*, owned keys only.

    IT EMITS RATHER THAN EDITS BYTES, for the reason the ruff suite's twin gives: surgery on the live
    text is a control that depends on how somebody wrapped a list. Tables go out parent-first by
    dotted-path length, because TOML refuses a parent re-opened after its child.
    """
    ordered = sorted(tables, key=lambda artefact: (len(PYPROJECT_SECTIONS[artefact].table), artefact))
    lines: list[str] = []
    for artefact in ordered:
        lines.append(artefact)
        lines += [f'{key} = {json.dumps(value)}' for key, value in sorted(tables[artefact].items())]
        lines.append('')
    path.write_text('\n'.join(lines), encoding='utf-8')
    return path


# --------------------------------------------------------------- the declarations, before any file


def test_every_repo_and_table_has_a_declaration_and_none_invents_one() -> None:
    """COMPLETENESS, BOTH SIDES. A missing delta leaves a table unjudged; an extra one names nothing."""
    expected = {f'{repo}::{artefact}' for repo in REPOS for artefact in ARTEFACTS}
    live = {f'{repo}::{artefact}' for repo, table in PYPROJECT_SECTION_DELTAS.items() for artefact in table}
    assert len(expected) == CELL_FLOOR, f'{len(expected)} cells against {len(REPOS)} repos x {len(ARTEFACTS)} tables'
    assert live == expected, (
        f'undeclared: {sorted(expected - live)}; invented: {sorted(live - expected)}. A table with no '
        f'declaration is not judged, and a declaration for a table the base does not own judges nothing.'
    )


def test_no_declared_delta_is_a_fork_of_the_base_it_declares_against() -> None:
    """Driven on the DECLARATION alone, so a malformed delta is a different answer from a diverged file."""
    for repo, table in sorted(PYPROJECT_SECTION_DELTAS.items()):
        for artefact, delta in sorted(table.items()):
            base = section_base(artefact)
            assert len(base.owned_keys) >= SECTION_KEY_FLOOR, f'{artefact} owns no key; every arm below went thin'
            assert delta.repo == repo, f'{repo}::{artefact} declares itself as {delta.repo!r}'
            assert section_problems(base, delta) == (), section_problems(base, delta)


def test_every_ceiling_is_its_measurement_and_no_delta_carries_headroom() -> None:
    """THE RATCHET'S OTHER SIDE. Headroom nobody chose is how a waiver list stops being a delta."""
    measured = {'lab-commons': 0, 'wdg-lab': 1, 'optimi-lab': 1, 'motronics-studio': 0}
    for repo, table in sorted(PYPROJECT_SECTION_DELTAS.items()):
        for artefact, delta in sorted(table.items()):
            added = sum(len(entries) for entries in delta.added.values())
            assert added == delta.ceiling, (
                f'{repo}::{artefact} adds {added} entries against a ceiling of {delta.ceiling}. The '
                f'ceiling was set AT the measurement, so an entry added here raises it in the same '
                f'edit and says what it is for, and an entry removed lowers it.'
            )
        assert table[PYTEST_INI].ceiling == measured[repo], (
            f"{repo}'s testpaths delta was measured at {measured[repo]} on 2026-09-19 and now "
            f'declares {table[PYTEST_INI].ceiling} -- re-measure the live file before moving it'
        )


# ------------------------------------------------------------------------------ the live measurement


def test_every_reached_repo_owns_every_table_the_base_declares() -> None:
    """THE PROPERTY. Each real file, through the kit's own reader, against the live base and delta."""
    reached = reachable_repos(REPO_PATHS)
    assert 'lab-commons' in reached, 'the reader could not find the tree it is running in'
    absent = sorted(set(REPOS) - set(reached))
    verdicts: dict[str, str] = {}
    for repo, root in sorted(reached.items()):
        path = root / PYPROJECT_FILE
        for artefact in ARTEFACTS:
            report = inspect_section(path, section_base(artefact), PYPROJECT_SECTION_DELTAS[repo][artefact])
            verdicts[f'{repo}::{artefact}'] = report.status
            assert report.ok, f'{repo}::{artefact} is {report.status}: {report.detail} {report.offending}'
    assert len(verdicts) == len(reached) * len(ARTEFACTS), (
        f'{len(verdicts)} cells judged over {len(reached)} reached repo(s) x {len(ARTEFACTS)} '
        f'table(s); not checked out here and therefore unjudged: {absent}'
    )
    assert set(verdicts.values()) == {OWNED}, sorted(verdicts.items())


def test_the_promoted_keys_are_a_four_way_agreement_and_not_a_three_way_one() -> None:
    """THE BAR, RE-DERIVED. The whole argument for these two tables is that the KIT agrees too.

    `RUFF_QUOTE_STYLE` declines six keys because the three consumers agree and the kit does not. This
    arm is that rule pointed at the promotion: if the kit ever stops holding one of these, the base
    has become three repos legislating for a fourth and this reds rather than the kit being edited.
    """
    reached = reachable_repos(REPO_PATHS)
    assert len(reached) >= len(REPOS) - 1, f'only {sorted(reached)} reachable; a four-way claim needs the four'
    readmes, dynamics, testpaths = {}, {}, {}
    for repo, root in sorted(reached.items()):
        document = tomllib.loads((root / PYPROJECT_FILE).read_text(encoding='utf-8'))
        readmes[repo] = document['project']['readme']
        dynamics[repo] = tuple(document['project']['dynamic'])
        testpaths[repo] = set(document['tool']['pytest']['ini_options']['testpaths'])
    assert set(readmes.values()) == {README_NAME}, readmes
    assert set(dynamics.values()) == {('version',)}, dynamics
    assert set.intersection(*testpaths.values()) == {BENT_TESTPATH}, testpaths


# ------------------------------------------------------------- the DECLINED half, driven both ways


class TestTheDeclineRegistryIsAboutLiveTables:
    """A table measured and NOT promoted is recorded, and the record is checked against the files.

    A base that quietly omits a table is indistinguishable from one nobody looked at -- that is the
    reason the registry exists. It is also the reason it needs both arms: a decline nobody can
    locate in any repo rots the same way, and a table that is both declined and owned is the two
    halves of one decision disagreeing.
    """

    @staticmethod
    def _documents() -> dict[str, dict[str, object]]:
        """Every reached repo's parsed `pyproject.toml`."""
        return {
            repo: tomllib.loads((root / PYPROJECT_FILE).read_text(encoding='utf-8'))
            for repo, root in sorted(reachable_repos(REPO_PATHS).items())
        }

    def test_the_registry_clears_its_floor(self) -> None:
        """A registry of two entries is a shrug. The floor is what makes it evidence of a sweep."""
        assert len(PYPROJECT_DECLINED) >= PYPROJECT_TABLE_FLOOR, (
            f'{len(PYPROJECT_DECLINED)} declined table(s) against a floor of {PYPROJECT_TABLE_FLOOR}. '
            f'Rows may only leave by being PROMOTED, and a promotion moves the row into '
            f'PYPROJECT_SECTION_ROWS rather than deleting it.'
        )
        for table, reason in sorted(PYPROJECT_DECLINED.items()):
            assert len(reason.split()) >= 20, f'{table} is declined in {len(reason.split())} words -- state the number'

    def test_every_declined_table_is_declared_by_at_least_one_live_repo(self) -> None:
        """A decline dies with its subject. One naming a table nobody has refuses nothing."""
        documents = self._documents()
        assert documents, 'no pyproject.toml was read at all'
        for table in sorted(PYPROJECT_DECLINED):
            holders = [repo for repo, document in documents.items() if _walk(document, table) is not None]
            assert holders, (
                f'{".".join(table)} is declined and NO reached repo declares it. Either the table '
                f'left the family -- delete the row in that edit -- or the path is misspelled and '
                f'this row has been refusing nothing since it was written.'
            )

    def test_no_table_is_both_declined_and_owned(self) -> None:
        """The two halves of one decision, checked against each other rather than read side by side."""
        owned = {base.table for base in PYPROJECT_SECTIONS.values()}
        both = sorted(owned & set(PYPROJECT_DECLINED))
        assert both == [], f'{both} is both promoted and declined -- delete the decline in the edit that promoted it'

    def test_the_owned_tables_are_a_strict_subset_of_what_the_family_declares(self) -> None:
        """THE SCAN'S FLOOR. Finding nothing left to decide is vacuous, not green.

        If every table any repo declares were owned, the registry above would be empty for a REASON
        and this suite would be measuring nothing. It is not: the live files declare far more tables
        than the base owns, and the gap is what `PYPROJECT_DECLINED` accounts for.
        """
        documents = self._documents()
        declared = {table for document in documents.values() for table in _tables(document)}
        owned = {base.table for base in PYPROJECT_SECTIONS.values()}
        assert owned < declared, f'owned {sorted(owned)} against declared {sorted(declared)}'
        assert len(declared) >= 20, f'only {len(declared)} table(s) found across {sorted(documents)}'


def _walk(document: Mapping[str, object], path: tuple[str, ...]) -> Mapping[str, object] | None:
    """*path* resolved through nested mappings, or ``None`` at the first step that is not there."""
    node: object = document
    for step in path:
        if not isinstance(node, Mapping) or step not in node:
            return None
        node = node[step]
    return node if isinstance(node, Mapping) else None


def _tables(document: Mapping[str, object], prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    """Every table path in *document*, nested ones included."""
    out: list[tuple[str, ...]] = []
    for key, value in document.items():
        if isinstance(value, Mapping):
            out.append((*prefix, key))
            out += _tables(value, (*prefix, key))
    return out


# ----------------------------------------------------------------------------- the planted controls


def test_an_added_testpath_reds_and_the_refusal_names_it(tmp_path: Path) -> None:
    """PLANTED CONTROL, the widening a presence-only mode could never see, through the REAL reader."""
    root = reachable_repos(REPO_PATHS)['lab-commons']
    delta = PYPROJECT_SECTION_DELTAS['lab-commons'][PYTEST_INI]
    base = section_base(PYTEST_INI)
    tables = live_tables(root)
    assert PLANTED_TESTPATH not in tables[PYTEST_INI]['testpaths'], 'the kit already collects the planted path'

    assert inspect_section(plant(tmp_path / PYPROJECT_FILE, tables), base, delta).ok, (
        'the unedited emission is already not OWNED; this control would red on its own fixture'
    )

    tables[PYTEST_INI]['testpaths'] = [*tables[PYTEST_INI]['testpaths'], PLANTED_TESTPATH]
    report = inspect_section(plant(tmp_path / PYPROJECT_FILE, tables), base, delta)
    assert not report.ok, 'a collected path nobody declared was accepted -- the base is asserting presence again'
    assert any(PLANTED_TESTPATH in line for line in report.offending), report.offending
    assert any('undeclared local waiver' in line for line in report.offending), report.offending


def test_a_changed_readme_reds_and_the_refusal_names_both_values(tmp_path: Path) -> None:
    """PLANTED CONTROL for the SCALAR arm: the direction that says which value the file has."""
    root = reachable_repos(REPO_PATHS)['lab-commons']
    delta = PYPROJECT_SECTION_DELTAS['lab-commons'][PROJECT]
    base = section_base(PROJECT)
    tables = live_tables(root)
    assert tables[PROJECT]['readme'] == README_NAME, tables[PROJECT]
    assert inspect_section(plant(tmp_path / PYPROJECT_FILE, tables), base, delta).ok, (
        'the unedited emission is not OWNED'
    )

    tables[PROJECT]['readme'] = 'docs/index.md'
    report = inspect_section(plant(tmp_path / PYPROJECT_FILE, tables), base, delta)
    assert not report.ok, 'the readme moved and nothing noticed'
    assert any('docs/index.md' in line and README_NAME in line for line in report.offending), report.offending


def test_a_dropped_base_testpath_reds_and_the_same_drop_declared_is_owned(tmp_path: Path) -> None:
    """PLANTED CONTROL, BOTH SIDES OF THE RATCHET, over one byte-identical file.

    Without the second half the first would be satisfied by a base that refuses every change. Only
    the DECLARATION moves between the two readings, which is the whole claim the mechanism makes.
    """
    root = reachable_repos(REPO_PATHS)['lab-commons']
    base = section_base(PYTEST_INI)
    tables = live_tables(root)
    assert BENT_TESTPATH in tables[PYTEST_INI]['testpaths'], 'this control bends nothing'
    tables[PYTEST_INI]['testpaths'] = [p for p in tables[PYTEST_INI]['testpaths'] if p != BENT_TESTPATH]
    planted = plant(tmp_path / PYPROJECT_FILE, tables)

    silent = PYPROJECT_SECTION_DELTAS['lab-commons'][PYTEST_INI]
    report = inspect_section(planted, base, silent)
    assert not report.ok, f'{BENT_TESTPATH} left testpaths and nothing noticed'
    assert any(BENT_TESTPATH in line and 'does not have it' in line for line in report.offending), report.offending

    owned = SectionDelta(
        repo='lab-commons',
        added={},
        dropped={('testpaths', BENT_TESTPATH): 'PLANTED: this repo declares the path gone, with a reason'},
        ceiling=0,
    )
    assert inspect_section(planted, base, owned).ok, inspect_section(planted, base, owned).offending

    empty = SectionDelta(repo='lab-commons', added={}, dropped={('testpaths', BENT_TESTPATH): '  '}, ceiling=0)
    with pytest.raises(ForkedSectionDelta, match='reason'):
        inspect_section(planted, base, empty)


def test_a_delta_reaching_a_declined_table_is_refused_by_the_lookup() -> None:
    """PLANTED CONTROL for the registry's REFUSAL, and it names where the decision lives."""
    with pytest.raises(ForkedSectionDelta, match='PYPROJECT_DECLINED'):
        section_base('[tool.commitizen]')
