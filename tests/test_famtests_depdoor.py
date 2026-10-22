"""``dev_lab.dev.famtests.depdoor`` -- every arm driven GREEN and driven RED.

WHY EACH ARM IS DRIVEN TWICE. This module publishes assertions, and an assertion that cannot fail is
the one defect no amount of green reveals. So each case below plants a repo that answers correctly
and the same repo with exactly one answer broken -- a port missing an adapter, an adapter that always
says "nobody", a reader that invents an anchor, a door handed a key that never moves.

THE FIXTURES ARE A REPO THAT DOES NOT EXIST, deliberately. The subject of this body is the consumer's
adapters, so the kit's own test supplies the smallest one that behaves like one: an anchor reader
over a glob. Environment seats are planted in an injected records directory; nothing is installed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from dev_lab.dev.dep import NO_ANCHORS_DECLARED, Port, mutate
from dev_lab.dev.famtests.depdoor import (
    A_REQUIREMENT,
    UNDECLARED_GAPS,
    Ran,
    assert_a_moved_key_retires_a_planted_anchor,
    assert_a_port_declaring_no_anchors_renders_the_gap,
    assert_a_verdict_in_another_environment_does_not_refuse,
    assert_an_unmoved_key_retires_nothing,
    assert_the_anchor_reader_has_a_floor_and_a_ceiling,
    assert_the_door_refuses_while_a_verdict_is_in_flight,
    assert_this_repo_declares_its_verdict_anchors,
    scripted_keys,
)

#: The fixture repo's name. Not one of the four real ones, so a body that closed over a family name
#: rather than reading its argument would red here rather than agreeing by coincidence.
_REPO = 'a-repo-under-test'

#: The fixture repo's verdict log shape, repo-relative, in the form a consumer spells it.
_ANCHOR_GLOB = '.verdicts/verify-*.log'


@pytest.fixture(autouse=True)
def isolated_environment_seats(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Planted installers must not contend with the real verifier running these controls."""
    monkeypatch.setenv('LAB_COMMONS_RESOURCE_DIR', str(tmp_path / 'environment-records'))


def _anchors(tree: Path) -> tuple[Path, ...]:
    """The fixture repo's anchor adapter: the verdict logs under *tree*, and nothing else."""
    directory = tree / Path(_ANCHOR_GLOB).parent
    if not directory.is_dir():
        return ()
    return tuple(sorted(directory.glob(Path(_ANCHOR_GLOB).name)))


def _port() -> Port:
    """The fixture repo's port factory -- anchors declared, which is the state under test."""
    return Port(name=_REPO, anchor_paths=lambda: ())


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """An EMPTY scratch checkout. The floor arm asserts on its emptiness before it plants."""
    directory = tmp_path / 'tree'
    directory.mkdir()
    return directory


def _plant_anchor(tree: Path, stamp: str) -> Path:
    """Write one verdict log of the fixture repo's own shape and return it."""
    anchor = tree / _ANCHOR_GLOB.replace('*', stamp)
    anchor.parent.mkdir(parents=True, exist_ok=True)
    anchor.write_text('VERDICT result=PASS env=planted\n', encoding='utf-8')
    return anchor


def test_the_gap_set_is_the_named_anchor_sentence() -> None:
    """THE FLOOR ON THE PIN ITSELF. An empty set would make the control vacuous."""
    assert frozenset({NO_ANCHORS_DECLARED}) == UNDECLARED_GAPS


def test_a_complete_port_renders_no_gap() -> None:
    """THE PROPERTY, on a repo that declares its anchors."""
    assert_this_repo_declares_its_verdict_anchors(port=_port, repo_name=_REPO)


def test_a_port_missing_the_anchor_adapter_reds() -> None:
    """PLANTED: an undeclared anchor reader. The property arm must convict, or it is asserting nothing."""
    with pytest.raises(AssertionError, match='NO VERDICT ANCHORS'):
        assert_this_repo_declares_its_verdict_anchors(port=lambda: Port(name=_REPO), repo_name=_REPO)


