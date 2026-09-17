"""The install-door guard, driven by PLANTED doors -- including the three real ones measured today.

WHY EVERY CONTROL HERE IS PLANTED RATHER THAN READ OFF A TREE. The hazard is a command that LOOKS
like a correct one: `uv run python -m x` and `uv run --no-sync python -m x` differ by one flag and by
a whole environment. A scan run over a clean repo cannot tell whether it refuses that difference or
merely never met it, so each row of the measured table in :mod:`lab_commons.dev.installdoor` is
planted here and pushed through the REAL classifier.

THE THREE REAL DOORS, quoted verbatim from the checkouts they were measured in on 2026-09-17, are in
`_MEASURED` below -- two that reverted and one that did not. They are the reason the rule exists, so
they are the cases that may never quietly start passing or failing differently.

THIS REPO DECLARES NO FLOATING REQUIREMENT -- it IS the shared kit -- so its own doors can deliver
nothing stale today. The rule is still ENFORCED here rather than waived, and the last test in this
file is why: it reads this repo's manifest and this repo's declared door files, so the day a bare
`git+` requirement lands here the CI `uv sync` it already scans stops being inert and reds. The
planted trees above are what prove the guard can FAIL; that test is what keeps it pointed at a
subject that has not arrived yet.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from lab_commons.dev.installdoor import (
    Delivery,
    RevertingDoors,
    VacuousDoorScan,
    assert_doors_deliver,
    classify,
    commands,
    floating_requirements,
    reverting,
    scan_doors,
)

#: The one floating requirement every repo in this family declares. A tuple, because the API takes a
#: SET of names: a repo declaring two of them must name both for re-resolution or it has delivered
#: one stale.
_KIT: tuple[str, ...] = ('lab-commons',)

#: THE MEASURED ROWS, verbatim. Left column: the command as it was written. Right: what it delivered
#: against a venv holding dev40 with the remote at dev42, measured 2026-09-17 with uv 0.12.5.
_MEASURED: tuple[tuple[str, Delivery], ...] = (
    # wdg-lab/.pre-commit-config.yaml, pre-push. Reverted the kit on every push.
    ('uv run python -m lab_commons.dev.githooks bump-version', Delivery.REVERTS),
    # wdg-lab/scripts/githooks/generate-changelog.sh. Reverted it on every commit.
    ('uv run python -m commitizen changelog', Delivery.REVERTS),
    # wdg-lab/Makefile install-dev -- the door everyone suspected, and it was never the defect.
    ('uv pip install -e ".[dev,web,rust,cad3d,full]"', Delivery.RESOLVES),
)

#: Every other shape the classifier must decide, with the fact each one is decided by.
_PLANTED: tuple[tuple[str, Delivery], ...] = (
    ('uv sync', Delivery.REVERTS),
    ('uv sync --extra dev --extra web', Delivery.REVERTS),
    ('uv sync -P lab-commons', Delivery.RESOLVES),
    ('uv sync --upgrade-package lab-commons --extra dev', Delivery.RESOLVES),
    ('uv sync --upgrade-package=lab-commons', Delivery.RESOLVES),
    ('uv sync -U', Delivery.RESOLVES),
    ('uv run --no-sync python -m commitizen changelog', Delivery.INERT),
    ('uv add ruff', Delivery.REVERTS),
    ('uv lock', Delivery.INERT),
    ('uv lock --upgrade-package=lab-commons', Delivery.RESOLVES),
    ('uv --native-tls sync', Delivery.REVERTS),
    ('uv pip install -U pip wheel', Delivery.RESOLVES),
    ('uv pip list', Delivery.INERT),
    ('uvx ruff check', Delivery.INERT),
    ('uvx pre-commit install', Delivery.INERT),
    ('pip install "lab-commons @ git+https://example.invalid/x.git"', Delivery.RESOLVES),
    ('python -m pip install -e .', Delivery.RESOLVES),
    ('python -m pytest', Delivery.INERT),
    ('maturin develop --release', Delivery.INERT),
)


def _argv(command: str) -> list[str]:
    return shlex.split(command)


@pytest.mark.parametrize(('command', 'expected'), _MEASURED)
def test_the_three_measured_doors_are_classified_as_they_behaved(command: str, expected: Delivery) -> None:
    """The rows that made the rule. `uv pip install` is RESOLVES on purpose -- it was not the defect."""
    assert classify(_argv(command), _KIT) is expected


@pytest.mark.parametrize(('command', 'expected'), _PLANTED)
def test_the_classifier_decides_every_planted_shape(command: str, expected: Delivery) -> None:
    """One flag apart is a whole environment apart, so each neighbouring pair is planted."""
    assert classify(_argv(command), _KIT) is expected


def test_a_repo_with_no_floating_requirement_has_no_door_to_get_wrong() -> None:
    """The rule's subject is the REQUIREMENT. With none declared, a lock can hold nothing back."""
    assert classify(_argv('uv sync'), ()) is Delivery.INERT
    assert classify(_argv('uv run python -c pass'), ()) is Delivery.INERT


