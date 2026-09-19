"""THE READER, driven over PLANTED manifests and PLANTED commands, never over an environment.

Every control here is the edit somebody actually made or would make, run through the real functions.
Nothing installs, syncs or prunes -- the defect under study is a prune, and re-running it would
destroy a working box, so the whole suite is a statement about TEXT and declared config.

The manifest below is motronics' shape reduced to what decides the answer: an `all` extra that is a
SELF-REFERENCE to six other extras and carries no `dev`, a `dev` extra holding the runner, an
`addopts` naming two plugins, and an extra deliberately outside `all`. That is the incident of
2026-09-18 in fourteen lines.
"""

from __future__ import annotations

import pytest

from lab_commons.dev.syncscope import (
    Scope,
    Selection,
    UnknownExtraError,
    canon,
    declares_groups,
    extras,
    scope,
    selection,
    stranded,
    survivors,
    verdict_set,
)

#: The motronics shape: `all` expands through the project's own name and does NOT include `dev`.
MANIFEST = """
[project]
name = "motronics"
dependencies = ["numpy", "lab-commons @ git+https://github.com/DawnEver/lab-commons.git"]

[project.optional-dependencies]
euclid = ["gmsh", "wdg-lab[web] @ git+https://example.invalid/wdg-lab.git"]
pareto = ["optimi-lab @ git+https://example.invalid/optimi-lab"]
femm = ["pywin32; sys_platform == 'win32'"]
all = ["motronics[euclid,pareto,femm]"]
img-to-cad = ["opencv-python-headless"]
dev = ["pytest", "pytest-xdist", "pytest-timeout", "ruff"]

[tool.pytest.ini_options]
addopts = "-n auto --dist loadgroup"
timeout = 300
"""


def _selecting(*names: str) -> Selection:
    """A selection that PRUNES and names *names* -- the shape every row in the census carries."""
    return Selection(prunes=True, extras=frozenset(canon(name) for name in names))


def test_an_extra_that_references_its_own_project_is_expanded() -> None:
    """THE FACT THAT MADE THE INCIDENT EXPENSIVE: `all` reads as one distribution and installs six."""
    table = extras(MANIFEST)
    assert table['all'] == {'gmsh', 'wdg-lab', 'optimi-lab', 'pywin32'}
    assert 'motronics' not in table['all'], 'the self-reference was counted as a distribution rather than followed'
    assert table['img-to-cad'] == {'opencv-python-headless'}, 'the extra outside `all` is still declared'


def test_the_verdict_set_is_derived_from_the_repos_own_pytest_configuration() -> None:
    """A plugin named in `addopts` is load-bearing: pytest exits 4 -- no verdict -- on an unknown option."""
    assert verdict_set(MANIFEST) == {'pytest', 'pytest-xdist', 'pytest-timeout', 'ruff', 'lab-commons'}


def test_a_manifest_naming_no_plugin_needs_only_the_runner_and_the_linter() -> None:
    """THE OTHER SIDE: the set must shrink when the configuration does, or it is a typed-out constant."""
    plain = '[project]\nname = "kit"\ndependencies = []\n\n[project.optional-dependencies]\ndev = ["pytest"]\n'
    assert verdict_set(plain) == {'pytest', 'ruff'}


def test_the_kit_is_not_made_to_depend_on_itself() -> None:
    """lab-commons declares no lab-commons; reading its own name into its verdict set would be a lie."""
    kit = '[project]\nname = "lab-commons"\ndependencies = []\n\n[project.optional-dependencies]\ndev = ["pytest"]\n'
    assert 'lab-commons' not in verdict_set(kit)


def test_the_incident_is_refused_a_bare_sync_strands_the_runner() -> None:
    """THE CONTROL FOR THE WHOLE MODULE: `--sync` with no `--extra`, 113 distributions to 30."""
    bare = _selecting()
    assert scope(bare, MANIFEST) is Scope.STRANDS
    assert stranded(bare, MANIFEST) == ('pytest', 'pytest-timeout', 'pytest-xdist', 'ruff')