def test_a_report_that_does_not_name_the_repo_reds() -> None:
    """PLANTED: a complete door reporting under somebody else's name."""
    with pytest.raises(AssertionError, match='who changed what'):
        assert_this_repo_declares_its_verdict_anchors(port=_port, repo_name='a-name-the-port-never-uses')


def test_the_control_convicts_a_port_declaring_neither() -> None:
    """THE CONTROL, run as the consumer will run it."""
    assert_a_port_declaring_no_anchors_renders_the_gap()


def test_the_door_refuses_a_live_verdict() -> None:
    """H1 prevented, through the real door."""
    assert_the_door_refuses_while_a_verdict_is_in_flight(repo_name=_REPO, verdict_anchors=lambda: ())


def test_a_verdict_in_another_environment_is_no_refusal(tmp_path: Path) -> None:
    """The other side of H1, green: another repo's verify does not refuse this environment."""
    assert_a_verdict_in_another_environment_does_not_refuse(
        repo_name=_REPO, verdict_anchors=lambda: (), elsewhere=tmp_path / 'another' / '.venv'
    )


def test_a_machine_wide_guard_reds_the_other_environment_arm() -> None:
    """PLANTED: an environment arm handed THIS environment as "elsewhere" -- the over-broad guard -- reds."""
    with pytest.raises(AssertionError, match='refused a change'):
        assert_a_verdict_in_another_environment_does_not_refuse(
            repo_name=_REPO, verdict_anchors=lambda: (), elsewhere=Path(sys.prefix)
        )


def test_the_refusal_arm_has_no_plantable_red_and_that_is_recorded() -> None:
    """THE ONE ARM WHOSE RED IS NOT REACHABLE FROM ITS ARGUMENTS, measured rather than assumed.

    The first attempt here passed a *repo_name* the refusal would not carry, expecting a conviction.
    It did not convict, and the reason is structural: the arm BUILDS its planted holder out of
    *repo_name*, so the string it looks for in the refusal is by construction the string it put
    there. Every value of the one argument is green.

    That is not a hole to paper over with a stub -- ``mutate`` and ``HeldEnvironmentError`` are the
    subject, and a fake door would prove the fake. What IS asserted is the half that can be: the
    refusal must carry the word ``env_key``, which no argument of this arm supplies, so a refusal
    that stopped saying WHY a running verdict is at risk still reds. Driven here by asking the door
    the same question through a port with no holder at all, which must NOT raise -- the other side
    of the same ratchet, and the one a repo could really break.
    """
    quiet = Port(name=_REPO, anchor_paths=lambda: ())
    report = mutate(A_REQUIREMENT, port=quiet, dry_run=True)
    assert report.gaps == ()


def test_a_moved_key_retires_the_planted_anchor(tree: Path) -> None:
    """H2 remedied, and the file is really gone."""
    anchor = _plant_anchor(tree, '20260919T000000Z')
    assert_a_moved_key_retires_a_planted_anchor(
        repo_name=_REPO,
        verdict_anchors=lambda: _anchors(tree),
        anchor=anchor,
    )


def test_the_retirement_arm_reds_when_nothing_was_planted(tree: Path) -> None:
    """THE FLOOR. Retiring nothing and passing for it is the shape this refuses."""
    with pytest.raises(AssertionError, match='never planted'):
        assert_a_moved_key_retires_a_planted_anchor(
            repo_name=_REPO,
            verdict_anchors=lambda: _anchors(tree),
            anchor=tree / '.verdicts' / 'verify-nothing.log',
        )


def test_the_retirement_arm_reds_on_an_adapter_that_finds_nothing(tree: Path) -> None:
    """PLANTED: a real anchor and a reader blind to it -- the door retires nothing and says so."""
    anchor = _plant_anchor(tree, '20260919T000001Z')
    with pytest.raises(AssertionError, match='was retired'):
        assert_a_moved_key_retires_a_planted_anchor(
            repo_name=_REPO,
            verdict_anchors=lambda: (),
            anchor=anchor,
        )


def test_an_unmoved_key_retires_nothing(tree: Path) -> None:
    """THE OTHER SIDE OF THE RATCHET."""
    anchor = _plant_anchor(tree, '20260919T000002Z')
    assert_an_unmoved_key_retires_nothing(
        repo_name=_REPO,
        verdict_anchors=lambda: _anchors(tree),
        anchor=anchor,
    )


