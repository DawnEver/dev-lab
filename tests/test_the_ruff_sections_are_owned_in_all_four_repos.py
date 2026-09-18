r"""THE RUFF SECTION BASE IS DRIVEN OVER THE LIVE TREES, and until this module it was driven over nothing.

WHAT WAS WRONG, MEASURED 2026-09-18. `lab_commons.dev.famconfig` published `RUFF_SECTIONS`,
`ruff_section_base` and `section_problems` with 21 green tests, and every one of them drove a PLANTED
file. Scanning ``tests/`` and ``src/`` for those three names returned the module that defines them
and the kit's re-export -- nothing else. So the base could not have refused anything in any of the
four repos it is a claim about, and this family's own rule says what that is: "a ratchet has two
sides -- a capability that disappears, or a waiver nothing uses, is as wrong as its opposite".

WHAT THIS MODULE IS AND IS NOT. It is the CONSUMER of that base: the declarations live in
`_famconfig_section_delta.py` as data, and every arm below reads a real ``pyproject.toml`` or
``ruff.toml`` off disk through the kit's own `inspect_section`. It re-implements nothing -- a second
reader that agreed with the first by construction would be the vacuous green this package refuses
everywhere else.

WHY IT IS A SEPARATE MODULE FROM `test_the_config_census_is_measured.py`, which measures the same
four files. The census asks WHAT IS TRUE of the family today and records numbers; this asks whether
each repo's table is what the live base and that repo's DECLARATION produce, and its remedy is an
edit to a declaration rather than a re-measurement. The two answer different questions about one
artefact, which is the same reason the Makefile contract and the pre-commit rendering are two files.

THE MOTRONICS ROW IS THE ONE THAT MAKES THE `prefix` RULE NON-VACUOUS. Three repos keep these tables
in ``pyproject.toml`` and that repo keeps them in ``ruff.toml``, where they lose the ``tool.ruff``
prefix and the root table IS the file. Both spellings are read here by the same base, against real
files, which is what the planted tests could assert about the resolver but not about the tree.
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
from _famconfig_section_delta import RUFF_LINT, SECTION_DELTAS

from lab_commons.dev._famconfig_ruff_rows import RUFF_KEY_FLOOR, RUFF_SELECT, RUFF_SELECT_FLOOR
from lab_commons.dev.famconfig import (
    OWNED,
    RUFF_SECTIONS,
    ForkedSectionDelta,
    SectionDelta,
    inspect_section,
    locate_section,
    ruff_config_path,
    ruff_section_base,
    section_problems,
)

#: The SET key the floors below are stated over, spelled once. It is a NAME rather than a literal at
#: every use site because ruff's own `S608` reads the word inside an f-string as SQL, and a
#: suppression for a message about a linter's selector list is noise that a constant removes outright.
SELECT: Final = 'select'

#: Every owned table, in the spelling a reader writes it in. Read off the live registry rather than
#: restated, so a row added there arrives here and cannot be judged by a list that stayed behind.
ARTEFACTS = tuple(sorted(RUFF_SECTIONS))

#: The scan's floor, stated as the PRODUCT rather than as an integer: a run that lost a repo and a
#: run that lost a table are different failures, and a bare count cannot tell them apart.
CELL_FLOOR = len(REPOS) * len(ARTEFACTS)

#: The one selector the DROP controls bend. It is a whole group every repo takes and no repo waives,
#: so removing it is a real capability loss rather than a code that was already dead.
BENT_SELECTOR = 'FURB'

#: The code the ADD control plants. It is in the family select, in NO repo's ignore list, and is
#: therefore a waiver that would really be new -- planting one a repo already waives would make the
#: control green against a file nothing changed in.
PLANTED_WAIVER = 'PLR0911'


def kit_tables(root: Path) -> dict[str, dict[str, object]]:
    """The kit's LIVE ruff tables, read through the same resolver the property arm uses.

    Read rather than fixtured, so a control cannot go on asserting against a config this repo stopped
    having. The controls below bend THIS, which is why the unedited round trip has to be OWNED first.
    """
    document = tomllib.loads(ruff_config_path(root).read_text(encoding='utf-8'))
    found = {artefact: locate_section(document, base) or {} for artefact, base in RUFF_SECTIONS.items()}
    return {
        artefact: {key: table[key] for key in RUFF_SECTIONS[artefact].owned_keys if key in table}
        for artefact, table in found.items()
    }


def plant(path: Path, tables: Mapping[str, Mapping[str, object]]) -> Path:
    """*tables* written out as a ``pyproject.toml`` at *path*, owned keys only.

    IT EMITS RATHER THAN EDITS BYTES, and that is deliberate after the first cut of these controls
    did the opposite. Surgery on the live file's text is a control that depends on how somebody
    wrapped a selector list -- the kit packs ten codes per line with a trailing comment, so a
    line-shaped replacement silently matched nothing and the "bent" file was the clean one. An
    emitter cannot fail that way, and the floor each control asserts first -- the UNEDITED emission
    is OWNED -- is what proves the emission is faithful for every key the base owns.

    TABLES GO OUT PARENT FIRST, which is the second thing that bit: sorting the artefact SPELLINGS
    puts ``[tool.ruff.lint]`` before ``[tool.ruff]`` (a dot sorts under a bracket), and TOML refuses a
    parent re-opened after its child. The order is taken from the base's dotted path length, so it is
    a property of the table rather than of how a reader writes its name.
    """
    ordered = sorted(tables, key=lambda artefact: (len(RUFF_SECTIONS[artefact].table), artefact))
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
    live = {f'{repo}::{artefact}' for repo, table in SECTION_DELTAS.items() for artefact in table}
    assert len(expected) == CELL_FLOOR, f'{len(expected)} cells against {len(REPOS)} repos x {len(ARTEFACTS)} tables'
    assert live == expected, (
        f'undeclared: {sorted(expected - live)}; invented: {sorted(live - expected)}. A table with no '
        f'declaration is not judged, and a declaration for a table the base does not own judges nothing.'
    )


def test_no_declared_delta_is_a_fork_of_the_base_it_declares_against() -> None:
    """Driven on the DECLARATION alone, so a malformed delta is a different answer from a diverged file.

    `section_problems` binds the base's key floor itself, so an empty base cannot make this pass.
    """
    for repo, table in sorted(SECTION_DELTAS.items()):
        for artefact, delta in sorted(table.items()):
            base = ruff_section_base(artefact)
            assert len(base.owned_keys) >= RUFF_KEY_FLOOR, f'{artefact} owns no key; every arm below just went thin'
            assert delta.repo == repo, f'{repo}::{artefact} declares itself as {delta.repo!r}'
            assert section_problems(base, delta) == (), section_problems(base, delta)


def test_every_ceiling_is_its_measurement_and_no_delta_carries_headroom() -> None:
    """THE RATCHET'S OTHER SIDE. Headroom nobody chose is how a waiver list stops being a delta."""
    measured = {'lab-commons': 0, 'wdg-lab': 53, 'optimi-lab': 52, 'motronics-studio': 56}
    for repo, table in sorted(SECTION_DELTAS.items()):
        for artefact, delta in sorted(table.items()):
            added = sum(len(entries) for entries in delta.added.values())
            assert added == delta.ceiling, (
                f'{repo}::{artefact} adds {added} entries against a ceiling of {delta.ceiling}. The '
                f'ceiling was set AT the measurement, so an entry added here raises it in the same '
                f'edit and says what it is for, and an entry removed lowers it.'
            )
        assert table[RUFF_LINT].ceiling == measured[repo], (
            f"{repo}'s ignore delta was measured at {measured[repo]} on 2026-09-18 and now declares "
            f'{table[RUFF_LINT].ceiling} -- re-measure against the live config before moving the number'
        )


