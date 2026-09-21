"""THE LIVE BOUNDED-WAIT BODY, driven here on this box -- including the arm that says the box is unfit.

WHAT THIS FILE IS FOR, AND IT IS NOT THE CONSUMERS' ARMS. Each lab's
``test_a_bounded_wait_names_its_remedy.py`` asserts that ``dev.bounded`` behaves; this file asserts
that the SHARED BODY behaves, which is a different subject and has one property the consumers cannot
reach: what the arms do on a box too loaded to measure anything. That state is planted here on
NUMBERS, so both of its refusals are exercised without owning a loaded machine.

THE CONTROLS RUN IN BOTH DIRECTIONS AT EVERY SEAM. A wall that only ever refuses is not a bound, so
the passing case is driven beside the failing one; a reaper that spares everything is not a reaper,
so a real process outside this lineage is planted and confirmed by its own exit; and the separation
verdict is driven at the three answers it can give rather than at the one today's numbers produce.

THE AXIS EVERY CONTROL HERE IS BLIND TO is the same one the module names: a clock reading cannot tell
a correct reap from a child that died by itself. Nothing below claims otherwise, and the one arm that
observes the machine does it through the planted process's exit status.
"""

from __future__ import annotations

import subprocess
import time
from typing import Final

import pytest

from lab_commons.dev import bounded
from lab_commons.dev.famtests import boundedremedy

#: The numbers this REPO drives the live arms at. Both labs measured 3.0 and 4.0 independently and
#: landed on the same pair; the kit takes the same, and states that it is a copy of a measurement
#: rather than a source of one.
WALL_SECONDS: Final = 3.0
REAP_CEILING_SECONDS: Final = 4.0

#: How much load this repo absorbs before a reading is called inconclusive, and how far the planted
#: child must outlive the permitted return for a pass to mean anything. 120 s against a permitted
#: 7 s + slack is a factor of seventeen at rest, so a 4x separation leaves a wide band and still
#: refuses a box that has eaten three quarters of it.
OVERHEAD_MULTIPLE: Final = 4.0
SEPARATION_FACTOR: Final = 4.0


def test_the_calibration_reads_this_box_and_is_positive() -> None:
    """The reading every timing claim is priced from: it must be a real, usable number."""
    overhead = boundedremedy.spawn_overhead(interpreter=boundedremedy.default_interpreter(), ceiling_seconds=60.0)
    assert overhead > 0.0, 'a zero overhead multiplies to zero slack and silently removes mechanism 2'
    assert overhead < 60.0, f'{overhead:.2f}s is not a reading of an EMPTY child; the calibration measured something'


def test_a_box_that_cannot_start_a_child_is_inconclusive_rather_than_red() -> None:
    """PLANTED: a ceiling nothing can meet. The refusal must name the MACHINE, not the code."""
    with pytest.raises(boundedremedy.BoxTooLoaded, match='reading about the MACHINE'):
        boundedremedy.spawn_overhead(interpreter=boundedremedy.default_interpreter(), ceiling_seconds=1e-6)


def test_the_pool_vars_are_pinned_by_name_and_a_one_for_one_swap_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`NAMED-SETS-NOT-COUNTS` over the one constant in this family pinned by a COUNT.

    Both labs asserted `len(BLAS_THREAD_VARS) >= 4` under a message saying *"by name rather than by
    count"*. The plants below are why that is a defect rather than a wording slip: each is a
    one-for-one change a count reads as UNCHANGED, so a bogus runtime could replace a real one and the
    arm would stay green while its own message claimed to have named the set.
    """
    boundedremedy.assert_the_pool_vars_are_the_named_set()
    swapped = tuple('BOGUS_NUM_THREADS' if name == 'OMP_NUM_THREADS' else name for name in bounded.BLAS_THREAD_VARS)
    assert len(swapped) >= 4, 'the plant must clear the count pin this replaces, or it proves nothing'
    monkeypatch.setattr(bounded, 'BLAS_THREAD_VARS', swapped)
    with pytest.raises(AssertionError, match='BOGUS_NUM_THREADS'):
        boundedremedy.assert_the_pool_vars_are_the_named_set()


def test_a_duplicate_that_inflates_the_count_is_refused_too(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other half a count is blind to: three real runtimes spelled four times still reads as four."""
    duped = (*bounded.BLAS_THREAD_VARS[:3], bounded.BLAS_THREAD_VARS[0])
    assert len(duped) >= 4, 'the plant must clear the count pin this replaces'
    monkeypatch.setattr(bounded, 'BLAS_THREAD_VARS', duped)
    with pytest.raises(AssertionError, match='duplicate'):
        boundedremedy.assert_the_pool_vars_are_the_named_set()