def test_the_unmoved_arm_reds_when_an_adapter_deletes_the_evidence(tree: Path) -> None:
    """PLANTED: an over-eager adapter that takes the verdict down while merely being READ.

    The key cannot be the plant here -- the arm supplies its own, which is what makes it a statement
    about the DOOR rather than about a fixture -- so the deletion is planted in the one place a repo
    could really put it: an adapter with a side effect. That is the concrete shape of "a retirement
    that always fires deletes evidence nobody invalidated".
    """
    anchor = _plant_anchor(tree, '20260919T000003Z')

    def destructive() -> tuple[Path, ...]:
        found = _anchors(tree)
        for path in found:
            path.unlink()
        return found

    with pytest.raises(AssertionError, match='took the live verdict'):
        assert_an_unmoved_key_retires_nothing(
            repo_name=_REPO,
            verdict_anchors=destructive,
            anchor=anchor,
        )


def test_the_unmoved_arm_reds_when_nothing_was_planted(tree: Path) -> None:
    """THE FLOOR. A door that deletes everything would pass an arm with no anchor to lose."""
    with pytest.raises(AssertionError, match='never planted'):
        assert_an_unmoved_key_retires_nothing(
            repo_name=_REPO,
            verdict_anchors=lambda: _anchors(tree),
            anchor=tree / '.verdicts' / 'verify-nothing.log',
        )


def test_the_anchor_reader_has_a_floor_and_a_ceiling(tree: Path) -> None:
    """The fixture reader finds the real shape, ignores a stray, and invents nothing."""
    assert_the_anchor_reader_has_a_floor_and_a_ceiling(
        verdict_anchors=_anchors,
        anchor_glob=_ANCHOR_GLOB,
        tree=tree,
    )


def test_a_reader_that_finds_nothing_reds(tree: Path) -> None:
    """THE FLOOR. Without it every retirement arm above retires a shape the repo never writes."""
    with pytest.raises(AssertionError, match='really writes'):
        assert_the_anchor_reader_has_a_floor_and_a_ceiling(
            verdict_anchors=lambda _: (),
            anchor_glob=_ANCHOR_GLOB,
            tree=tree,
        )


def test_a_reader_that_takes_a_stray_file_reds(tree: Path) -> None:
    """THE CEILING. A reader that globs everything hands the door a file to delete."""

    def greedy(tree: Path) -> tuple[Path, ...]:
        directory = tree / Path(_ANCHOR_GLOB).parent
        return tuple(sorted(directory.iterdir())) if directory.is_dir() else ()

    with pytest.raises(AssertionError, match='was read as a verdict'):
        assert_the_anchor_reader_has_a_floor_and_a_ceiling(
            verdict_anchors=greedy,
            anchor_glob=_ANCHOR_GLOB,
            tree=tree,
        )


def test_the_floor_arm_refuses_a_tree_that_is_not_empty(tree: Path) -> None:
    """A dirty scratch tree makes the empty-tree reading a reading of something else."""
    _plant_anchor(tree, '20260919T000004Z')
    with pytest.raises(AssertionError, match='is not empty'):
        assert_the_anchor_reader_has_a_floor_and_a_ceiling(
            verdict_anchors=_anchors,
            anchor_glob=_ANCHOR_GLOB,
            tree=tree,
        )


def test_the_run_stand_in_installs_nothing_and_reports_its_argv() -> None:
    """:class:`Ran` records the argv it was HANDED and never composes one."""
    ran = Ran()
    assert ran(['python', '-m', 'pip', 'install', 'x'], check=False).returncode == 0
    assert ran.calls == [['python', '-m', 'pip', 'install', 'x']]


def test_the_scripted_key_moves_once_and_then_settles() -> None:
    """A port called more often than the script is long answers a settled environment, never raises."""
    key = scripted_keys('before', 'after')
    assert [key(), key(), key()] == ['before', 'after', 'after']


def test_the_requirement_is_not_empty() -> None:
    """FLOOR. The door refuses an empty requirement list, so an empty constant would red every arm."""
    assert A_REQUIREMENT