# ------------------------------------------------------------------------------ the live measurement


def test_every_reached_repo_owns_every_table_the_base_declares() -> None:
    """THE PROPERTY. Each real file, through the kit's own reader, against the live base and delta."""
    reached = reachable_repos(REPO_PATHS)
    assert 'lab-commons' in reached, 'the reader could not find the tree it is running in'
    absent = sorted(set(REPOS) - set(reached))
    verdicts: dict[str, str] = {}
    for repo, root in sorted(reached.items()):
        config = ruff_config_path(root)
        for artefact in ARTEFACTS:
            report = inspect_section(config, ruff_section_base(artefact), SECTION_DELTAS[repo][artefact])
            verdicts[f'{repo}::{artefact}'] = report.status
            assert report.ok, (
                f'{repo}::{artefact} in {config.name} is {report.status}: {report.detail} {report.offending}'
            )
    assert len(verdicts) == len(reached) * len(ARTEFACTS), (
        f'{len(verdicts)} cells judged over {len(reached)} reached repo(s) x {len(ARTEFACTS)} '
        f'table(s); not checked out here and therefore unjudged: {absent}'
    )
    assert set(verdicts.values()) == {OWNED}, sorted(verdicts.items())


def test_the_two_config_spellings_are_both_exercised_against_a_real_file() -> None:
    """THE `prefix` RULE'S FLOOR. One base, two filenames -- and a planted file cannot prove a tree uses both.

    If only ``pyproject.toml`` is reachable the dedicated-file branch of `locate_section` is untested
    by every arm above, so the reach is asserted rather than assumed: the arm names which spelling it
    actually read in which repo, and a family that collapsed onto one filename reds here.
    """
    reached = reachable_repos(REPO_PATHS)
    names = {repo: ruff_config_path(root).name for repo, root in sorted(reached.items())}
    assert names['lab-commons'] == 'pyproject.toml', names
    motronics = names.get('motronics-studio')
    assert motronics is None or motronics == 'ruff.toml', (
        f'motronics-studio now keeps its ruff tables in {motronics!r}. The base is keyed by TABLE and '
        f'not by FILE precisely so this may move -- but the `prefix` branch then has no live subject, '
        f'so say so here rather than letting the resolver go unexercised.'
    )


