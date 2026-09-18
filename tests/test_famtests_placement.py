"""The controls for :mod:`lab_commons.dev.famtests.placement` -- every arm, both ways.

WHAT IS PROVED HERE. That each arm refuses a planted offender and stays silent on the honest tree
beside it, and -- for the two bar arms -- that the family's FOUR REAL MEASUREMENTS are driven through
them rather than quoted in prose. The finding this module exists to carry is that three rosters bound
their own-mechanism ceiling at 50 and the fourth at 40, over intervals that EXCLUDE each other's
value; that crossing is PLANTED below and the refusal asserted, so it is a test rather than a
paragraph.

EVERY NO-DEFAULT ARGUMENT GETS A COUNTER-CONTROL. The argument for the signature is never the
signature: it is that a WRONG value REPORTS CLEAN rather than raising. A wrong exclusion set removes
files from the population, a wrong tree list walks nothing, a narrow suffix set leaves a whole
language unclassified, and each of those then reports a tree with nothing unplaced in it. So the wrong
value is planted and the silence is asserted directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from lab_commons.dev import floors
from lab_commons.dev.famtests._placement_readings import CEILINGS, MINIMUMS, NOT_FAMILY, ROSTERS
from lab_commons.dev.famtests.placement import (
    MOVES,
    SPLITS,
    STAYS,
    BarMisbounded,
    Placement,
    StaleDebt,
    Unplaced,
    assert_ceiling_is_bounded,
    assert_every_file_is_placed,
    assert_minimum_is_bounded,
    assert_no_stale_debt,
    placed_files,
)

if TYPE_CHECKING:
    from pathlib import Path


def plant(root: Path, relative: str, body: str) -> Path:
    """Write *body* at *relative* under *root*, parents made -- a real file for a real walk."""
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding='utf-8')
    return path


# --------------------------------------------------------------------------- THE BARS


@pytest.mark.parametrize('roster', sorted(CEILINGS))
def test_every_rosters_real_ceiling_sits_inside_its_own_measured_interval(roster: str) -> None:
    value, admits, refuses = CEILINGS[roster]
    assert_ceiling_is_bounded(value, admits=admits, refuses=refuses, what=roster)


@pytest.mark.parametrize('roster', sorted(MINIMUMS))
def test_every_rosters_real_minimum_sits_inside_its_own_measured_interval(roster: str) -> None:
    value, admits, refuses = MINIMUMS[roster]
    assert_minimum_is_bounded(value, admits=admits, refuses=refuses, what=roster)


def test_the_family_ceiling_is_two_values_and_each_is_refused_by_the_others_interval() -> None:
    """THE FINDING, AS A TEST. A sibling's ceiling is refused by this roster's own two rows.

    `(35, 42)` excludes 50 and `(49, 55)` excludes 40, so a family constant would have been wrong for
    one of four consumers ON THAT CONSUMER'S OWN EVIDENCE -- and wrong in the admitting direction,
    which is the silent one. Read from the declaration rather than typed here, so a re-measurement
    that dissolved the disagreement would red this arm instead of leaving it describing a past tree.
    """
    scripts_value, *_ = CEILINGS['motronics scripts']
    wdg_value, wdg_admits, wdg_refuses = CEILINGS['wdg-lab']
    _, scripts_admits, scripts_refuses = CEILINGS['motronics scripts']
    assert scripts_value != wdg_value, 'the disagreement is the subject; if it closed, delete this arm'

    with pytest.raises(BarMisbounded, match='exclude each other'):
        assert_ceiling_is_bounded(wdg_value, admits=scripts_admits, refuses=scripts_refuses, what='scripts, handed 50')
    with pytest.raises(BarMisbounded, match='exclude each other'):
        assert_ceiling_is_bounded(scripts_value, admits=wdg_admits, refuses=wdg_refuses, what='wdg-lab, handed 40')


def test_the_family_minimum_agrees_four_ways_and_the_intersection_still_contains_it() -> None:
    """The counter-side: for THIS bar every repo's interval admits every repo's value.

    Measured rather than asserted as a shared constant. The tightest floor is 2.54% and the tightest
    cap is 3.06%, so the four intervals intersect in `(2.54, 3.06]` and 3.0 is inside it. That is why
    the agreement is evidence and NOT a reason to publish the number.
    """
    tightest_floor = max(refuses for _, _, refuses in MINIMUMS.values())
    tightest_cap = min(admits for _, admits, _ in MINIMUMS.values())
    assert (tightest_floor, tightest_cap) == (2.54, 3.06)
    for roster, (value, _, _) in MINIMUMS.items():
        assert_minimum_is_bounded(value, admits=tightest_cap, refuses=tightest_floor, what=roster)


def test_a_bar_at_the_edge_of_its_interval_is_decided_and_not_left_to_the_reader() -> None:
    """A ceiling may EQUAL the reading it admits and may not equal the one it refuses.

    The minimum mirrors it. Both edges are driven, because an off-by-one on a bar is the quiet
    direction: it admits a row the evidence refuses, and nothing reds.
    """
    assert_ceiling_is_bounded(49, admits=49, refuses=55, what='edge')
    with pytest.raises(BarMisbounded):
        assert_ceiling_is_bounded(55, admits=49, refuses=55, what='edge')
    assert_minimum_is_bounded(4.79, admits=4.79, refuses=1.41, what='edge')
    with pytest.raises(BarMisbounded):
        assert_minimum_is_bounded(1.41, admits=4.79, refuses=1.41, what='edge')


def test_a_pair_of_readings_that_brackets_nothing_is_named_as_the_stale_half() -> None:
    with pytest.raises(BarMisbounded, match='brackets'):
        assert_ceiling_is_bounded(50, admits=60, refuses=55, what='crossed')
    with pytest.raises(BarMisbounded, match='brackets'):
        assert_minimum_is_bounded(3.0, admits=1.0, refuses=4.0, what='crossed')


# --------------------------------------------------------------------------- THE WALK


def a_tree(root: Path) -> None:
    """One of each shape the walk must decide: placed, excluded by part, by name, and by suffix."""
    plant(root, 'scripts/runner.py', 'value = 1\n')
    plant(root, 'scripts/helper.sh', '#!/bin/sh\n')
    plant(root, 'scripts/__init__.py', '')
    plant(root, 'scripts/__pycache__/runner.cpython-313.pyc', '')
    plant(root, 'scripts/notes.md', '# prose\n')
    plant(root, 'tests/architecture/test_a.py', 'value = 1\n')
    plant(root, 'tests/unit/test_b.py', 'value = 1\n')


def test_the_walk_places_what_it_declares_and_nothing_else(tmp_path: Path) -> None:
    a_tree(tmp_path)
    found = placed_files(
        tmp_path,
        trees=('scripts', 'tests/architecture'),
        suffixes=('.py', '.sh'),
        not_placed=('__pycache__',),
    )
    assert found == ('scripts/helper.sh', 'scripts/runner.py', 'tests/architecture/test_a.py')


def test_a_wrong_tree_list_walks_nothing_and_reports_it_clean(tmp_path: Path) -> None:
    """THE NO-DEFAULT COUNTER-CONTROL FOR `trees`: the wrong answer does not raise, it goes quiet."""
    a_tree(tmp_path)
    assert placed_files(tmp_path, trees=('src',), suffixes=('.py',), not_placed=()) == ()


def test_a_wrong_exclusion_set_shrinks_the_population_silently(tmp_path: Path) -> None:
    """THE NO-DEFAULT COUNTER-CONTROL FOR `not_placed`: it REMOVES rows rather than refusing."""
    a_tree(tmp_path)
    honest = placed_files(tmp_path, trees=('scripts',), suffixes=('.py',), not_placed=('__pycache__',))
    guessed = placed_files(tmp_path, trees=('scripts',), suffixes=('.py',), not_placed=('__pycache__', 'scripts'))
    assert 'scripts/runner.py' in honest
    assert guessed == (), 'a widened exclusion hides the whole tree and the walk still returns cleanly'


def test_a_narrow_suffix_set_leaves_a_whole_language_unclassified(tmp_path: Path) -> None:
    """THE NO-DEFAULT COUNTER-CONTROL FOR `suffixes`, and it is motronics' measured 2026-09-16 defect."""
    a_tree(tmp_path)
    narrow = placed_files(tmp_path, trees=('scripts',), suffixes=('.py',), not_placed=('__pycache__',))
    wide = placed_files(tmp_path, trees=('scripts',), suffixes=('.py', '.sh'), not_placed=('__pycache__',))
    assert 'scripts/helper.sh' not in narrow
    assert 'scripts/helper.sh' in wide