def test_naming_only_one_of_two_floating_requirements_still_reverts_the_other() -> None:
    """`-P` is per package, so a partial upgrade delivers the unnamed one stale."""
    two = ('lab-commons', 'optimi-lab')
    assert classify(_argv('uv sync -P lab-commons'), two) is Delivery.REVERTS
    assert classify(_argv('uv sync -P lab-commons -P optimi-lab'), two) is Delivery.RESOLVES


def test_a_command_quoted_inside_another_is_not_a_door() -> None:
    """The too-loose half of a spelling blocklist, refused: a mention is not an invocation."""
    text = 'python -c "print(\'uv sync\')"\necho "run uv sync to install"\n'
    found = [argv for _line, argv in commands(text)]
    assert [argv[0] for argv in found] == ['python'], found
    assert classify(found[0], _KIT) is Delivery.INERT


def test_a_comment_explaining_a_door_is_not_a_second_door() -> None:
    """A Makefile that argues for its own shape must not be read as running what it describes."""
    text = '# the runtime target deliberately does not run uv sync here\n\tuv sync -P lab-commons\n'
    assert [argv for _line, argv in commands(text)] == [['uv', 'sync', '-P', 'lab-commons']]


def test_a_wrapped_command_is_still_the_command() -> None:
    """`timeout`, `if !`, and a YAML `entry:` all leave a program a program."""
    text = 'timeout 900 uv sync\nif ! /root/.local/bin/uv pip install -e .; then\n    entry: uv run python -m x\n'
    found = {argv[0]: classify(argv, _KIT) for _line, argv in commands(text)}
    assert found == {
        'uv': Delivery.REVERTS,
        '/root/.local/bin/uv': Delivery.RESOLVES,
    }, found


def test_floating_requirements_reads_both_tables_and_ignores_every_pinned_shape(tmp_path: Path) -> None:
    """A ref of ANY spelling is a pin, and a pinned requirement is not this rule's subject."""
    manifest = tmp_path / 'pyproject.toml'
    manifest.write_text(
        '[project]\n'
        'name = "x"\n'
        'dependencies = [\n'
        '  "numpy",\n'
        '  "lab-commons @ git+https://example.invalid/lab-commons.git",\n'
        '  "pinned-sha @ git+https://example.invalid/a.git@0123abc",\n'
        '  "pinned-tag @ git+https://example.invalid/b.git?tag=v1",\n'
        ']\n'
        '[project.optional-dependencies]\n'
        'dev = ["optimi-lab[dev] @ git+https://example.invalid/optimi-lab"]\n',
        encoding='utf-8',
    )
    assert floating_requirements(manifest) == ('lab-commons', 'optimi-lab')


def test_a_missing_manifest_raises_rather_than_answering_none(tmp_path: Path) -> None:
    """ "No floating requirement" is the reading under which every door passes, so it must not be free."""
    with pytest.raises(OSError, match='pyproject'):
        floating_requirements(tmp_path / 'pyproject.toml')


