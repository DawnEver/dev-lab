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

NOTHING HERE RE-IMPLEMENTS :mod:`lab_commons.dev.famconfig`. Rendering, comparing, refusing a
malformed delta and surveying an unmanaged file are that module's; every assert below adds the two
things a shared body owes -- a FLOOR under each scan, and a remedy named in the caller's own words.

AND FOUR ARMS THE LABS HOLD ARE ALREADY IN THE KIT, which this is careful not to bury. Both plant
refusals against ``Delta.anchored`` (an anchor on a repeated base line, on a line the base lacks, one
carrying no lines) plus a delta restating a base content line -- all four already driven against the
real base in ``tests/test_dev_famconfig.py``, and the consumer half of each is exactly
:func:`assert_delta_is_not_a_fork`. Copying them here would be a fifth spelling of a kit test living
in four consumer trees, so they are NOT here, and this paragraph is why.

THE STAGE ENGINE ARRIVES AS AN ARGUMENT AND HAS NO DEFAULT, and two reasons force it independently:
a hook with no ``stages:`` key inherits them from the UPSTREAM manifest of the repo it came from, so
a table computed by parsing a consumer's YAML here would be a guess about ANOTHER repository wearing
a measurement's clothes; and ``pre_commit`` is not a dependency of this package and must not become
one, since ``lab_commons.dev``'s inventory records that the layer is stdlib plus tier 1.

THE READINGS LIVE IN :mod:`lab_commons.dev.famtests._configrender_readings` and are re-exported here,
so a consumer has ONE import surface while the split stays real: everything there is a READING and
everything here is a VERDICT that adds a floor, a comparison and a remedy. That is the same seam
:mod:`lab_commons.dev._famconfig_survey` runs on one layer down, and the import runs one way.

EVERY OTHER REPO-SHAPED FACT ARRIVES THE SAME WAY: the root, the repo name, the delta table, the
re-render command, the hook floor, the ids the anchor carries, which hooks narrowed and which kept
pre-push, and whether this checkout HAS a pre-push hook. That last is the worked example -- one lab's
narrowing is free precisely because no pre-push hook is installed and the other's is a real loss
precisely because one is, so a default would hand one repo the other's premise and report it measured.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lab_commons.dev.famconfig import (
    ABSENT,
    BASES,
    INSTALLED,
    RENDERED,
    artefact_base,
    delta_problems,
    inspect_file,
    measured_delta,
    render,
)
from lab_commons.dev.famtests._configrender_readings import (
    HookStages,
    Reopening,
    StagePartition,
    StageResolver,
    UnresolvedHooks,
    assert_floor,
    declared_hook_ids,
    reopenings,
    resolved_stages,
    stage_partition,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

    from lab_commons.dev.famconfig import Base, Delta

__all__ = [
    'HookStages',
    'Reopening',
    'StagePartition',
    'StageResolver',
    'UnresolvedHooks',
    'assert_artefact_is_rendered',
    'assert_declared_ids_survive',
    'assert_delta_is_not_a_fork',
    'assert_every_base_is_accounted_for',
    'assert_modes_are_as_agreed',
    'assert_no_base_line_left_undeclared',
    'assert_no_rule_is_reopened',
    'assert_pre_push_premise',
    'assert_render_round_trips',
    'assert_stage_declaration',
    'declared_hook_ids',
    'reopenings',
    'resolved_stages',
    'stage_partition',
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

    :func:`~lab_commons.dev.famconfig.inspect_file` RAISES on a malformed delta, which is right for a
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


def assert_declared_ids_survive(*, config: Path, extra_hook_ids: Iterable[str], hook_floor: int) -> None:
    """The named set's SUBJECT, read off the live artefact rather than restated from the declaration.

    A set that only ever agreed with itself stays green through losing every hook it names. The floor
    is what stops the subset check passing against a file that parsed to nothing.
    """
    declared = declared_hook_ids(config)
    if declared is None:
        msg = f'{config} could not be read, so no hook id was checked. That is INCONCLUSIVE, not clean.'
        raise AssertionError(msg)
    assert_floor(len(declared), hook_floor, f'{config.name} hook ids')
    missing = sorted(set(extra_hook_ids) - declared)
    if missing:
        msg = (
            f"{missing} are declared as this repo's extra hook ids and {config.name} no longer carries "
            f'them. Either the block shrank, so correct the named set, or an upgrade lost the hooks.'
        )
        raise AssertionError(msg)


def assert_stage_declaration(
    *,
    config: Path,
    resolve: StageResolver,
    hook_floor: int,
    narrowed: frozenset[str],
    keeps_pre_push: frozenset[str],
) -> None:
    """The behaviour change a ``default_stages`` adoption made, MEASURED against the real engine.

    BOTH SETS ARE EQUALITIES, not subsets, and that is the whole shape. A declaration listing only what
    moved cannot see a hook silently JOINING the move, and one listing only what survived cannot see a
    hook silently leaving. An EMPTY set is a legitimate declaration and must be SPELLED: "we measured
    and none narrowed" is a different act from never asking, and only the first can be checked.
    """
    hooks = resolved_stages(config, resolve=resolve)
    if len(hooks) < hook_floor:
        msg = (
            f'the engine resolved {len(hooks)} hooks from {config.name}, below the {hook_floor} floor. A '
            f'stage table read off a config that resolved to nothing agrees with every claim about it.'
        )
        raise UnresolvedHooks(msg)
    measured = stage_partition(hooks)
    for label, live, declared in (
        ('narrowed to pre-commit alone', measured.narrowed, narrowed),
        ('still reaching pre-push', measured.pre_push, keeps_pre_push),
    ):
        if live != declared:
            msg = (
                f'the hooks {label} are {sorted(live)} and this repo declares {sorted(declared)}. Extra in '
                f'the engine ({sorted(live - declared)}) is a hook whose stages moved with nobody saying '
                f'so; extra in the declaration ({sorted(declared - live)}) outlived its cause.'
            )
            raise AssertionError(msg)


def assert_pre_push_premise(*, hooks_dir: Path, pre_push_installed: bool) -> None:
    """WHETHER THIS CHECKOUT HAS A PRE-PUSH HOOK, pinned in whichever direction the repo declared.

    The premise a stage narrowing rests on, and this file's clearest no-default fact: one lab adopts
    ``default_stages: [pre-commit]`` for free because nothing runs at push there, and the other records
    the identical change as a REAL loss because something does. The difference is the INSTALLATION, not
    the config, so BOTH directions red -- installing a hook where none was declared is the right moment
    to re-decide the narrowing rather than to discover it later as a miss.
    """
    if not hooks_dir.is_dir():
        msg = f'no hooks directory at {hooks_dir}; this guard looked nowhere and is not reporting a clean tree'
        raise AssertionError(msg)
    live = (hooks_dir / 'pre-push').exists()
    if live and not pre_push_installed:
        msg = (
            f'a pre-push hook is installed at {hooks_dir} and this repo declares none. Every stage the base '
            f'takes off a stock hook has stopped being free: re-measure the adoption, declare `stages:` on '
            f'what this repo wants at push, or record the loss as a drop with its reason.'
        )
        raise AssertionError(msg)
    if pre_push_installed and not live:
        msg = (
            f'this repo declares a pre-push hook and none is installed at {hooks_dir}. The premise that made '
            f'the stage declaration a real loss is gone; its measurement describes a checkout that is gone.'
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