def test_package_markers_are_never_placed_and_that_is_the_kits_answer_not_the_repos(tmp_path: Path) -> None:
    a_tree(tmp_path)
    found = placed_files(tmp_path, trees=('scripts',), suffixes=('.py',), not_placed=())
    assert 'scripts/__init__.py' not in found


# --------------------------------------------------------------------------- COMPLETENESS


def test_completeness_names_both_directions_in_one_refusal() -> None:
    with pytest.raises(Unplaced) as caught:
        assert_every_file_is_placed(('a.py', 'b.py'), declared=('b.py', 'gone.py'), floor=1, headroom=5, what='roster')
    message = str(caught.value)
    assert "UNPLACED (walked, no row): ['a.py']" in message
    assert "GONE (row, not walked): ['gone.py']" in message


def test_the_floor_is_bound_before_a_single_comparison_is_made() -> None:
    """An EMPTY walk against an EMPTY manifest agrees perfectly, which is the vacuous green."""
    with pytest.raises(floors.FloorUnmet):
        assert_every_file_is_placed((), declared=(), floor=20, headroom=5, what='roster')


def test_the_floors_second_side_refuses_a_number_the_tree_has_outgrown() -> None:
    found = tuple(f'{n}.py' for n in range(80))
    with pytest.raises(floors.SlackFloor):
        assert_every_file_is_placed(found, declared=found, floor=20, headroom=5, what='roster')


