"""``lab_commons.dev.ab_bench`` -- driven over REAL callables, a REAL clock and REAL exceptions.

NOTHING HERE IS MOCKED, including the thing that is hardest not to mock: time. The arms below do
actual work -- a busy loop of a chosen duration -- and the assertions about ordering are made with
enough slack to survive a box that is shared with a multi-hour run, which is the box this family
always measures on. An assertion tight enough to be flaky would get loosened, and a loosened timing
assertion is a test that passes for a reason nobody can state.

BOTH DIRECTIONS, EVERYWHERE. A harness that records every arm as refusing and one that records none
both pass a one-sided test, so every refusal case plants a REFUSING arm beside a SUCCEEDING one and
asserts the two came out different. The same for the crossover: a "no threshold" answer is checked
against a set that HAS one, so an implementation that always answered ``None`` would red.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import pytest

from lab_commons.dev.ab_bench import (
    MIN_CROSSOVER_POINTS,
    ArmSamples,
    Trials,
    amortised,
    crossover,
    interleave,
    ratio,
)

#: How long a "slow" arm busies itself, in seconds. Chosen so the gap against the fast arm survives
#: another lane's gate taking the cores: the fast arm would have to be delayed by this much, in the
#: MEDIAN of its rounds, to invert the ordering.
SLOW_S = 0.05


def _busy(seconds: float) -> float:
    """A real workload: spin until *seconds* of wall clock have passed, then return how long it took.

    A busy loop rather than ``sleep`` because ``sleep`` yields the CPU, and an arm that yields is
    exactly the arm a contended box treats most unlike real work.
    """

    def arm() -> float:
        started = time.perf_counter()
        while time.perf_counter() - started < seconds:
            pass
        return time.perf_counter() - started

    return arm


class TestInterleave:
    def test_every_arm_runs_once_per_round_in_declaration_order(self) -> None:
        """The alternation is the mechanism, so the ORDER is asserted, not just the sample counts.

        The floor is the total: a harness that ran nothing would produce an empty order list, which
        an ``order == expected`` check over an empty expectation would happily accept.
        """
        order: list[str] = []

        def note(name: str) -> Callable[[], str]:
            def arm() -> str:
                order.append(name)
                return name

            return arm

        trials = interleave({'a': note('a'), 'b': note('b'), 'c': note('c')}, repeat=4)

        assert len(order) == 12, 'floor: three arms over four rounds must have run twelve times'
        assert order == ['a', 'b', 'c'] * 4, 'arms must alternate per round, never block per arm'
        assert trials.rounds == 4
        assert all(len(trials.arms[name].samples_s) == 4 for name in 'abc')

    def test_a_slower_arm_measures_slower_and_every_sample_is_positive(self) -> None:
        """Real work, real clock. The floor: a harness returning zeros would fail the positivity."""
        trials = interleave({'fast': _busy(0.0), 'slow': _busy(SLOW_S)}, repeat=5)

        fast, slow = trials.median_s('fast'), trials.median_s('slow')
        assert fast is not None
        assert slow is not None
        assert all(sample > 0.0 for arm in trials.arms.values() for sample in arm.samples_s)
        assert slow > fast, f'the {SLOW_S}s arm measured {slow}s against the empty arm at {fast}s'
        speedup = trials.speedup('slow', 'fast')
        assert speedup is not None
        assert speedup > 1.0

    def test_a_declared_refusal_is_recorded_and_its_sibling_is_unharmed(self) -> None:
        """BOTH DIRECTIONS: the refusing arm loses its samples, the sibling keeps every one of them."""
        rounds = 3

        def refuses() -> float:
            msg = 'residual 17.9 exceeds the guard'
            raise ValueError(msg)

        trials = interleave({'good': _busy(0.0), 'picky': refuses}, repeat=rounds, refuse_on=ValueError)

        assert len(trials.arms['good'].samples_s) == rounds, 'a sibling refusal must not cost a sample'
        assert trials.arms['good'].refusals == ()
        assert trials.arms['picky'].samples_s == (), 'a refused round contributes no timing'
        assert len(trials.arms['picky'].refusals) == rounds
        assert 'residual 17.9' in trials.arms['picky'].refusals[0]
        assert trials.refused == ('picky',), 'exactly the refusing arm is named'

    def test_an_undeclared_exception_propagates_rather_than_becoming_a_refusal(self) -> None:
        """A defect is not a refusal. The control is the same arm under a declared ``refuse_on``."""

        def broken() -> float:
            msg = 'the seam was never bound'
            raise AttributeError(msg)

        with pytest.raises(AttributeError, match='never bound'):
            interleave({'broken': broken}, repeat=2, refuse_on=ValueError)

        tolerated = interleave({'broken': broken}, repeat=2, refuse_on=AttributeError)
        assert len(tolerated.arms['broken'].refusals) == 2, 'declared, the SAME raise is recorded'

    def test_the_last_answer_of_each_arm_is_kept_for_the_disagreement(self) -> None:
        trials = interleave({'left': lambda: 1.0, 'right': lambda: 1.25}, repeat=2)

        gap = trials.disagreement('left', 'right', lambda a, b: abs(a - b) / abs(a))
        assert gap == pytest.approx(0.25, abs=1e-12), 'floor: a nonzero planted gap, not 0.0'

    def test_a_disagreement_against_an_arm_that_never_answered_is_none(self) -> None:
        def refuses() -> float:
            msg = 'no'
            raise ValueError(msg)

        trials = interleave({'left': lambda: 1.0, 'right': refuses}, repeat=2, refuse_on=ValueError)

        assert trials.disagreement('left', 'right', lambda a, b: abs(a - b)) is None
        assert trials.disagreement('left', 'left', lambda a, b: abs(a - b)) == 0.0

    @pytest.mark.parametrize(
        ('arms', 'repeat', 'fragment'),
        [
            ({}, 3, 'no arm'),
            ({'a': lambda: None}, 0, 'repeat=0'),
            ({'a': lambda: None}, -1, 'repeat=-1'),
        ],
    )
    def test_an_empty_measurement_refuses_at_the_call(self, arms, repeat, fragment) -> None:
        with pytest.raises(ValueError, match=fragment):
            interleave(arms, repeat=repeat)


class TestArmSamples:
    def test_a_refusal_poisons_the_median_and_the_identical_samples_without_one_do_not(self) -> None:
        """The two-sided control: SAME samples, one arm carrying a refusal, different verdicts."""
        samples = (0.1, 0.2, 0.3)
        clean = ArmSamples(name='clean', samples_s=samples, refusals=())
        partial = ArmSamples(name='partial', samples_s=samples, refusals=('ValueError: singular',))

        assert clean.median_s == pytest.approx(0.2)
        assert partial.median_s is None, 'an arm measured only on the inputs it accepted is not comparable'

    def test_an_arm_with_no_sample_has_no_median(self) -> None:
        assert ArmSamples(name='empty', samples_s=(), refusals=()).median_s is None


class TestSpeedup:
    def _trials(self, **arms: ArmSamples) -> Trials:
        return Trials(arms=arms, rounds=3)

    def test_a_refused_arm_is_never_averaged_into_a_win_or_a_loss(self) -> None:
        trials = self._trials(
            base=ArmSamples(name='base', samples_s=(0.4,), refusals=()),
            cand=ArmSamples(name='cand', samples_s=(0.2,), refusals=('ValueError: singular',)),
        )
        assert trials.speedup('base', 'cand') is None, 'the faster-looking refuser must not score 2x'

        honest = self._trials(
            base=ArmSamples(name='base', samples_s=(0.4,), refusals=()),
            cand=ArmSamples(name='cand', samples_s=(0.2,), refusals=()),
        )
        assert honest.speedup('base', 'cand') == pytest.approx(2.0), 'the control: without the refusal it is 2x'

    def test_a_zero_median_candidate_reports_no_speedup_rather_than_infinity(self) -> None:
        trials = self._trials(
            base=ArmSamples(name='base', samples_s=(0.4,), refusals=()),
            cand=ArmSamples(name='cand', samples_s=(0.0,), refusals=()),
        )
        assert trials.speedup('base', 'cand') is None


class TestRatio:
    @pytest.mark.parametrize(
        ('base', 'cand', 'expected'),
        [(0.4, 0.2, 2.0), (0.2, 0.4, 0.5), (None, 0.2, None), (0.4, None, None), (0.4, 0.0, None)],
    )
    def test_the_free_function_matches_the_method_and_refuses_the_same_shapes(self, base, cand, expected) -> None:
        got = ratio(base, cand)
        if expected is None:
            assert got is None
        else:
            assert got == pytest.approx(expected)


class TestAmortised:
    def test_a_setup_reused_many_times_costs_less_per_call_than_one_reused_once(self) -> None:
        """Both directions of the amortisation, so a function ignoring ``over`` would red."""
        assert amortised(0.01, 1.0, over=100) == pytest.approx(0.02)
        assert amortised(0.01, 1.0, over=1) == pytest.approx(1.01)

    @pytest.mark.parametrize('over', [0, -5])
    def test_a_non_positive_reuse_count_refuses_rather_than_making_the_setup_free(self, over) -> None:
        with pytest.raises(ValueError, match='not free'):
            amortised(0.01, 1.0, over=over)


class TestCrossover:
    def test_a_clean_threshold_is_found_and_bracketed_from_below(self) -> None:
        got = crossover({'tiny': (100.0, 0.5), 'small': (1000.0, 0.9), 'big': (10000.0, 1.8)})

        assert got.threshold == 10000.0
        assert got.inversions == ()
        assert 'bracketed from below' in got.reason

    def test_a_winner_that_changes_back_forbids_a_threshold_and_the_pairs_are_named(self) -> None:
        """The motronics shape: three points within 11 % of each other, ratios 0.81 / 1.70 / 0.78.

        Its control is the test above -- the SAME function over a monotone set returns a threshold --
        so an implementation that always refused would fail there.
        """
        got = crossover(
            {
                'ipm_uv_cummins_fea': (31901.0, 0.81),
                'pmasynrm_uv_fea': (32572.0, 1.70),
                'ipm_uv_fea': (35430.0, 0.78),
            }
        )

        assert got.threshold is None
        assert got.inversions == (('pmasynrm_uv_fea', 'ipm_uv_fea'),)
        assert 'changes back' in got.reason
        assert 'dispatch on the wrong variable' in got.reason

    def test_a_candidate_that_never_wins_is_distinguished_from_one_that_always_does(self) -> None:
        never = crossover({'a': (100.0, 0.4), 'b': (200.0, 0.9)})
        always = crossover({'a': (100.0, 1.4), 'b': (200.0, 1.9)})

        assert never.threshold is None
        assert 'does not win at any measured size' in never.reason
        assert always.threshold == 100.0
        assert 'upper bound on the threshold' in always.reason, 'an unbracketed crossover says so'

    def test_a_refusal_is_excluded_and_named_rather_than_counted_as_a_loss(self) -> None:
        """BOTH DIRECTIONS: as ``None`` the row is excluded; as a real loss it forbids the threshold."""
        excluded = crossover({'singular': (157.0, None), 'a': (1000.0, 1.2), 'b': (2000.0, 1.4)})
        assert excluded.excluded == ('singular',)
        assert excluded.threshold == 1000.0

        counted = crossover({'singular': (157.0, 0.1), 'a': (1000.0, 1.2), 'b': (2000.0, 1.4)})
        assert counted.excluded == ()
        assert counted.threshold == 1000.0
        assert 'bracketed from below' in counted.reason, 'as a measured loss it BRACKETS the same threshold'

    def test_a_ratio_of_exactly_one_is_not_a_win(self) -> None:
        """A tie is not a reason to dispatch. Planted at the largest size so a win would show."""
        got = crossover({'a': (100.0, 0.5), 'b': (200.0, 1.0)})
        assert got.threshold is None

    @pytest.mark.parametrize(
        'points',
        [
            {},
            {'only': (100.0, 1.5)},
            {'only': (100.0, 1.5), 'refused': (200.0, None)},
        ],
    )
    def test_too_few_measured_points_refuse_the_question(self, points) -> None:
        with pytest.raises(ValueError, match='cannot'):
            crossover(points)

    def test_the_floor_constant_is_the_one_the_refusal_enforces(self) -> None:
        """A named floor, not a magic 2: the guard and its constant must not drift apart."""
        enough = {f'row{i}': (float(i + 1) * 100.0, 1.5) for i in range(MIN_CROSSOVER_POINTS)}
        assert crossover(enough).threshold is not None

        with pytest.raises(ValueError, match='crossover'):
            crossover(dict(list(enough.items())[: MIN_CROSSOVER_POINTS - 1]))
