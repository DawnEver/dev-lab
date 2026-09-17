"""The shard partition and the AND over a shard set, driven against real trees and real refusals.

WHY THE PARTITION ARMS ASSERT A PROPERTY RATHER THAN A LIST. A test that spells out which files land
in piece 1 of 3 is a second copy of the arithmetic and agrees with it by construction, including
when both are wrong. The properties that actually matter are COVERAGE (the union is the whole),
DISJOINTNESS (no member is judged twice) and DETERMINISM (two calls agree), and those are false of
every wrong implementation this could have.

THE COMPOSE ARMS ARE PLANTED IN BOTH DIRECTIONS. Each refusal has a sibling arm that is identical
except for the one fact being refused, so a composer that refused everything would fail here just as
loudly as one that refused nothing.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from lab_commons.dev.shards import Composed, compose, partition, population
from lab_commons.dev.testfacts import VacuousScanError
from lab_commons.dev.verdict import Outcome

#: A healthy set: three pieces, one tree, one env, all passing.
_TREE = 'sha256:c0ffee'
_ENV = 'env0'


def _rows(*outcomes: Outcome, tree: str = _TREE, env: str = _ENV) -> tuple[tuple[str, str, Outcome], ...]:
    """Rows that agree on everything except the outcomes given."""
    return tuple((tree, env, outcome) for outcome in outcomes)


def _plant(root: Path, *names: str) -> None:
    """Write an empty file per name, creating parents."""
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('', encoding='utf-8')


def test_a_population_is_sorted_posix_and_relative_to_the_root(tmp_path: Path) -> None:
    """The three properties one piece of a set depends on to mean the same thing everywhere."""
    _plant(tmp_path, 'tests/b/test_z.py', 'tests/a/test_a.py', 'tests/test_m.py', 'tests/notes.txt')
    found = population(tmp_path, 'tests', 'test_*.py', floor=3)
    assert found == ('tests/a/test_a.py', 'tests/b/test_z.py', 'tests/test_m.py')
    assert all('\\' not in name for name in found)


def test_a_population_below_its_floor_refuses_rather_than_returning_an_empty_set(tmp_path: Path) -> None:
    """THE VACUOUS-GREEN REFUSAL: a moved directory must not shard into a green verdict about nothing."""
    _plant(tmp_path, 'tests/test_a.py')
    with pytest.raises(VacuousScanError, match='below the 5 floor'):
        population(tmp_path, 'tests', 'test_*.py', floor=5)


def test_a_population_at_its_floor_is_returned_so_the_refusal_is_not_unconditional(tmp_path: Path) -> None:
    """THE CONTROL IN THE OTHER DIRECTION: the floor can still say yes, exactly at the boundary."""
    _plant(tmp_path, 'tests/test_a.py', 'tests/test_b.py')
    assert len(population(tmp_path, 'tests', 'test_*.py', floor=2)) == 2


def test_the_floor_is_a_REQUIRED_KEYWORD() -> None:
    """A default floor is a floor nobody chose, which is how the scan gets to be vacuous again."""
    floor = inspect.signature(population).parameters['floor']
    assert floor.kind is inspect.Parameter.KEYWORD_ONLY
    assert floor.default is inspect.Parameter.empty


@pytest.mark.parametrize('count', [1, 2, 3, 5, 8])
def test_the_pieces_COVER_the_whole_and_never_overlap(count: int) -> None:
    """Coverage and disjointness, over a population that is not a multiple of any piece count."""
    whole = tuple(f'test_{i:02d}.py' for i in range(17))
    pieces = [partition(whole, index, count) for index in range(count)]
    flat = [member for piece in pieces for member in piece]
    assert sorted(flat) == sorted(whole)
    assert len(flat) == len(set(flat))


def test_the_pieces_are_BALANCED_to_within_one_member() -> None:
    """Round-robin's reason for existing: no piece may be handed the whole expensive neighbourhood."""
    whole = tuple(f'test_{i:02d}.py' for i in range(17))
    sizes = {len(partition(whole, index, 5)) for index in range(5)}
    assert max(sizes) - min(sizes) <= 1


def test_the_same_index_of_the_same_set_is_the_same_piece_twice() -> None:
    """Determinism: piece 2 of 8 must name the same files on every box and on every call."""
    whole = tuple(f'test_{i:02d}.py' for i in range(17))
    assert partition(whole, 2, 8) == partition(whole, 2, 8)