def test_the_allowance_grows_with_the_box_and_never_below_the_declared_reap() -> None:
    """The arithmetic, at rest and under load. A slower box gets more slack without an edit."""
    quiet = boundedremedy.allowance(reap_ceiling_seconds=4.0, overhead_seconds=0.1, overhead_multiple=4.0)
    loaded = boundedremedy.allowance(reap_ceiling_seconds=4.0, overhead_seconds=0.4, overhead_multiple=4.0)
    assert loaded > quiet, 'a four-times-slower box must be granted more slack, or mechanism 2 does nothing'
    assert quiet >= 4.0, 'the priced allowance may never fall below the reap ceiling the repo measured'


def test_the_separation_verdict_gives_all_three_of_its_answers() -> None:
    """THE ANTI-FLAKE CEILING, PLANTED IN BOTH DIRECTIONS, and the two refusals are told apart.

    This is the arm that stops mechanism 2 from degrading into "pad until it passes". The three
    inputs differ only in WHERE the margin went -- nowhere, into the box, into the declaration -- and
    the verdict must name a different remedy for each, because waiting for a quiet box is the wrong
    advice for numbers that were never going to work.
    """
    holds = boundedremedy.separation_verdict(
        wall_seconds=3.0,
        reap_ceiling_seconds=4.0,
        slack_seconds=4.5,
        child_lifetime_seconds=120.0,
        separation_factor=4.0,
    )
    assert holds is None, f'7.5s permitted against a 120s child is a seventeen-fold separation: {holds}'

    box = boundedremedy.separation_verdict(
        wall_seconds=3.0,
        reap_ceiling_seconds=4.0,
        slack_seconds=40.0,
        child_lifetime_seconds=120.0,
        separation_factor=4.0,
    )
    assert isinstance(box, boundedremedy.BoxTooLoaded), f'a box that priced 40s of slack must be INCONCLUSIVE: {box}'
    assert 'the finding is the MACHINE' in str(box)

    declared = boundedremedy.separation_verdict(
        wall_seconds=3.0,
        reap_ceiling_seconds=4.0,
        slack_seconds=4.5,
        child_lifetime_seconds=10.0,
        separation_factor=4.0,
    )
    assert isinstance(declared, boundedremedy.UnprovableSeparation), f'10s clears nothing: {declared}'
    assert 'never widen the allowance' in str(declared)


def test_the_wall_terminates_the_whole_tree_rather_than_the_wrapper() -> None:
    """THE INCIDENT, AS A TEST, RUN FOR REAL: a grandchild holding stdout must not hold the wall."""
    elapsed = boundedremedy.assert_the_wall_terminates_the_tree(
        interpreter=boundedremedy.default_interpreter(),
        wall_seconds=WALL_SECONDS,
        reap_ceiling_seconds=REAP_CEILING_SECONDS,
        overhead_multiple=OVERHEAD_MULTIPLE,
        separation_factor=SEPARATION_FACTOR,
    )
    assert elapsed < boundedremedy.CHILD_LIFETIME_SECONDS / SEPARATION_FACTOR, (
        f'{elapsed:.1f}s is within a quarter of the child lifetime -- the arm returned the margin it '
        f'allowed rather than the margin it had'
    )


def test_a_run_inside_the_wall_is_left_alone() -> None:
    """THE OTHER SIDE: a bound that also breaks the passing case is a fault."""
    boundedremedy.assert_a_run_inside_the_wall_is_left_alone(
        interpreter=boundedremedy.default_interpreter(), wall_seconds=60.0
    )


def test_a_bound_that_returned_without_raising_is_reported_as_a_tree_that_never_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PLANTED THE OTHER WAY: a call that came back cleanly must NOT read as a successful bound.

    `run_bounded` is lent a body that returns a finished process instead of raising, which is what a
    spawn that silently failed looks like from the clock's side -- fast, quiet and indistinguishable
    from a perfect reap. Without this branch the arm reports green when nothing was ever bounded,
    which is the vacuous-green shape a tool that REFUSED produces: the lane whose
    `ruff check --per-file-ignores ''` errored, grepped its empty output, and reported every waiver
    as already spent.
    """
    done = subprocess.CompletedProcess(args=['x'], returncode=0, stdout='', stderr='')
    monkeypatch.setattr(bounded, 'run_bounded', lambda *_args, **_kwargs: done)
    with pytest.raises(AssertionError, match='planted tree did not start'):
        boundedremedy.assert_the_wall_terminates_the_tree(
            interpreter=boundedremedy.default_interpreter(),
            wall_seconds=WALL_SECONDS,
            reap_ceiling_seconds=REAP_CEILING_SECONDS,
            overhead_multiple=OVERHEAD_MULTIPLE,
            separation_factor=SEPARATION_FACTOR,
        )


def test_the_reaper_refuses_its_own_lineage_and_still_kills_what_is_not_ours() -> None:
    """BOTH SIDES OF THE SPARING, both live: our own tree survives, a planted one does not."""
    boundedremedy.assert_the_reaper_refuses_its_own_lineage()
    boundedremedy.assert_the_reaper_kills_what_is_not_ours(
        interpreter=boundedremedy.default_interpreter(), exit_ceiling_seconds=20.0
    )


def test_each_state_names_its_own_remedy() -> None:
    """The live reading, at this repo's own capacity and its own word for a wider tier."""
    capacity = max(bounded.logical_cores(), 4)
    boundedremedy.assert_each_state_names_its_own_remedy(
        capacity=capacity, wider_tier='a heavy run with an explicit go-ahead', narrowed_workers=bounded.NARROWED_FLOOR
    )


