"""``lab_commons.dev.famtests.depdoor`` -- every arm driven GREEN and driven RED.

WHY EACH ARM IS DRIVEN TWICE. This module publishes assertions, and an assertion that cannot fail is
the one defect no amount of green reveals. So each case below plants a repo that answers correctly
and the same repo with exactly one answer broken -- a port missing an adapter, an adapter that always
says "nobody", a reader that invents an anchor, a door handed a key that never moves.

THE FIXTURES ARE A REPO THAT DOES NOT EXIST, deliberately. The subject of this body is the consumer's
adapters, so the kit's own test supplies the smallest pair that behaves like one: a holders adapter
over a real :class:`~lab_commons.dev.boxlock.BoxLock` in an injected records directory, and an anchor
reader over a glob. Nothing here is installed and no real box seat is taken.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lab_commons.dev.boxlock import BoxLock
from lab_commons.dev.dep import Port
from lab_commons.dev.famtests.depdoor import (
    A_REQUIREMENT,
    BOTH_GAPS,
    Ran,
    assert_a_moved_key_retires_a_planted_anchor,
    assert_a_port_declaring_neither_renders_both_gaps,
    assert_an_unmoved_key_retires_nothing,
    assert_the_anchor_reader_has_a_floor_and_a_ceiling,
    assert_the_door_refuses_while_a_verdict_is_in_flight,
    assert_the_holders_adapter_names_a_planted_holder,
    assert_this_repo_supplies_both_halves_of_the_door,
    scripted_keys,
)
from lab_commons.resources import Broker

#: The fixture repo's name. Not one of the four real ones, so a body that closed over a family name
#: rather than reading its argument would red here rather than agreeing by coincidence.
_REPO = 'a-repo-under-test'

#: The fixture repo's verdict log shape, repo-relative, in the form a consumer spells it.
_ANCHOR_GLOB = '.verdicts/verify-*.log'


def _anchors(tree: Path) -> tuple[Path, ...]:
    """The fixture repo's anchor adapter: the verdict logs under *tree*, and nothing else."""
    directory = tree / Path(_ANCHOR_GLOB).parent
    if not directory.is_dir():
        return ()
    return tuple(sorted(directory.glob(Path(_ANCHOR_GLOB).name)))


def _holders(*, broker: Broker) -> tuple[str, ...]:
    """The fixture repo's holders adapter: the box seat, named as the door will print it."""
    return tuple(f'{holder.what} since={holder.since}' for holder in BoxLock.holders(broker=broker))


def _port(*, broker: Broker) -> Port:
    """The fixture repo's port factory -- both halves answered, which is the state under test."""
    return Port(name=_REPO, holders=lambda: _holders(broker=broker), anchor_paths=lambda: ())


@pytest.fixture
def records(tmp_path: Path) -> Broker:
    """A broker over an ISOLATED records directory, so a plant contends only with its own case."""
    directory = tmp_path / 'records'
    directory.mkdir()
    return Broker(resource_dir=directory)


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


def test_the_gap_set_is_two_named_sentences() -> None:
    """THE FLOOR ON THE PIN ITSELF. An empty or one-sided set would make the control vacuous."""
    assert len(BOTH_GAPS) == 2
    assert all(sentence.strip() for sentence in BOTH_GAPS)


def test_a_complete_port_renders_no_gap(records: Broker) -> None:
    """THE PROPERTY, on a repo that answers both questions."""
    assert_this_repo_supplies_both_halves_of_the_door(port=_port, repo_name=_REPO, broker=records)


def test_a_port_missing_the_lock_adapter_reds(records: Broker) -> None:
    """PLANTED: half a door. The property arm must convict, or it is asserting nothing."""

    def half(*, broker: Broker) -> Port:
        _ = broker
        return Port(name=_REPO, anchor_paths=lambda: ())

    with pytest.raises(AssertionError, match='NO LOCK DECLARED'):
        assert_this_repo_supplies_both_halves_of_the_door(port=half, repo_name=_REPO, broker=records)


def test_a_report_that_does_not_name_the_repo_reds(records: Broker) -> None:
    """PLANTED: a complete door reporting under somebody else's name."""
    with pytest.raises(AssertionError, match='who changed what'):
        assert_this_repo_supplies_both_halves_of_the_door(
            port=_port,
            repo_name='a-name-the-port-never-uses',
            broker=records,
        )


def test_the_control_convicts_a_port_declaring_neither() -> None:
    """THE CONTROL, run as the consumer will run it."""
    assert_a_port_declaring_neither_renders_both_gaps()


def test_the_holders_adapter_arm_is_green_on_a_real_adapter(records: Broker) -> None:
    """The fixture adapter really reads the box records, so the plant is visible to it."""
    assert_the_holders_adapter_names_a_planted_holder(live_holders=_holders, broker=records)


def test_an_adapter_that_always_says_nobody_reds(records: Broker) -> None:
    """PLANTED: the vacuous green this arm exists for -- an adapter blind to every run forever."""
    with pytest.raises(AssertionError, match='cannot see the run it is meant to refuse'):
        assert_the_holders_adapter_names_a_planted_holder(live_holders=lambda **_: (), broker=records)


def test_an_adapter_that_always_names_somebody_reds(records: Broker) -> None:
    """THE OTHER SIDE: an adapter naming a phantom refuses every dependency change this repo makes."""
    with pytest.raises(AssertionError, match='already named'):
        assert_the_holders_adapter_names_a_planted_holder(
            live_holders=lambda **_: ('a-holder-that-is-not-there',),
            broker=records,
        )


def test_the_door_refuses_a_live_verdict() -> None:
    """H1 prevented, through the real door."""
    assert_the_door_refuses_while_a_verdict_is_in_flight(repo_name=_REPO, verdict_anchors=lambda: ())


def test_the_refusal_arm_reds_when_the_repo_name_is_wrong() -> None:
    """PLANTED: the refusal names a holder, but not the one this repo would be told about."""
    with pytest.raises(AssertionError, match='the refusal said'):
        assert_the_door_refuses_while_a_verdict_is_in_flight(
            repo_name='a-name-the-refusal-will-not-carry',
            verdict_anchors=lambda: (),
        )


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
