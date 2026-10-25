"""Known-good as a history, and a failure count that can actually reach its threshold."""

from __future__ import annotations

from typing import Any

from dev_lab.supervise.release import (
    DEFAULT_KEEP,
    Snapshot,
    failure_streak,
    history,
    record_failure,
    record_success,
    target_of,
)


def _snapshot(main: str, libs: str = '', at: str = '') -> Snapshot:
    return Snapshot(main=main, libs=libs, at=at)


def test_a_target_that_has_never_deployed_has_no_history() -> None:
    """Not an error: the first deployment has nothing to roll back to, and says so."""
    assert history({}) == []


def test_a_snapshot_is_identified_by_its_commits_and_not_by_when_it_was_taken() -> None:
    """THE POINT OF THE KEY: the same code failing twice is the same failure, however far apart."""
    early = _snapshot('abc', 'lib=def', at='2026-10-03T10:00:00+00:00')
    late = _snapshot('abc', 'lib=def', at='2026-10-03T18:00:00+00:00')
    assert early.key == late.key


def test_the_same_release_recorded_twice_is_not_two_releases() -> None:
    """Re-verifying what is already known good must not fill the history with one commit."""
    state: dict[str, Any] = {}
    record_success(state, _snapshot('abc', at='t1'))
    record_success(state, _snapshot('abc', at='t2'))
    assert len(history(state)) == 1
    assert history(state)[0].at == 't2'


def test_the_history_is_bounded_and_keeps_the_newest() -> None:
    """A rollback steps back through it, so the end that matters is the recent one."""
    state: dict[str, Any] = {}
    for index in range(DEFAULT_KEEP + 3):
        record_success(state, _snapshot(f'sha{index}', at=f't{index}'))
    kept = history(state)
    assert len(kept) == DEFAULT_KEEP
    assert [one.main for one in kept] == [f'sha{i}' for i in range(3, 6)]


def test_a_newest_first_ordering_would_make_a_rollback_step_forward() -> None:
    """The order is load-bearing: the last entry is what a rollback returns to."""
    state: dict[str, Any] = {}
    record_success(state, _snapshot('first', at='t1'))
    record_success(state, _snapshot('second', at='t2'))
    assert history(state)[-1].main == 'second'


def test_failures_accumulate_for_one_release() -> None:
    """THE PREDECESSOR'S BUG: remembering the commit SET made two different failures count as one."""
    state: dict[str, Any] = {}
    bad = _snapshot('broken')
    assert record_failure(state, bad, 'it crashed') == 1
    assert record_failure(state, bad, 'it crashed') == 2
    assert record_failure(state, bad, 'it crashed') == 3
    assert failure_streak(state, bad) == 3


def test_a_different_release_starts_its_own_streak() -> None:
    """A new commit is a new question, and the count answers about the thing being tried."""
    state: dict[str, Any] = {}
    record_failure(state, _snapshot('one'), 'no')
    record_failure(state, _snapshot('one'), 'no')
    assert failure_streak(state, _snapshot('two')) == 0
    assert record_failure(state, _snapshot('two'), 'no') == 1


def test_a_success_clears_the_failures_of_what_came_before() -> None:
    """The count exists to notice a release that keeps failing; success settles the question."""
    state: dict[str, Any] = {}
    broken = _snapshot('broken')
    record_failure(state, broken, 'no')
    record_failure(state, broken, 'no')
    record_success(state, _snapshot('works', at='t'))
    assert failure_streak(state, broken) == 0


def test_an_interrupted_streak_does_not_count_across() -> None:
    """Three failures of A, then B, then A again is not a streak of four."""
    state: dict[str, Any] = {}
    first, second = _snapshot('a'), _snapshot('b')
    record_failure(state, first, 'no')
    record_failure(state, second, 'no')
    assert record_failure(state, first, 'no') == 1


def test_a_failure_record_is_bounded() -> None:
    """An unbounded list would grow the state file for the life of the deployment."""
    state: dict[str, Any] = {}
    for index in range(80):
        record_failure(state, _snapshot(f'sha{index}'), 'no')
    assert len(state['release_failures']) <= 50


def test_a_target_snapshot_renders_its_libraries_in_a_stable_order() -> None:
    """Two snapshots of one state must compare equal, so the rendering cannot depend on dict order."""
    one = target_of({'main': 'm', 'lib': 'l', 'other': 'o'})
    two = target_of({'other': 'o', 'lib': 'l', 'main': 'm'})
    assert one.libs == two.libs == 'lib=l,other=o'
    assert one.main == 'm'