#: THIS repo's own install doors, declared as a named set. `python-verify.yml` is here because it
#: RUNS in every caller's checkout, so its `uv sync` is a door of this tree even though the
#: environment it moves is somebody's CI runner.
_OWN_DOORS: tuple[str, ...] = ('Makefile', '.github/workflows/ci.yml', '.github/workflows/python-verify.yml')

#: MEASURED 2026-09-17: 9 installer-capable commands across those three files. The floor is under it
#: because "no reverting door" over a set that was never read is the vacuous green this family refuses.
_OWN_DOOR_FLOOR = 5


def test_this_repos_own_doors_are_inert_because_it_declares_no_floating_requirement() -> None:
    """lab-commons IS the kit, so nothing it installs can be held back by a lock -- CHECKED, not said.

    The claim is live rather than decorative: add a bare `git+` requirement to this repo's manifest
    and the CI `uv sync` above stops being INERT, which is exactly the day the rule acquires a
    subject here.
    """
    root = Path(__file__).resolve().parents[1]
    names = floating_requirements(root / 'pyproject.toml')
    assert names == (), f'{list(names)} are declared floating here, so the doors below now have a subject'
    doors = assert_doors_deliver(root, list(_OWN_DOORS), names, floor=_OWN_DOOR_FLOOR)
    assert {door.delivery for door in doors} == {Delivery.INERT}


def _plant(root: Path, *, door: str) -> None:
    (root / 'Makefile').write_text(f'install-dev:\n\t{door}\n', encoding='utf-8')
    (root / 'hook.sh').write_text('uv run python -m commitizen changelog\n', encoding='utf-8')


def test_the_guard_fires_on_a_planted_reverting_door(tmp_path: Path) -> None:
    """THE PLANTED CONTROL. A reverting door in a real tree, through the REAL guard, and it refuses."""
    _plant(tmp_path, door='uv sync --extra dev')
    with pytest.raises(RevertingDoors) as refusal:
        assert_doors_deliver(tmp_path, ['Makefile', 'hook.sh'], _KIT, floor=2)
    message = str(refusal.value)
    assert 'Makefile:2' in message and 'hook.sh:1' in message
    assert '--upgrade-package lab-commons' in message and '--no-sync' in message


def test_the_guard_passes_once_both_remedies_are_applied(tmp_path: Path) -> None:
    """The other side: apply the two remedies the refusal NAMED and the same guard goes green."""
    _plant(tmp_path, door='uv sync --extra dev -P lab-commons')
    (tmp_path / 'hook.sh').write_text('uv run --no-sync python -m commitizen changelog\n', encoding='utf-8')
    doors = assert_doors_deliver(tmp_path, ['Makefile', 'hook.sh'], _KIT, floor=2)
    assert {door.delivery for door in doors} == {Delivery.RESOLVES, Delivery.INERT}
    assert reverting(doors) == ()


def test_the_scan_refuses_to_report_a_clean_tree_it_never_read(tmp_path: Path) -> None:
    """A renamed door file must red as INCONCLUSIVE rather than pass having read nothing."""
    _plant(tmp_path, door='uv sync -P lab-commons')
    with pytest.raises(VacuousDoorScan, match='below the floor'):
        assert_doors_deliver(tmp_path, ['Makefile.renamed', 'hook.sh.renamed'], _KIT, floor=2)


def test_a_door_carries_the_file_and_the_line_a_reader_opens(tmp_path: Path) -> None:
    """A refusal that cannot be navigated to sends a reader looking, and looking is where they stop."""
    _plant(tmp_path, door='uv sync')
    doors = scan_doors(tmp_path, ['Makefile', 'hook.sh'], _KIT)
    assert [door.describe() for door in doors] == [
        'Makefile:2 -- uv sync',
        'hook.sh:1 -- uv run python -m commitizen changelog',
    ]