def test_the_selects_are_one_set_across_every_reached_repo() -> None:
    """The base's biggest SET key, re-derived rather than trusted, with a floor under the reading."""
    reached = reachable_repos(REPO_PATHS)
    base = ruff_section_base(RUFF_LINT)
    assert len(base.sets[SELECT]) >= RUFF_SELECT_FLOOR, (
        f'the base holds {len(base.sets[SELECT])} selectors, below the {RUFF_SELECT_FLOOR} floor -- '
        f'a comparison over a near-empty selector set agrees with everything it reads'
    )
    per_repo = {}
    for repo, root in sorted(reached.items()):
        document = tomllib.loads(ruff_config_path(root).read_text(encoding='utf-8'))
        table = document.get('lint') or document.get('tool', {}).get('ruff', {}).get('lint', {})
        per_repo[repo] = set(table[SELECT])
    assert per_repo, 'no ruff config was read at all'
    assert set.union(*per_repo.values()) == set(RUFF_SELECT), sorted(set.union(*per_repo.values()))
    assert set.intersection(*per_repo.values()) == set(RUFF_SELECT), 'the four-way selector agreement broke'


# ----------------------------------------------------------------------------- the planted controls


def test_an_added_ignore_entry_reds_and_the_refusal_names_the_code(tmp_path: Path) -> None:
    """PLANTED CONTROL, the move this base exists to catch, through the REAL reader.

    A repo quietly widening its waiver list is the one direction `REQUIRED` mode could never see, so
    the unedited copy must be OWNED first -- a guard green on a constant would pass this either way.
    """
    root = reachable_repos(REPO_PATHS)['lab-commons']
    delta = SECTION_DELTAS['lab-commons'][RUFF_LINT]
    base = ruff_section_base(RUFF_LINT)
    tables = kit_tables(root)
    assert PLANTED_WAIVER not in tables[RUFF_LINT]['ignore'], f'the kit already waives {PLANTED_WAIVER}'

    assert inspect_section(plant(tmp_path / 'pyproject.toml', tables), base, delta).ok, (
        'the unedited emission is already not OWNED; this control would red on its own fixture'
    )

    tables[RUFF_LINT]['ignore'] = [*tables[RUFF_LINT]['ignore'], PLANTED_WAIVER]
    report = inspect_section(plant(tmp_path / 'pyproject.toml', tables), base, delta)
    assert not report.ok, 'a waiver nobody declared was accepted -- the base is asserting presence again'
    assert any(PLANTED_WAIVER in line for line in report.offending), report.offending
    assert any('undeclared local waiver' in line for line in report.offending), report.offending


def test_a_dropped_selector_reds_and_the_refusal_names_it(tmp_path: Path) -> None:
    """PLANTED CONTROL, the other direction: the base leaving through the file instead of the table."""
    root = reachable_repos(REPO_PATHS)['lab-commons']
    delta = SECTION_DELTAS['lab-commons'][RUFF_LINT]
    base = ruff_section_base(RUFF_LINT)
    tables = kit_tables(root)
    assert BENT_SELECTOR in tables[RUFF_LINT][SELECT], 'this control bends nothing: the kit does not select it'

    tables[RUFF_LINT][SELECT] = [code for code in tables[RUFF_LINT][SELECT] if code != BENT_SELECTOR]
    report = inspect_section(plant(tmp_path / 'pyproject.toml', tables), base, delta)
    assert not report.ok, f'{BENT_SELECTOR} left the config and nothing noticed'
    assert any(BENT_SELECTOR in line and 'does not have it' in line for line in report.offending), report.offending


def test_the_same_drop_with_a_declared_reason_is_owned(tmp_path: Path) -> None:
    """PLANTED CONTROL, THE RATCHET'S OTHER SIDE: a declared loss is OWNED, and it still costs a reason.

    Without this arm the two above would be satisfied by a base that refuses every change, which is a
    ratchet with one side. The file here is byte-identical to the one that just red; only the
    DECLARATION moved, which is the whole claim the mechanism makes.
    """
    root = reachable_repos(REPO_PATHS)['lab-commons']
    base = ruff_section_base(RUFF_LINT)
    tables = kit_tables(root)
    tables[RUFF_LINT][SELECT] = [code for code in tables[RUFF_LINT][SELECT] if code != BENT_SELECTOR]
    planted = plant(tmp_path / 'pyproject.toml', tables)

    owned = SectionDelta(
        repo='lab-commons',
        added={},
        dropped={(SELECT, BENT_SELECTOR): 'PLANTED: this repo declares the group gone, with a reason'},
        ceiling=0,
    )
    assert inspect_section(planted, base, owned).ok, inspect_section(planted, base, owned).offending

    silent = SectionDelta(repo='lab-commons', added={}, dropped={(SELECT, BENT_SELECTOR): '   '}, ceiling=0)
    with pytest.raises(ForkedSectionDelta, match='reason'):
        inspect_section(planted, base, silent)
