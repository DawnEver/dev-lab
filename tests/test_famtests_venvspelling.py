"""Adoption of the venv-spelling guard HERE, plus the arms that judge the guard itself.

The shared bodies live in :mod:`lab_commons.dev.famtests.venvspelling`; what is here is this
repo's own answers -- which tree, which floor -- and the controls that prove the reader convicts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lab_commons.dev.famtests.venvspelling import (
    SANCTIONED_SPELLERS,
    Spelling,
    assert_a_planted_recipe_is_convicted,
    assert_only_the_resolver_spells_a_venv_interpreter,
    assert_the_resolver_is_still_consulted,
    scannable_text,
    spellings_in,
)
from lab_commons.dev.floors import FloorUnmet
from lab_commons.dev.venvpath import (
    CANDIDATE_RELATIVE_PATHS,
    VENV_INTERPRETER_GLOB,
    VENV_LAYOUTS,
    UnknownPlatform,
    current_os_name,
    hardcoded_spellings,
    portable,
    venv_interpreter,
)

#: This repo's kit source, the population the guard judges here.
SOURCE = Path(__file__).resolve().parent.parent / 'src'

#: MEASURED 2026-09-19 at 114 files under ``src``. The floor is on FILES READ: a walk that lost its
#: root reports exactly what a clean tree reports, and this scan's whole value is its silence.
FILE_FLOOR = 90


def _tree() -> dict[str, str]:
    """The kit as ``{repo-relative POSIX path: source}`` -- this repo's answer for the population."""
    return {path.relative_to(SOURCE).as_posix(): path.read_text(encoding='utf-8') for path in SOURCE.rglob('*.py')}


def test_only_the_resolver_spells_a_venv_interpreter() -> None:
    """THE PROPERTY. No file outside the sanctioned set spells a concrete venv interpreter."""
    assert_only_the_resolver_spells_a_venv_interpreter(files=_tree(), floor=FILE_FLOOR, what='lab-commons kit module')


def test_the_reader_convicts_a_planted_recipe_and_spares_the_narrative() -> None:
    """THE CONTROL, shared and taking no argument -- see the body for its three plants."""
    assert_a_planted_recipe_is_convicted()


def test_the_resolver_is_still_consulted() -> None:
    """THE OTHER SIDE. A resolver nothing calls is as wrong as a hardcoded path, and is silent."""
    assert_the_resolver_is_still_consulted()


def test_the_scan_has_a_floor_that_a_lost_root_trips() -> None:
    """A SCAN THAT READ NOTHING IS NOT A CLEAN SCAN -- the floor refuses, rather than passing."""
    with pytest.raises(FloorUnmet):
        assert_only_the_resolver_spells_a_venv_interpreter(files={}, floor=FILE_FLOOR, what='lab-commons kit module')


def test_the_floor_still_binds_on_the_tree_it_was_measured_against() -> None:
    """The high side, stated as the margin rather than as a second magic number."""
    read = len(_tree())
    assert read >= FILE_FLOOR, f'{read} files read, below the floor {FILE_FLOOR}'
    assert read - FILE_FLOOR <= 40, (
        f'{read} kit modules against a floor of {FILE_FLOOR}: the floor has been outgrown and no longer '
        f'separates a clean walk from a broken one. RE-MEASURE the floor; never widen this margin.'
    )


def test_the_sanctioned_set_is_named_and_is_exactly_the_resolver() -> None:
    """A NAMED SET, and EQUALITY -- a superset pin cannot say which module stopped resolving."""
    assert frozenset({'lab_commons/dev/venvpath.py'}) == SANCTIONED_SPELLERS