def test_an_agreeing_roster_above_its_floor_passes() -> None:
    found = tuple(f'{n}.py' for n in range(25))
    assert assert_every_file_is_placed(found, declared=found, floor=20, headroom=10, what='roster') is None


# --------------------------------------------------------------------------- THE DEBT


def test_a_debt_row_naming_a_file_the_manifest_lost_is_refused() -> None:
    with pytest.raises(StaleDebt, match=r'gone\.py'):
        assert_no_stale_debt(declared=('a.py',), debt={'gone.py': 'own=90 hits=1'}, what='roster')


def test_the_empty_debt_is_the_state_the_ratchet_exists_to_reach_and_is_accepted() -> None:
    """The `datedmemory` side of the fork, chosen deliberately over `rostercensus`'s refusal."""
    assert assert_no_stale_debt(declared=('a.py',), debt={}, what='roster') is None
    assert assert_no_stale_debt(declared=('a.py',), debt=frozenset(), what='roster') is None


def test_the_debt_may_be_a_bare_set_as_well_as_a_mapping() -> None:
    with pytest.raises(StaleDebt, match=r'gone\.py'):
        assert_no_stale_debt(declared=('a.py',), debt=frozenset({'gone.py'}), what='roster')


# --------------------------------------------------------------------------- THE DECLARATION


def test_the_sides_are_three_distinct_spellings() -> None:
    """A roster that lost a side would silently classify every row as whatever survived."""
    assert len({STAYS, MOVES, SPLITS}) == 3
    assert Placement(side=STAYS, why='ours') != Placement(side=MOVES, why='ours')


