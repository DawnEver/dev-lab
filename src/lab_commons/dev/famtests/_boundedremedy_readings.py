"""THE READINGS a live bounded-wait arm is priced from -- PURE where it can be, calibrated where not.

THE SEAM, and it is the one this package already runs three times (``_datedmemory_readings``,
``_citedtests_readings``, ``_upperbounds_readings``): the VERDICTS next door in
:mod:`lab_commons.dev.famtests.boundedremedy` spawn real process trees and cannot be driven without
one, while everything here is either a pure function of numbers or a single calibrating spawn. That
split is what lets the anti-flake arithmetic be tested exhaustively on a quiet box and on a
pathologically loaded one, without either box existing.

WHY AN ELAPSED-TIME CLAIM NEEDS THIS AT ALL, stated here because this is where the mechanism lives.
An arm that asserts on the clock reds when the box is slow, and the tempting repair -- a bigger wall
-- makes a hang detector strictly worse. So the number is not a constant a reader may raise:

* The claim is a SEPARATION. The planted child outlives the wall by a wide factor, and what is
  asserted is that the call returned nearer its OWN wall than the child's lifetime. Load moves the
  return by seconds; waiting on the tree moves it by the child's whole lifetime.
* The slack is PRICED FROM THIS BOX, in the same second, by :func:`spawn_overhead`. A box four times
  slower is granted four times the slack with nobody editing a constant.
* And the pricing has a CEILING, which is the half that keeps the other two honest. Once the priced
  slack has grown far enough that a genuine wait on the tree would fit inside it, the arm can no
  longer fail and must not report a pass. :func:`separation_verdict` is that reading, and it names
  which of the two it is -- the MACHINE or the DECLARATION -- rather than reporting one refusal for
  both, because the remedies are opposite: wait for a quiet box, or fix the numbers.
"""

from __future__ import annotations

import subprocess
import sys
import time

from lab_commons.dev import bounded

__all__ = [
    'PARENT_HOLDING_A_GRANDCHILD',
    'BoxTooLoaded',
    'UnprovableSeparation',
    'allowance',
    'default_interpreter',
    'separation_verdict',
    'spawn_overhead',
]


class BoxTooLoaded(AssertionError):
    """The box cannot separate a bounded return from a slow one, so this run proved nothing.

    Deliberately NOT a pass and NOT a failure of the code under test. It is this package's
    INCONCLUSIVE: the finding is the machine, and the remedy is to re-measure when the box is quiet
    rather than to raise the wall, which makes a hang detector strictly worse.
    """


class UnprovableSeparation(AssertionError):
    """The DECLARED numbers do not outlive the wall by enough for a pass to have meant anything."""


#: The child the wall is driven against: it sleeps far past the wall AND spawns a grandchild that
#: does too. THE GRANDCHILD IS THE WHOLE POINT -- it inherits the stdout write handle, so the pipe
#: stays open while it lives, which is precisely the shape ``subprocess.run(timeout=...)`` cannot
#: bound. Without it the case passes against the very implementation the rule was written about.
#: BYTE-IDENTICAL in both consumers before this module existed, which is what made it a row.
PARENT_HOLDING_A_GRANDCHILD = (
    'import subprocess, sys, time; '
    "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']); "
    'time.sleep(120)'
)

#: How long the child in :data:`PARENT_HOLDING_A_GRANDCHILD` sleeps. Published beside the snippet so
#: the separation arithmetic reads the number out of the same place the child gets it, rather than a
#: consumer restating it and the two drifting apart -- at which point the arm's own premise is wrong
#: and nothing says so.
CHILD_LIFETIME_SECONDS = 120.0


def default_interpreter() -> str:
    """The running process's own Python, published as a spelling rather than installed as a default.

    A consumer passes this explicitly. An interpreter defaulted inside the kit is the kit's answer
    about which Python a consumer's tree runs under, which is the class of guess this package exists
    to refuse -- and the one whose failure mode is a wider scope rather than an error.
    """
    return sys.executable