@pytest.mark.parametrize('os_name', sorted(VENV_LAYOUTS))
def test_both_platform_branches_resolve_on_whichever_box_runs_this(os_name: str) -> None:
    """BOTH BRANCHES, ON A WINDOWS BOX. The signal is an argument, which is the whole point.

    This family has no macOS machine in the loop, so a resolver reading ``os.name`` internally
    would ship with its POSIX half never once executed. Taking the platform as an argument with no
    default is what makes this arm possible, and it is the only honest cross-platform claim
    available from here: the PATH is asserted, the macOS filesystem is not.
    """
    resolved = venv_interpreter(os_name=os_name)
    assert resolved == '/'.join(VENV_LAYOUTS[os_name])
    assert '\\' not in resolved, 'a tracked artefact carries POSIX separators on both platforms'
    assert tuple(resolved.split('/')) in CANDIDATE_RELATIVE_PATHS


def test_an_unknown_platform_is_refused_rather_than_defaulted() -> None:
    """A guessed layout hands back a path that does not exist and reports a missing venv."""
    with pytest.raises(UnknownPlatform):
        venv_interpreter(os_name='vms')


def test_this_box_resolves_through_the_same_door() -> None:
    """``current_os_name`` is the ONE reader, so nothing else imports ``os`` to ask."""
    assert venv_interpreter(os_name=current_os_name()) in {'/'.join(p) for p in CANDIDATE_RELATIVE_PATHS}


@pytest.mark.parametrize(
    ('command', 'expected'),
    [
        ('./.venv/Scripts/python.exe -m lab_commons.dev.verify', f'./{VENV_INTERPRETER_GLOB} -m lab_commons.dev.verify'),  # noqa: E501 -- the two spellings must sit side by side to be read as a pair
        ('./.venv/bin/python -m lab_commons.dev.verify', f'./{VENV_INTERPRETER_GLOB} -m lab_commons.dev.verify'),
        ('.venv\\Scripts\\python.exe x', f'{VENV_INTERPRETER_GLOB} x'),
        ('.venv/bin/python3.12 x', f'{VENV_INTERPRETER_GLOB} x'),
        ('git push --force', 'git push --force'),
    ],
)
def test_portable_normalises_every_spelling_and_leaves_the_rest_alone(command: str, expected: str) -> None:
    """Both layouts and both separators converge; a command naming no interpreter is untouched."""
    assert portable(command) == expected


def test_the_leading_anchor_survives_the_rewrite() -> None:
    """``./`` is the difference between THIS checkout's venv and whatever a lookup finds.

    ``glob_for``'s own rule is that nothing is prepended to a remedy; a rewriter that silently
    dropped the anchor would widen every row it touched, which is the opposite of that rule.
    """
    assert portable('./.venv/bin/python x').startswith('./')
    assert not portable('.venv/bin/python x').startswith('./')


def test_the_reader_reports_every_occurrence_and_keeps_duplicates() -> None:
    """The caller reports LINES, so two spellings on one line are two repairs rather than one."""
    both = '.venv/bin/python and .venv/Scripts/python.exe'
    assert len(hardcoded_spellings(both)) == 2
    assert hardcoded_spellings('git status') == ()


def test_a_code_site_and_a_recipe_site_are_told_apart() -> None:
    """The two carry different repairs, so a finding NAMES which rather than reporting a location."""
    windows = venv_interpreter(os_name='nt')
    code = spellings_in({'x.py': f'PATH = "{windows}"\n'})
    recipe = spellings_in({'x.py': f'"""D.\n\nRun::\n\n    PATH = "{windows}"\n"""\n'})
    assert [item.where for item in code] == ['code']
    assert [item.where for item in recipe] == ['recipe']
    assert isinstance(code[0], Spelling)


def test_an_unparseable_file_yields_nothing_rather_than_stopping_the_walk() -> None:
    """A fixture that does not parse is another guard's business, not a reason this one cannot read."""
    assert scannable_text('def (:\n') == ()


def test_a_comment_is_not_scanned_because_nobody_pastes_one_as_code() -> None:
    """Comments record the retirement; the replacement is named in ``venvpath``."""
    windows = venv_interpreter(os_name='nt')
    assert not spellings_in({'x.py': f'# it used to read {windows} here\nX = 1\n'})