def test_a_placement_row_is_frozen_so_a_reader_cannot_relabel_it() -> None:
    row = Placement(side=STAYS, why='names the widget')
    with pytest.raises(AttributeError):
        row.side = MOVES


def test_the_readings_declare_every_roster_the_bars_were_taken_from() -> None:
    """A bar row naming a roster the census does not hold is a measurement with no tree behind it."""
    assert set(CEILINGS) == set(ROSTERS) == set(MINIMUMS)
    assert len(ROSTERS) == 4, 'four rosters is the whole population; a fifth arriving must be read, not assumed'
    for path, commit, rows in ROSTERS.values():
        assert path.endswith('.py'), 'a roster is a module and the path is how a reader re-takes the reading'
        assert commit, 'a reading with no commit names a tree that could have moved under it'
        assert rows > 0, 'a roster of zero rows bounded nothing'


def test_the_boundary_rows_each_carry_the_count_that_decided_them() -> None:
    """Direction alone is not a boundary and neither is a shared filename -- so every row has a number.

    The floor matters more than the rows: a NOT_FAMILY census that found nothing would read exactly
    like a module whose boundary was measured and came back total.
    """
    assert len(NOT_FAMILY) >= 3, 'a boundary that named nothing is a module that did not measure one'
    for held_by, why in NOT_FAMILY.values():
        assert 1 <= held_by <= len(ROSTERS)
        assert len(why) > 80, 'a count without its reason is the pin that cannot say which half moved'


def test_a_checkout_under_an_excluded_directory_still_has_a_population(tmp_path: Path) -> None:
    """THE CONTROL FOR THE `not_placed` MATCH BEING RELATIVE, and it is a MEASURED family defect.

    The exclusion used to test the ABSOLUTE path's parts. Every ancestor of the checkout is in those
    parts, so a repo living under a directory whose name is in *not_placed* excluded ITS WHOLE TREE
    -- for any commit, with no refusal. That is not hypothetical: this family fans lanes out into
    ``<repo>/.claude/worktrees/<branch>``, `.claude` is in both labs' `NOT_PLACED`, and a worktree cut
    there collapsed every population scanner in that repo at once.

    THE PLANT IS THE LAYOUT AND NOT THE SET, which is what makes this a different control from
    `test_a_wrong_exclusion_set_shrinks_the_population_silently`. The set here is CORRECT; only the
    checkout's location moved, and nothing about the roster's own declaration changed.
    """
    nested = tmp_path / '.claude' / 'worktrees' / 'kit' / 'repo'
    a_tree(nested)
    found = placed_files(nested, trees=('scripts',), suffixes=('.py',), not_placed=('__pycache__', '.claude'))
    assert found == ('scripts/runner.py',), (
        f'a checkout under an excluded directory walked {found}. The exclusion must test the '
        f'REPO-RELATIVE path -- testing the absolute one makes the population a fact about where the '
        f'checkout happens to sit, and an empty population reports a fully classified tree.'
    )


def test_the_exclusion_still_bites_on_a_relative_part_under_that_same_layout(tmp_path: Path) -> None:
    """THE RATCHET'S OTHER SIDE. A fix that stopped excluding anything would satisfy the arm above.

    So the same nested checkout must still drop a file that is genuinely inside an excluded directory
    WITHIN the repo -- a capability that disappears is as wrong as a waiver nothing uses.
    """
    nested = tmp_path / '.claude' / 'worktrees' / 'kit' / 'repo'
    a_tree(nested)
    plant(nested, 'scripts/.claude/agents/helper.py', 'value = 1\n')
    found = placed_files(nested, trees=('scripts',), suffixes=('.py',), not_placed=('__pycache__', '.claude'))
    assert 'scripts/.claude/agents/helper.py' not in found, f'the exclusion stopped biting entirely: {found}'
    assert found == ('scripts/runner.py',), found
