"""FAMILY-CONFIG-IS-RENDERED, as a body each consumer parametrizes: a hand edit to a shared artefact REDS.

WHAT THIS IS THE FAMILY HALF OF. Both labs hold a ``test_the_family_config_is_rendered.py``, 348 and
300 lines, 59% identical CODE with docstrings blanked -- and BOTH already import their repo half from
a local ``_famconfig`` holding ``DELTAS``, ``EXTRA_HOOK_IDS`` and ``REPO``. The seam was already drawn
in both trees; what was missing was the other side of it. This is that side.

WHAT GREEN MEANS, STATED EXACTLY, because overclaiming it would be the defect the family calls
dominant. For a RENDERED artefact it means the bytes on disk are what base plus delta produce; for a
REQUIRED one, that every base line is PRESENT -- a Makefile's shared targets share a NAME and no
RECIPE, so byte equality there would assert a portability that does not exist. It says nothing about
whether any rule or target is CORRECT.

NOTHING HERE RE-IMPLEMENTS :mod:`dev_lab.dev.famconfig`. Rendering, comparing, refusing a
malformed delta and surveying an unmanaged file are that module's; every assert below adds the two
things a shared body owes -- a FLOOR under each scan, and a remedy named in the caller's own words.

AND FOUR ARMS THE LABS HOLD ARE ALREADY IN THE KIT, which this is careful not to bury. Both plant
refusals against ``Delta.anchored`` (an anchor on a repeated base line, on a line the base lacks, one
carrying no lines) plus a delta restating a base content line -- all four already driven against the
real base in ``tests/test_dev_famconfig.py``, and the consumer half of each is exactly
:func:`assert_delta_is_not_a_fork`. Copying them here would be a fifth spelling of a kit test living
in four consumer trees, so they are NOT here, and this paragraph is why.

THE READINGS LIVE IN :mod:`dev_lab.dev.famtests._configrender_readings` and are re-exported here,
so a consumer has ONE import surface while the split stays real: everything there is a READING and
everything here is a VERDICT that adds a floor, a comparison and a remedy. That is the same seam
:mod:`dev_lab.dev._famconfig_survey` runs on one layer down, and the import runs one way.

EVERY OTHER REPO-SHAPED FACT ARRIVES THE SAME WAY: the root, the repo name, the delta table and the
re-render command.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dev_lab.dev.famconfig import (
    ABSENT,
    BASES,
    INSTALLED,
    RENDERED,
    RUFF_SECTIONS,
    SECTION_BASES,
    artefact_base,
    delta_problems,
    inspect_file,
    inspect_section,
    measured_delta,
    render,
    ruff_config_path,
)
from dev_lab.dev.famtests._configrender_readings import (
    Reopening,
    assert_floor,
    reopenings,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from dev_lab.dev.famconfig import Base, Delta, SectionDelta

__all__ = [
    'Reopening',
    'assert_artefact_is_rendered',
    'assert_delta_is_not_a_fork',
    'assert_every_base_is_accounted_for',
    'assert_every_section_is_owned',
    'assert_modes_are_as_agreed',
    'assert_no_base_line_left_undeclared',
    'assert_no_rule_is_reopened',
    'assert_render_round_trips',
    'reopenings',
]


def assert_every_base_is_accounted_for(*, deltas: Mapping[str, Delta], repo: str) -> None:
    """COMPLETENESS: the kit's bases and this repo's declarations are the same set, exactly.

    A suite that only checks the artefacts a repo happens to declare cannot tell a base the repo has
    not adopted from one the kit has not published. Both directions are named, because a declaration
    outliving its subject reads as a live adoption.
    """
    assert_floor(len(deltas), 1, f'{repo} declares no artefact at all')
    if set(deltas) != set(BASES):
        unadopted, unknown = sorted(set(BASES) - set(deltas)), sorted(set(deltas) - set(BASES))
        msg = (
            f"{repo} accounts for {sorted(deltas)} against the kit's {sorted(BASES)}. Not adopted and not "
            f'refused: {unadopted} -- an artefact drifting with nobody saying so. Declared and not published: '
            f'{unknown} -- a declaration that outlived its subject. Add a Delta, or delete the entry.'
        )
        raise AssertionError(msg)


def assert_artefact_is_rendered(
    *, root: Path, artefact: str, deltas: Mapping[str, Delta], repo: str, rerender_hint: str
) -> None:
    """THE PROPERTY: this file is the family's answer plus the lines this repo declared.

    *rerender_hint* has no default. The command that re-renders a repo's artefacts is that repo's --
    measured today, one lab runs a Makefile target and the other an inline interpreter line -- and a
    guessed remedy is a refusal nobody can act on, which is how a refusal gets routed around.
    """
    base = artefact_base(artefact)
    report = inspect_file(root / artefact, base, deltas[artefact])
    if report.status == INSTALLED:
        return
    remedy = (
        rerender_hint
        if base.mode == RENDERED
        else f'add the missing line(s) to {artefact}, or declare each as a Delta.dropped entry saying why'
    )
    offending = '\n  '.join(report.offending) or '(none listed)'
    absent = '\n  This artefact is not on disk at all, which guarantees nothing.' if report.status == ABSENT else ''
    msg = (
        f'{artefact} is {report.status} in {repo} ({base.mode} mode): {report.detail}\n  {offending}{absent}\n\n'
        f'A shared artefact edited by hand stops being shared the moment the edit lands, and nothing else '
        f'in this tree would have said so. If the edit was wanted it is a delta line or a declared drop, '
        f"and both live in this repo's own famconfig declaration.\n  {remedy}\n"
    )
    raise AssertionError(msg)


def assert_delta_is_not_a_fork(*, artefact: str, deltas: Mapping[str, Delta], repo: str) -> None:
    """The anti-fork arm, driven on the DECLARATION so it is a separate answer from "the file drifted".

    :func:`~dev_lab.dev.famconfig.inspect_file` RAISES on a malformed delta, which is right for a
    renderer and wrong for a reader trying to tell the two apart. Asking ``delta_problems`` separates
    them, and this is also the consumer half of every anchor control the kit already drives.
    """
    problems = delta_problems(artefact_base(artefact), deltas[artefact])
    if problems:
        msg = f"{repo}'s {artefact} delta is not a delta of the base:\n  " + '\n  '.join(problems)
        raise AssertionError(msg)


def assert_no_rule_is_reopened(*, base: Base, delta: Delta, repo: str, directory_floor: int) -> None:
    """A delta renders AFTER the base, and ``.gitignore`` is last-match-wins, so ORDER is the rule.

    Three shapes, one hazard. A BARE re-statement of a slashed base rule is a different rule wearing a
    duplicate's clothes -- a trailing slash matches a directory only -- and it wins by coming later. A
    NEGATION re-includes what the base excluded above it unless the delta closes the rule again below.
    An UNSEALED closure is the same fact read from the other end: a re-statement of a base rule that a
    subtree negation BELOW it re-includes again, which is the shape a presence test is blind to and
    the one a consumer had to pin by hand as "this line must be last". None of the three is visible to
    a byte comparison: all render exactly as declared. *directory_floor* has no default, because how
    many directory rules a base carries is a fact about that base.
    """
    found = reopenings(base, delta)
    assert_floor(len(found.base_directories), directory_floor, f'{base.artefact} base holds no directory rule')
    if found.bare:
        msg = (
            f"{repo}'s {base.artefact} delta re-adds {sorted(found.bare)} without the base's trailing slash. "
            f'Those render AFTER the base and gitignore is last-match-wins, so each silently reverts the '
            f'slashed base rule it looks like a duplicate of. Drop the bare line.'
        )
        raise AssertionError(msg)
    if found.reopened:
        msg = (
            f'{sorted(found.reopened)} re-include a path the {base.artefact} base excludes, and the delta '
            f'renders AFTER the base. Either narrow the negation to something the base does not exclude, '
            f'or close the rule again as a LATER line. Last-match-wins means order is the rule.'
        )
        raise AssertionError(msg)
    if found.unsealed:
        msg = (
            f'{sorted(found.unsealed)} re-state a {base.artefact} base directory rule and are then re-included '
            f'by a LATER subtree negation in the same delta, so each closes nothing. The line exists, which is '
            f'why a presence check passes; it is above the re-inclusion, which is why the rule is open. Move it '
            f'BELOW every negation it is meant to close.'
        )
        raise AssertionError(msg)


def assert_modes_are_as_agreed(*, modes: Mapping[str, str]) -> None:
    """The mode each artefact is judged under is the one this repo agreed to, named rather than taken.

    RENDERED demands byte equality and REQUIRED only presence, so a base silently arriving in the other
    mode changes what green MEANS without changing a byte here. Naming the weaker mode stops it being
    reached out of convenience; naming the stronger stops a repo's recipes becoming a diff against a
    family file that cannot hold them.
    """
    assert_floor(len(modes), 1, 'this repo declares no mode for any artefact')
    live = {name: BASES[name].mode for name in modes if name in BASES}
    unknown = sorted(set(modes) - set(BASES))
    if unknown:
        msg = f'{unknown} have a declared mode and no base in the kit; the declaration outlived its subject'
        raise AssertionError(msg)
    changed = {name: (live[name], modes[name]) for name in modes if live[name] != modes[name]}
    if changed:
        msg = (
            f'the kit now judges (live, agreed): {changed}. A mode change rewrites what green means here '
            f'without touching a byte in this tree. Re-read what the new mode demands before agreeing.'
        )
        raise AssertionError(msg)


def assert_no_base_line_left_undeclared(*, root: Path, artefact: str, repo: str) -> None:
    """The survey that SIZED an adoption, re-run against the adopted file -- a second route in.

    After adoption the survey must find nothing to drop: every base line is on disk. It reaches the same
    ratchet as the rendered-bytes property by a route that does not go through the bytes, so a base line
    leaving is visible even where the mode is the weaker one.
    """
    survey = measured_delta(root / artefact, artefact_base(artefact), repo)
    if survey.dropped:
        msg = (
            f'the survey reports {sorted(survey.dropped)} absent from {artefact} on disk with no declared '
            f'drop. A base line left this file, and a removal nothing declares is a drift by another name.'
        )
        raise AssertionError(msg)


def assert_render_round_trips(
    *, artefact: str, deltas: Mapping[str, Delta], repo: str, scratch: Path, edit: tuple[str, str]
) -> None:
    """PLANTED CONTROL, both directions, through the same function the property uses.

    A guard green on the real tree could be asserting a constant. The artefact is rendered into a scratch
    path and must INSTALL; then *edit* replaces one base line and it must NOT, and the refusal has to
    NAME the line or the guard reported a failure it never located. The pair comes from the caller
    because which line is safe to bend is a fact about the base this repo declared.
    """
    base, delta = artefact_base(artefact), deltas[artefact]
    target, replacement = edit
    if not any(target in line for line in base.content_lines):
        msg = f'no such line: {target!r} is not in the {artefact} base, so this control plants nothing'
        raise AssertionError(msg)
    planted = scratch / artefact
    planted.write_text(render(base, delta), encoding='utf-8')
    clean = inspect_file(planted, base, delta)
    if clean.status != INSTALLED:
        msg = f"{repo}'s freshly rendered {artefact} does not install ({clean.status}): {clean.detail}"
        raise AssertionError(msg)
    planted.write_text(planted.read_text(encoding='utf-8').replace(target, replacement), encoding='utf-8')
    edited = inspect_file(planted, base, delta)
    if edited.status == INSTALLED:
        msg = f'a hand edit to a base line of {artefact} did not red -- the guard is theatre'
        raise AssertionError(msg)
    if not any(target in line for line in edited.offending):
        msg = f'{artefact} reds on the edit but never names {target!r}: {edited.offending}'


def assert_every_section_is_owned(*, root: Path, deltas: Mapping[str, SectionDelta], repo: str) -> None:
    """Every family config TABLE in *root* is the section base plus this repo's SectionDelta.

    The tables are `[tool.ruff*]`, `[project]` and `[tool.pytest.ini_options]`; every base must be declared.

    The consumer's verdict on its OWN tables. Moved here 2026-10-03 from kit tests that read every
    consumer's pyproject/ruff config from the kit's suite: a test judges the repo it lives in.
    """
    missing = sorted(set(SECTION_BASES) - set(deltas))
    unknown = sorted(set(deltas) - set(SECTION_BASES))
    problems = [f'{name}: no SectionDelta declared' for name in missing]
    problems += [f'{name}: declared, and the kit publishes no such section' for name in unknown]
    for name in sorted(set(SECTION_BASES) & set(deltas)):
        base = SECTION_BASES[name]
        path = ruff_config_path(root) if name in RUFF_SECTIONS else root / 'pyproject.toml'
        report = inspect_section(path, base, deltas[name])
        if not report.ok:
            problems.append(f'{name} in {path.name}: {report.status} -- {report.detail} {list(report.offending)}')
    if problems:
        msg = f'{repo}: config tables that are not base + delta:\n  ' + '\n  '.join(problems)
        raise AssertionError(msg)
