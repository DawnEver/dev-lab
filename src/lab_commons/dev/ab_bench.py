"""A/B an IN-PROCESS seam on a shared box: interleaved arms, recorded refusals, and no invented number.

WHY A SECOND BENCH MODULE. :mod:`lab_commons.dev.shadow_build` already alternates two arms, but it
alternates CHILD PROCESSES: one probe script, two ``PYTHONPATH`` environments, exactly two arms, and
an arm that exits non-zero is a hard error because a dead child is FAST. That shape cannot host the
other measurement this family keeps needing -- a seam INSIDE the interpreter, timed over the same
captured input, where there are more than two candidates, where one candidate legitimately REFUSES
an input the other accepts, and where one arm pays a one-time setup the others do not. Those are
different failure modes, so they are different functions rather than flags on one.

THE FOUR PROPERTIES THIS HOLDS, each of which is a way a benchmark has actually lied here:

* ALTERNATED, NEVER BLOCKED. A box shared with concurrent runs drifts, and a block design charges
  every bit of that drift to whichever arm was running while it happened. :func:`interleave` runs
  every arm once per round.
* A REFUSAL IS A RESULT. An arm that rejects an input its rivals accept has answered the question,
  and aborting the sweep there hides the answer behind a missing row. The refusal is RECORDED and
  the arm is left without a sample for that round -- while :meth:`ArmSamples.median_s` reports
  ``None`` rather than a median over the rounds that happened to succeed, because a candidate timed
  only on the inputs it likes is not a candidate that was measured.
* SETUP IS AMORTISED OVER A MEASURED COUNT, NEVER OVER 1 AND NEVER OVER NOTHING. A cached
  factorisation, a compiled plan, a warmed connection: quoting the per-call half without its setup
  is the declaration-that-lies defect wearing a stopwatch. :func:`amortised` demands the recurrence
  count the caller MEASURED, and refuses a count of zero.
* A FASTER ANSWER IS NOT THE SAME ANSWER. Two arms that disagree numerically are a correctness
  decision, not a speed one, so :meth:`Trials.disagreement` puts the size of the disagreement in the
  same table as the ratio. The DISTANCE is the caller's, because what counts as a difference is a
  property of the values, which this module cannot see.

AND THE VERDICT IT REFUSES TO FAKE. A seam faster on one input and slower on another is a DISPATCH,
not a port, and a dispatch needs a threshold. :func:`crossover` asks whether one exists -- whether
some size separates every loss from every win -- and when the winner changes BACK as size grows it
returns no threshold and NAMES the pairs that forbid one. That negative is the expensive finding:
measured in motronics-studio 2026-09-04 over three sparse systems within 11 % of each other in
order, the ratios ran 0.81, 1.70, 0.78, so the two points a migration had reasoned from were two
different inputs rather than two points on a curve.

NOTHING HERE TIMES A SUBPROCESS, TOUCHES THE FILESYSTEM, OR IMPORTS THE CODE UNDER TEST. The caller
brings its arms already bound; this brings the discipline.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

__all__ = [
    'MIN_CROSSOVER_POINTS',
    'ArmSamples',
    'Crossover',
    'Trials',
    'amortised',
    'crossover',
    'interleave',
    'ratio',
]

#: The fewest measured points a crossover question may be asked over. TWO, because one point cannot
#: distinguish "the candidate always wins" from "the candidate wins above this size" -- it agrees
#: with both, and a threshold derived from it would be a size the sweep never bracketed. A floor
#: rather than a silent empty answer: a crossover "found" over no data reads exactly like one that
#: was measured.
MIN_CROSSOVER_POINTS: Final = 2


@dataclass(frozen=True, slots=True)
class ArmSamples:
    """One arm's raw samples, its refusals, and the last answer it produced.

    RAW SAMPLES ARE KEPT, not just the median. A single timing off a busy box is an anecdote, and a
    reader who cannot see the spread cannot tell a 10 % difference from the box.
    """

    name: str
    samples_s: tuple[float, ...]
    refusals: tuple[str, ...]
    value: Any = None

    @property
    def median_s(self) -> float | None:
        """The median sample, or ``None`` when this arm REFUSED at any point or produced nothing.

        A refusal poisons the median DELIBERATELY. An arm that rejected some rounds and was timed on
        the rest has been measured on a subset it selected for itself, and reporting that as its
        speed is the most flattering possible lie about a candidate -- the arm that bails out early
        on the hard inputs wins. ``None`` says "not comparable", which is the truth; the refusals
        are right there to explain it.
        """
        if self.refusals or not self.samples_s:
            return None
        return statistics.median(self.samples_s)


@dataclass(frozen=True, slots=True)
class Trials:
    """Every arm of one interleaved run, keyed by the caller's names."""

    arms: Mapping[str, ArmSamples]
    rounds: int

    def median_s(self, name: str) -> float | None:
        """*name*'s median, or ``None`` -- see :meth:`ArmSamples.median_s`."""
        return self.arms[name].median_s

    @property
    def refused(self) -> tuple[str, ...]:
        """Every arm that refused at least once, sorted. Empty is a real answer here, not a silence."""
        return tuple(sorted(name for name, arm in self.arms.items() if arm.refusals))

    def speedup(self, baseline: str, candidate: str) -> float | None:
        """*baseline*'s median over *candidate*'s: ``> 1`` means the candidate wins.

        ``None`` when either arm has no comparable median, or when the candidate's median is zero --
        a zero-second median means the arm did not do the work, and "I cannot say" is the honest
        report of that. A number would be read as a result, and an arm that refused would be
        averaged into a win or a loss it never earned.
        """
        base = self.median_s(baseline)
        cand = self.median_s(candidate)
        if base is None or not cand:
            return None
        return base / cand

    def disagreement(self, left: str, right: str, distance: Callable[[Any, Any], float]) -> float | None:
        """How far apart the two arms' ANSWERS are, by the caller's *distance*.

        THE DISTANCE IS THE CALLER'S and is not defaulted. A relative norm, an absolute difference
        and a symmetric-difference count are all correct for some pair of values and wrong for the
        others, so a default here would silently pick one and present it as measured. Passing it
        keeps the choice visible at the site that owns the values -- the same reason
        :mod:`lab_commons.dev.shadow_build` takes its caller's wall and manifest.

        ``None`` when either arm never produced a value, because there is nothing to compare.
        """
        left_arm, right_arm = self.arms[left], self.arms[right]
        if not left_arm.samples_s or not right_arm.samples_s:
            return None
        return float(distance(left_arm.value, right_arm.value))


