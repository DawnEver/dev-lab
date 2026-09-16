"""``lab_commons.dev.bounded`` -- the wall, the width, and the sentence, each driven for real.

THE SUBJECT OF THE WALL IS THE CLOCK, so it is measured against a planted GRANDCHILD that really
inherits the parent's stdout handle and really outlives the wall. That is the only shape that can
fail for the right reason: ``subprocess.run(timeout=...)`` passes a test whose child has no
children, and passes it in the exact configuration that hung a real run for thirty minutes past its
own wall.

THE SENTENCE IS DRIVEN IN ALL THREE STATES, because a refusal that names one remedy for three
different situations is the defect this module was carved out to remove -- and two of those three
remedies are WRONG in the other's case.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from lab_commons.dev.bounded import (
    BLAS_THREAD_VARS,
    NARROWED_FLOOR,
    blas_threads,
    is_narrowed,
    logical_cores,
    reap_tree,
    run_bounded,
    wall_reason,
    worker_width,
)
from lab_commons.proc import process_tree

#: A parent that spawns a LONG-LIVED grandchild inheriting its stdout, then sleeps past the wall.
#: The grandchild is what keeps the pipe open, which is the whole defect.
_PARENT = (
    'import subprocess, sys, time; '
    "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']); "
    'time.sleep(120)'
)

#: The wall the cases below use, and the ceiling on how long the reap may take afterwards. Both are
#: small multiples of the wall rather than absolute numbers pulled out of the air: the claim is
#: about a RATIO -- the call returns near its wall, not near the child's lifetime.
_WALL_S = 3.0
_REAP_CEILING = 4.0


def test_the_wall_terminates_a_tree_and_returns_near_its_wall() -> None:
    """THE PROPERTY, and the thing ``subprocess.run`` does not do.

    The assertion is on ELAPSED TIME against the wall, not on the tree being empty afterwards: a
    pid table on a busy box is a snapshot of a mutating machine, but "did this call return" is a
    fact nothing can blur. The child sleeps 120 s; a run that waits for the grandchild's pipe
    cannot come back in single-digit seconds.
    """
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_bounded([sys.executable, '-c', _PARENT], timeout=_WALL_S, text=True)
    elapsed = time.monotonic() - started
    assert elapsed < _WALL_S + _REAP_CEILING, (
        f'the bounded call took {elapsed:.1f}s against a {_WALL_S}s wall. A hang detector that hangs '
        f'is worse than none: raising the wall makes this strictly worse.'
    )


def test_a_run_that_finishes_inside_the_wall_is_not_disturbed() -> None:
    """THE OTHER SIDE. A wall that also breaks the passing case is not a wall, it is a fault."""
    done = run_bounded([sys.executable, '-c', 'print("ok")'], timeout=60, text=True)
    assert done.returncode == 0
    assert done.stdout.strip() == 'ok'
    assert done.args[0] == sys.executable


def test_the_width_takes_the_SMALLER_of_memory_and_cores(monkeypatch: pytest.MonkeyPatch) -> None:
    """Memory first, cores second -- an overcommit of memory kills, an overcommit of cores slows."""
    monkeypatch.setattr('lab_commons.dev.bounded.logical_cores', lambda: 16)
    monkeypatch.setattr('lab_commons.dev.bounded._available_gb', lambda: 8.0)
    # 8 GB / 4 GB per worker = 2, against 15 the cores allow: memory wins.
    assert worker_width(gb_per_worker=4.0, max_width=12, floor=2, reserve_cores=1, fallback=8) == 2

    monkeypatch.setattr('lab_commons.dev.bounded._available_gb', lambda: 256.0)
    # cores - reserve = 15, clipped by the declared maximum.
    assert worker_width(gb_per_worker=4.0, max_width=12, floor=2, reserve_cores=1, fallback=8) == 12


def test_an_unreadable_box_falls_back_to_a_measurement_not_to_the_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    """`None` IS NOT ZERO. "cannot measure" is not "cannot afford", and the two differ by 6 workers."""
    monkeypatch.setattr('lab_commons.dev.bounded.logical_cores', lambda: 16)
    monkeypatch.setattr('lab_commons.dev.bounded._available_gb', lambda: None)
    assert worker_width(gb_per_worker=4.0, max_width=12, floor=2, reserve_cores=1, fallback=8) == 8

    monkeypatch.setattr('lab_commons.dev.bounded.logical_cores', lambda: 3)
    # A small box clips the fallback by what its processors allow, and never falls below the floor.
    assert worker_width(gb_per_worker=4.0, max_width=12, floor=2, reserve_cores=1, fallback=8) == 2


def test_the_width_never_falls_below_its_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    """0 and 1 mean SERIAL, which is a human's choice and not somewhere a starved box arrives."""
    monkeypatch.setattr('lab_commons.dev.bounded.logical_cores', lambda: 2)
    monkeypatch.setattr('lab_commons.dev.bounded._available_gb', lambda: 0.5)
    assert worker_width(gb_per_worker=4.0, max_width=12, floor=2, reserve_cores=1, fallback=8) == 2