def test_a_collapsed_refusal_is_NAMED_by_the_state_that_collapsed(monkeypatch: pytest.MonkeyPatch) -> None:
    """PLANTED THROUGH THE REAL ARM: one sentence for three states must red, and say WHICH pair.

    A count could only say that three became two. The refusal names the states, because the fix is in
    whichever branch of `wall_reason` stopped distinguishing itself and a digit points at none of them.
    """
    monkeypatch.setattr(bounded, 'wall_reason', lambda **_: 'one sentence naming A TIER for every state')
    with pytest.raises(AssertionError, match=r"\['healthy', 'narrowed', 'unmeasured'\]"):
        boundedremedy.assert_each_state_names_its_own_remedy(
            capacity=8, wider_tier='A TIER', narrowed_workers=bounded.NARROWED_FLOOR
        )


def test_a_producer_that_builds_a_refusal_from_a_blank_tier_reds(monkeypatch: pytest.MonkeyPatch) -> None:
    """THE OTHER PLANT, AND IT REPLACES ONE THAT COULD NOT FAIL THE SHIPPED BODY.

    The clause this stands in for asserted ``wider_tier in text``, which every branch of the real
    `wall_reason` satisfies by interpolation -- so it convicted only a monkeypatched fake, and a
    consumer lane drove the real body on an absent tier word and got no refusal in either lab. What
    is planted now is a producer that ACCEPTS a blank tier, which is a shape a real implementation
    can have and which the real one had until 2026-09-18.
    """
    monkeypatch.setattr(bounded, 'wall_reason', lambda *, workers, capacity, **_: f'{workers} of {capacity}')
    with pytest.raises(AssertionError, match='built a refusal from a blank tier'):
        boundedremedy.assert_each_state_names_its_own_remedy(
            capacity=8, wider_tier='a tier this repo uses', narrowed_workers=bounded.NARROWED_FLOOR
        )


def test_the_blank_tier_clause_is_driven_on_the_real_body_and_passes_only_since_the_refusal() -> None:
    """THE SHIPPED PRODUCER, not a stand-in: a blank tier is refused at every one of the three states.

    This is the arm the replaced clause should have been. It fails against `wall_reason` as it stood
    yesterday, which is the property the clause it replaces never had.
    """
    for workers in (None, bounded.NARROWED_FLOOR, 8):
        with pytest.raises(ValueError, match='blank wider_tier'):
            bounded.wall_reason(workers=workers, capacity=8, wider_tier='   ')


def test_the_planted_parent_really_spawns_a_grandchild_that_outlives_the_wall() -> None:
    """THE PREMISE OF THE WHOLE FILE, checked rather than assumed.

    If the snippet stopped spawning a grandchild, every timing arm above would keep passing against
    the very implementation the rule was written about -- a green that proves the opposite of what it
    is read as. So the snippet's own text is asserted, and the lifetime it sleeps is read out of the
    module rather than restated here.
    """
    assert 'subprocess.Popen' in boundedremedy.PARENT_HOLDING_A_GRANDCHILD, 'no grandchild, no inherited pipe'
    assert f'time.sleep({int(boundedremedy.CHILD_LIFETIME_SECONDS)})' in boundedremedy.PARENT_HOLDING_A_GRANDCHILD
    assert boundedremedy.CHILD_LIFETIME_SECONDS > WALL_SECONDS * SEPARATION_FACTOR


def test_the_arms_are_bounded_even_when_they_fail() -> None:
    """A guard against unbounded waits may not itself wait forever, so the failing paths are timed."""
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        bounded.run_bounded(
            [boundedremedy.default_interpreter(), '-c', boundedremedy.PARENT_HOLDING_A_GRANDCHILD],
            timeout=WALL_SECONDS,
            text=True,
        )
    assert time.monotonic() - started < boundedremedy.CHILD_LIFETIME_SECONDS / SEPARATION_FACTOR