def interleave(
    arms: Mapping[str, Callable[[], Any]],
    *,
    repeat: int,
    refuse_on: type[BaseException] | tuple[type[BaseException], ...] = (),
) -> Trials:
    """Run every arm once per round, *repeat* rounds, and return each arm's samples.

    ROUND-ROBIN IN DECLARATION ORDER. The alternation is the whole point: it does not remove the
    box's noise, it stops the noise being ATTRIBUTED to one arm.

    Args:
        arms: name -> a zero-argument callable that does the work and returns its answer. The caller
            binds its own inputs in; nothing here knows what is being measured.
        repeat: rounds. Must be positive.
        refuse_on: the exception types that count as an arm REFUSING this input rather than as a
            defect. EMPTY BY DEFAULT, and that direction matters: a harness that swallowed every
            exception by default would turn the fastest possible failure -- raising immediately --
            into an arm with no samples and no complaint. A caller declares which refusal its
            candidate is entitled to make; everything else propagates.

    Returns:
        A :class:`Trials` carrying every arm's raw samples, refusals and last answer.

    Raises:
        ValueError: *arms* is empty, or *repeat* is not positive. Either produces empty sample sets,
            and a median of nothing raises somewhere further from the mistake than here.

    """
    if not arms:
        msg = 'interleave() over no arm measures nothing; there is no comparison to make.'
        raise ValueError(msg)
    if repeat <= 0:
        msg = (
            f'repeat={repeat} runs no round at all, so no arm is sampled. A benchmark that '
            f'collected nothing must refuse HERE rather than hand empty sets to a median.'
        )
        raise ValueError(msg)

    samples: dict[str, list[float]] = {name: [] for name in arms}
    refusals: dict[str, list[str]] = {name: [] for name in arms}
    values: dict[str, Any] = dict.fromkeys(arms)
    for _ in range(repeat):
        for name, call in arms.items():
            started = time.perf_counter()
            try:
                answer = call()
            except refuse_on as exc:
                refusals[name].append(f'{type(exc).__name__}: {exc}')
                continue
            samples[name].append(time.perf_counter() - started)
            values[name] = answer
    return Trials(
        arms={
            name: ArmSamples(
                name=name,
                samples_s=tuple(samples[name]),
                refusals=tuple(refusals[name]),
                value=values[name],
            )
            for name in arms
        },
        rounds=repeat,
    )