def test_extra_all_strands_the_runner_because_all_is_a_fact_about_the_manifest() -> None:
    """The remedy that reads as safe. `all` is whatever the project says it is, and here it omits `dev`."""
    assert scope(_selecting('all'), MANIFEST) is Scope.STRANDS
    assert scope(_selecting('all', 'dev'), MANIFEST) is Scope.COMPLETE
    assert scope(_selecting('all', 'dev', 'img-to-cad'), MANIFEST) is Scope.COMPLETE


def test_an_extra_the_manifest_does_not_declare_is_refused_rather_than_read_as_none() -> None:
    """`--extra all` is right in one repo and names nothing in another; reading it as empty answers nothing."""
    with pytest.raises(UnknownExtraError, match='all'):
        survivors(_selecting('all'), '[project]\nname = "kit"\n\n[project.optional-dependencies]\ndev = []\n')


def test_all_extras_keeps_everything_declared() -> None:
    """`--all-extras` is the one selection that cannot strand: it is the union of the table."""
    assert scope(Selection(prunes=True, all_extras=True), MANIFEST) is Scope.COMPLETE


@pytest.mark.parametrize(
    ('argv', 'prunes'),
    [
        (['uv', 'sync', '--extra', 'dev'], True),
        (['uv', 'sync'], True),
        (['uv', 'run', 'pytest'], True),
        (['uv', 'run', '--no-sync', 'make', 'verify'], False),
        (['uv', 'sync', '--inexact', '--extra', 'dev'], False),
        (['uv', 'pip', 'install', '-e', '.[dev]'], False),
        (['python', '-m', 'pip', 'install', 'ruff'], False),
        (['uv', 'lock'], False),
    ],
)
def test_which_commands_move_a_population(argv: list[str], *, prunes: bool) -> None:
    """One row per line of the measured table in the module docstring, through the real reader."""
    assert selection(argv).prunes is prunes


def test_only_uvs_own_flags_select_extras() -> None:
    """`uv run pytest --extra x` passes that flag to the CHILD; reading it would invent a selection."""
    assert selection(['uv', 'run', '--extra', 'dev', 'pytest']).extras == {'dev'}
    assert selection(['uv', 'run', 'pytest', '--extra', 'dev']).extras == frozenset()
    assert selection(['uv', 'run', '--python', '3.12', 'pytest', '--extra', 'dev']).extras == frozenset()
    assert selection(['uv', 'sync', '--extra=dev']).extras == {'dev'}


def test_a_selection_composed_elsewhere_is_unmeasured_and_not_empty() -> None:
    """THE HONEST BLIND SPOT: `$extra_flags` is not "no extras", and the two have opposite remedies."""
    chosen = selection(['uv', 'sync', '--extra', '$EXTRA'])
    assert chosen.unresolved == ('$EXTRA',)
    assert scope(chosen, MANIFEST) is Scope.UNMEASURED
    assert scope(_selecting(), MANIFEST) is Scope.STRANDS, 'a bare sync must stay a finding, not a blind spot'


def test_a_dependency_group_makes_the_answer_unmeasured_rather_than_confident() -> None:
    """An axis this reader does not model must say so. `--no-dev` is about GROUPS, not about a `dev` EXTRA."""
    with_group = MANIFEST + '\n[dependency-groups]\ndev = ["pytest"]\n'
    assert declares_groups(with_group)
    assert not declares_groups(MANIFEST)
    assert scope(_selecting(), with_group) is Scope.UNMEASURED


def test_a_verdict_distribution_supplied_only_under_a_marker_is_unmeasured() -> None:
    """A platform-conditional runner is not a property of the manifest, so it is not scored as present."""
    marked = MANIFEST.replace('dev = ["pytest",', 'dev = ["pytest; sys_platform == \'win32\'",')
    assert scope(_selecting('dev'), marked) is Scope.UNMEASURED
    assert scope(_selecting('dev'), MANIFEST) is Scope.COMPLETE, 'the unmarked manifest must stay measurable'


def test_names_are_compared_after_normalisation() -> None:
    """`img_to_cad` and `img-to-cad` are one extra; comparing raw spellings reports a strand that is not there."""
    assert canon('Img_To.Cad') == 'img-to-cad'
    assert scope(_selecting('IMG_TO_CAD', 'dev'), MANIFEST) is Scope.COMPLETE