@pytest.mark.parametrize(('index', 'count'), [(-1, 3), (3, 3), (9, 3), (0, 0), (0, -2)])
def test_an_index_outside_the_set_REFUSES_rather_than_returning_nothing(index: int, count: int) -> None:
    """An empty piece IS a shard that ran nothing and passed, so it may not be reachable by accident."""
    with pytest.raises(ValueError, match=r'shard index|at least one piece'):
        partition(('a.py', 'b.py'), index, count)


def test_a_complete_agreeing_passing_set_composes_to_PASS() -> None:
    """THE FLOOR FOR EVERY REFUSAL BELOW: the composer can say PASS at all."""
    got = compose(_rows(Outcome.PASS, Outcome.PASS, Outcome.PASS), 3)
    assert got == Composed(Outcome.PASS, got.reason, 3, 3)
    assert 'all 3 shards PASSED' in got.reason


def test_a_MISSING_row_is_INCONCLUSIVE_and_names_which_piece() -> None:
    """Never "the ones that arrived all passed" -- and the reason must be actionable, so it counts."""
    got = compose((_rows(Outcome.PASS)[0], None, _rows(Outcome.PASS)[0]), 3)
    assert got.result is Outcome.INCONCLUSIVE
    assert got.present == 2
    assert 'indices [1]' in got.reason


def test_a_set_SHORTER_than_its_count_is_INCONCLUSIVE_even_with_no_None() -> None:
    """A reader that produced two rows for a three-piece set has an incomplete set and no ``None``.

    This is the arm a ``None``-only check cannot see, and it is the likelier real failure: a reader
    that globbed for shard logs finds two files and returns two rows.
    """
    got = compose(_rows(Outcome.PASS, Outcome.PASS), 3)
    assert got.result is Outcome.INCONCLUSIVE
    assert got.present == 2


@pytest.mark.parametrize(
    ('rows', 'fragment'),
    [
        (((_TREE, _ENV, Outcome.PASS), ('sha256:other', _ENV, Outcome.PASS)), 'disagree'),
        (((_TREE, _ENV, Outcome.PASS), (_TREE, 'env1', Outcome.PASS)), 'disagree'),
        ((('unknown', _ENV, Outcome.PASS), ('unknown', _ENV, Outcome.PASS)), 'names no committed state'),
        ((('abc123-dirty', _ENV, Outcome.PASS), ('abc123-dirty', _ENV, Outcome.PASS)), 'names no committed state'),
    ],
)
def test_an_unattributable_or_disagreeing_set_is_INCONCLUSIVE(rows: tuple, fragment: str) -> None:
    """Two shards that agree on a tree NOBODY CAN NAME pass the agreement check and must still refuse."""
    got = compose(rows, 2)
    assert got.result is Outcome.INCONCLUSIVE
    assert fragment in got.reason


def test_two_shards_on_one_NAMED_tree_still_compose_so_the_attribution_arm_is_not_blanket() -> None:
    """THE PLANTED CONTROL for the attribution refusal: a real sha passes where ``unknown`` refused."""
    assert compose(_rows(Outcome.PASS, Outcome.PASS), 2).result is Outcome.PASS


def test_any_FAIL_makes_the_whole_FAIL_and_the_count_is_named() -> None:
    """The question is about the whole, so one failing piece settles it."""
    got = compose(_rows(Outcome.PASS, Outcome.FAIL, Outcome.FAIL), 3)
    assert got.result is Outcome.FAIL
    assert '2 of 3 shards FAILED' in got.reason


def test_a_FAIL_beats_an_INCONCLUSIVE_because_a_named_failure_is_more_information() -> None:
    """Mixed settled and unsettled pieces: the FAIL is a fact and the INCONCLUSIVE is an absence."""
    assert compose(_rows(Outcome.INCONCLUSIVE, Outcome.FAIL), 2).result is Outcome.FAIL


def test_a_set_holding_an_INCONCLUSIVE_and_no_FAIL_cannot_be_greener_than_it() -> None:
    """The last refusal, and the one that keeps ``PASS`` meaning every piece proved something."""
    got = compose(_rows(Outcome.PASS, Outcome.INCONCLUSIVE), 2)
    assert got.result is Outcome.INCONCLUSIVE
    assert 'greener' in got.reason


def test_the_composed_outcome_is_the_familys_enum_and_not_a_string() -> None:
    """One three-state vocabulary in this family; a second spelling is a fourth state nobody declared."""
    assert isinstance(compose(_rows(Outcome.PASS), 1).result, Outcome)
