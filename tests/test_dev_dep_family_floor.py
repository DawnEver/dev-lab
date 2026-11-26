"""A sync or relock that moves a family package moves its family floor (lab-commons) with it (dev-lab #994).

Observed: ``dep --sync --extra torch`` in a learn-lab worktree moved dev-lab to integrate/main but left lab-commons
pinned, so dev-lab's new imports broke until ``--upgrade-package lab-commons`` repaired it.
"""

from dev_lab.dev._dep_project import FAMILY_FLOOR, with_family_floor


def test_moving_a_family_package_moves_the_family_floor() -> None:
    assert with_family_floor({'dev-lab'}) == {'dev-lab', FAMILY_FLOOR}
    assert FAMILY_FLOOR == 'lab-commons'


def test_planted_control_a_move_of_no_family_package_adds_nothing() -> None:
    """PLANTED CONTROL: the rule can say no -- a non-family upgrade, or none at all, gains no floor."""
    assert with_family_floor({'numpy'}) == {'numpy'}
    assert with_family_floor(set()) == set()


def test_moving_the_floor_itself_stays_the_floor() -> None:
    assert with_family_floor({FAMILY_FLOOR}) == {FAMILY_FLOOR}