def amortised(per_call_s: float, setup_s: float, *, over: int) -> float:
    """*per_call_s* plus *setup_s* spread across *over* calls: what the cached arm actually costs.

    THE COUNT IS MEASURED BY THE CALLER, never defaulted to 1 and never assumed large. How often a
    setup is reused is a property of the workload, and a harness that guessed it would be choosing
    the proposal's own score.

    Raises:
        ValueError: *over* is not positive. Zero reuses make the setup free by arithmetic, which is
            the most favourable number in the table arriving from a division nobody chose.

    """
    if over <= 0:
        msg = (
            f'over={over} amortises a one-time cost across no call at all. A setup reused zero '
            f'times is not free: it is paid in full by the one call that took it.'
        )
        raise ValueError(msg)
    return per_call_s + setup_s / over


def ratio(baseline_s: float | None, candidate_s: float | None) -> float | None:
    """*baseline_s* over *candidate_s*, or ``None`` when either is missing or the candidate is zero.

    The free-function form of :meth:`Trials.speedup`, for rows measured elsewhere -- a stored table
    of past results, or an arm assembled by :func:`amortised`.
    """
    if baseline_s is None or not candidate_s:
        return None
    return baseline_s / candidate_s


@dataclass(frozen=True, slots=True)
class Crossover:
    """Whether a size threshold separates the candidate's losses from its wins.

    ``threshold`` is ``None`` whenever no single size does. ``inversions`` says WHY, by naming the
    pairs, because "no threshold" as a bare boolean is unactionable and invites being overridden
    with a number somebody picked.
    """

    threshold: float | None
    inversions: tuple[tuple[str, str], ...]
    excluded: tuple[str, ...]
    reason: str


def crossover(points: Mapping[str, tuple[float, float | None]]) -> Crossover:
    """Ask whether the ratios in *points* admit a dispatch threshold on size.

    A threshold exists when, ordering by size, every loss precedes every win: below it the baseline
    wins, at or above it the candidate does. It does NOT exist when the winner changes back -- a
    smaller input the candidate wins paired with a larger one it loses. Those pairs are returned.

    Args:
        points: name -> ``(size, ratio)``, where *ratio* is baseline over candidate, so ``> 1`` is a
            candidate win. ``None`` is a REFUSAL: the row is EXCLUDED and named, never folded in as
            a loss. A refusal is neither a win nor a loss, and averaging it into one is how a guard
            doing its job comes to read as a performance defect.

    Returns:
        A :class:`Crossover` whose ``reason`` states which of the four shapes was found.

    Raises:
        ValueError: fewer than :data:`MIN_CROSSOVER_POINTS` rows survive the exclusion. See that
            constant for why a threshold over one point is not a measurement.

    """
    excluded = tuple(sorted(name for name, (_size, rat) in points.items() if rat is None))
    rows = sorted(
        ((float(size), name, float(rat)) for name, (size, rat) in points.items() if rat is not None),
        key=lambda row: (row[0], row[1]),
    )
    if len(rows) < MIN_CROSSOVER_POINTS:
        msg = (
            f'{len(rows)} measured point(s) after excluding {len(excluded)} refusal(s) cannot '
            f'bracket a crossover: at least {MIN_CROSSOVER_POINTS} are needed for a threshold to '
            f'mean anything, since one point agrees with every threshold below it.'
        )
        raise ValueError(msg)

    inversions = tuple(
        (rows[i][1], rows[j][1])
        for i in range(len(rows))
        for j in range(i + 1, len(rows))
        if rows[i][2] > 1.0 >= rows[j][2]
    )
    if inversions:
        pairs = ', '.join(f'{win} wins but the larger {loss} does not' for win, loss in inversions)
        return Crossover(
            threshold=None,
            inversions=inversions,
            excluded=excluded,
            reason=(
                f'the winner changes back as size grows ({pairs}), so no size separates the losses '
                f'from the wins. What decides the winner here is not size, and a threshold written '
                f'anyway would be a dispatch on the wrong variable.'
            ),
        )

    wins = [row for row in rows if row[2] > 1.0]
    if not wins:
        return Crossover(
            threshold=None,
            inversions=(),
            excluded=excluded,
            reason=(
                f'the candidate does not win at any measured size (largest measured: '
                f'{rows[-1][0]:g}). There is nothing above a threshold to dispatch to.'
            ),
        )
    threshold = wins[0][0]
    if threshold == rows[0][0]:
        return Crossover(
            threshold=threshold,
            inversions=(),
            excluded=excluded,
            reason=(
                f'the candidate wins at every measured size, so the crossover is at or BELOW the '
                f'smallest point measured ({threshold:g}) and was not bracketed. Treat it as an '
                f'upper bound on the threshold, not as the threshold.'
            ),
        )
    return Crossover(
        threshold=threshold,
        inversions=(),
        excluded=excluded,
        reason=(
            f'every loss precedes every win by size; the candidate first wins at {threshold:g}, '
            f'bracketed from below by a measured loss.'
        ),
    )