def test_the_blas_pool_is_shared_out_rather_than_handed_to_every_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """The measured defect: N workers each building an N-core pool, 106 threads for 24 cores."""
    monkeypatch.setattr('lab_commons.dev.bounded.logical_cores', lambda: 24)
    assert blas_threads(6) == 4
    assert blas_threads(24) == 1
    assert blas_threads(100) == 1, 'floor 1 -- a worker with zero threads computes nothing'
    assert blas_threads(0) == 24, 'one process may have the whole box; that is what makes a priced run comparable'
    assert len(set(BLAS_THREAD_VARS)) == len(BLAS_THREAD_VARS) >= 4, 'the pool-spawning runtimes, by name'


def test_the_narrowing_line_is_half_of_capacity_with_a_floor() -> None:
    """BOTH SIDES of the line a measurement moved, and the case that moved it.

    4 workers on an 8-core box was reported as "a full-width run did not fit". Four of eight is not
    full width. 6 of 8 must stay HEALTHY, or a genuine tier boundary could never be named again.
    """
    assert is_narrowed(4, 8), 'the case that moved the line'
    assert not is_narrowed(6, 8), 'a healthy run must stay describable as a real tier boundary'
    assert is_narrowed(NARROWED_FLOOR, 2), 'the floor catches a narrow run on a box too small for the ratio'
    assert not is_narrowed(3, 4)


def test_the_refusal_names_a_DIFFERENT_remedy_in_each_of_the_three_states() -> None:
    """THE RULE ITSELF: take the remedy a refusal NAMES -- so the three states may not share one."""
    unmeasured = wall_reason(workers=None, capacity=8, wider_tier='heavy')
    narrowed = wall_reason(workers=2, capacity=8, wider_tier='heavy')
    healthy = wall_reason(workers=7, capacity=8, wider_tier='heavy')

    assert len({unmeasured, narrowed, healthy}) == 3, 'one sentence for three states is a diagnosis nobody computed'
    for sentence in (unmeasured, narrowed, healthy):
        assert 'heavy' in sentence, "every refusal names the remedy, and the tier is the caller's own word"
    assert 'not measured' in unmeasured and 'NARROWED' not in unmeasured
    assert 'NARROWED' in narrowed and 'memory pressure' in narrowed
    assert '7 of the 8' in healthy and 'different TIER' in healthy


def test_the_wider_tier_has_no_default() -> None:
    """A remedy naming a tier the reading repo does not have is a dead end wearing a remedy's clothes."""
    with pytest.raises(TypeError):
        wall_reason(workers=1, capacity=8)


def test_the_core_count_is_a_real_reading() -> None:
    """A FLOOR on the box reading itself: 0 cores would make every width answer arithmetic on nothing."""
    assert logical_cores() >= 1


def test_the_reaper_refuses_a_tree_that_contains_this_process() -> None:
    """THE SELF-MATCH, PLANTED AS THIS PROCESS. Ask for our own tree; be refused, and survive."""
    assert os.getpid() in process_tree(os.getpid()), 'a tree not containing its own root cannot protect it'
    assert reap_tree(os.getpid()) == frozenset(), 'the reaper was asked to end its own tree and must refuse'


def test_the_reaper_still_ends_a_tree_that_is_not_ours() -> None:
    """THE OTHER SIDE. A reaper that spares everything is not a reaper.

    Confirmed by the planted process's own exit rather than by the return value alone, so the claim
    rests on an observation of the machine and not on the function agreeing with itself.
    """
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])
    try:
        assert child.poll() is None, 'the planted process did not start, so nothing was proved'
        assert child.pid in reap_tree(child.pid), f'{child.pid} is outside this lineage and must be reaped'
        assert child.wait(timeout=20) is not None
    finally:
        if child.poll() is None:
            child.kill()