def spawn_overhead(*, interpreter: str, ceiling_seconds: float) -> float:
    """How long THIS box takes, right now, to run a bounded child that does nothing.

    The calibration every timing claim is priced from, taken in the same second as the measurement
    it prices -- which is the only reading that is about the box the test is running on rather than
    about the box somebody wrote the constant on.

    Args:
        interpreter: the Python to spawn. No default -- a consumer's test runner and its scripts do
            not always run under the same one, and guessing picks one of them.
        ceiling_seconds: the wall on the calibration itself, so a box that cannot start an
            interpreter at all fails fast instead of hanging inside the anti-hang mechanism.

    Returns:
        Elapsed seconds, always positive so it can be multiplied without collapsing the slack.

    Raises:
        BoxTooLoaded: the trivial child did not finish inside *ceiling_seconds*.

    """
    started = time.monotonic()
    try:
        bounded.run_bounded([interpreter, '-c', 'pass'], timeout=ceiling_seconds, text=True)
    except subprocess.TimeoutExpired as exc:
        msg = (
            f'this box did not start and finish an EMPTY Python child inside {ceiling_seconds}s. That is a '
            f'reading about the MACHINE, so every timing claim priced from it is INCONCLUSIVE rather than '
            f'red: re-measure on a quiet box. Raising the wall would make the hang detector strictly worse.'
        )
        raise BoxTooLoaded(msg) from exc
    return max(time.monotonic() - started, 1e-9)


def allowance(*, reap_ceiling_seconds: float, overhead_seconds: float, overhead_multiple: float) -> float:
    """What a bounded call may take BEYOND its wall on this box: the reap ceiling plus priced slack.

    Args:
        reap_ceiling_seconds: the repo's own measured ceiling on the reap after the kill.
        overhead_seconds: what :func:`spawn_overhead` just read.
        overhead_multiple: how many spawn-overheads of slack a loaded box is granted. No default: it
            prices how much load this repo absorbs before it would rather call a reading
            inconclusive, and that is a repo's answer about its own boxes.

    Returns:
        Seconds of slack above the wall.

    """
    return reap_ceiling_seconds + overhead_multiple * overhead_seconds


def separation_verdict(
    *,
    wall_seconds: float,
    reap_ceiling_seconds: float,
    slack_seconds: float,
    child_lifetime_seconds: float,
    separation_factor: float,
) -> AssertionError | None:
    """Whether a pass would MEAN anything, and if not, WHICH of the two reasons it is.

    PURE, so both refusals are driven on numbers rather than on a box that happens to be loaded.
    The verdict is returned rather than raised for the same reason: a caller decides when to raise,
    and a control can assert on the type without catching anything.

    THE TWO REASONS ARE TOLD APART BY RE-PRICING WITHOUT THE BOX. If the DECLARED numbers alone
    clear the separation, then load ate the margin and the finding is the machine
    (:exc:`BoxTooLoaded`, INCONCLUSIVE). If they do not, the declaration is wrong and no quiet box
    will fix it (:exc:`UnprovableSeparation`). Reporting one sentence for both would send half the
    readers to wait out a load that was never the problem.

    Args:
        wall_seconds: the bound the call is given.
        reap_ceiling_seconds: the repo's measured reap ceiling, with no box contribution in it.
        slack_seconds: what :func:`allowance` priced on this box, which includes that contribution.
        child_lifetime_seconds: how long the planted child sleeps.
        separation_factor: how many times the permitted return this repo requires the child's
            lifetime to be before a pass is evidence at all. No default -- it is the margin this
            repo wants between a bounded return and a wait on the tree.

    Returns:
        ``None`` when the separation holds, else the exception to raise, already carrying its
        sentence and its remedy.

    """
    permitted = wall_seconds + slack_seconds
    if child_lifetime_seconds >= separation_factor * permitted:
        return None
    declared = wall_seconds + reap_ceiling_seconds
    if child_lifetime_seconds >= separation_factor * declared:
        return BoxTooLoaded(
            f'this box priced {slack_seconds:.1f}s of allowance, leaving a permitted return of '
            f'{permitted:.1f}s against a {child_lifetime_seconds}s child -- inside the {separation_factor}x '
            f'separation, so a wait on the tree would now FIT in the allowance and the arm could not fail. '
            f'The declared numbers ({declared:.1f}s) clear it, so the finding is the MACHINE: INCONCLUSIVE, '
            f'and the remedy is a quiet box rather than a wider wall.'
        )
    return UnprovableSeparation(
        f'the planted child sleeps {child_lifetime_seconds}s against a DECLARED permitted return of '
        f'{declared:.1f}s, short of the {separation_factor}x separation this repo requires -- before this box '
        f'contributed anything. A pass would not distinguish a bounded return from a wait on the tree: '
        f'lengthen the child or tighten the wall, never widen the allowance.'
    )
