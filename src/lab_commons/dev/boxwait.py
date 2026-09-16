"""The VISIBLE, BOUNDED wait for this box's one seat -- the adoption half of :mod:`.boxlock`.

WHY IT IS ITS OWN MODULE. ``boxlock`` states the RULE (one CPU-saturating run at a time, as a
box-scoped structural seat) and the broker under it enforces it. Neither says what a dev TIER should
do when it finds the box held, and that is a policy with three wrong answers and one right one:
start anyway (the harm), refuse instantly (a re-run loop), block forever (a crash rendered as a
hang). This module is the fourth: queue on a deadline, say who you are waiting for while you wait,
and refuse NAMING the holder when the deadline passes.

It is separate from :mod:`lab_commons.dev.verify` because verify is one adopter and not the only
one -- a gate runner in a sibling repo needs the same three lines and must not reimplement them, and
an entry point that reimplemented them would be the second definition this family keeps paying for.
"""

from __future__ import annotations

import contextlib
import time
from typing import Final

from lab_commons.dev.boxlock import BoxLock
from lab_commons.log import emit
from lab_commons.resources import Exhausted

__all__ = ['PROGRESS_S', 'WAIT_S', 'hold_the_box', 'holders_line']

#: The CEILING ON THE WAIT for the box, in seconds -- 30 minutes, the same bound this family's gate
#: tier already carries, so a run queued behind a gate cannot outlive the thing it queues behind.
#: It bounds the WAIT and never the RUN: once admitted, a run takes as long as it takes.
#:
#: WHY A WAIT AT ALL, AND WHY NOT AN UNBOUNDED ONE. Refusing instantly hands an agent a refusal it
#: can do nothing with, and the predictable response is a re-run loop -- the busy-wait a poll exists
#: to replace. Waiting forever converts a crash into a hang, and it also contradicts what
#: INCONCLUSIVE means here: "nobody knows yet" is a thing a run has to RETURN in order to say.
WAIT_S: Final = 1800.0

#: How often the wait SAYS SOMETHING, in seconds. A silent queue and a hung process look identical
#: from a terminal -- measured on this family 2026-09-16, where a frozen log mtime read as a hang for
#: 26 minutes while pytest was working the whole time (`lab_commons.dev.verify._tee`). A queue that
#: names who it is waiting for reproduces none of that.
PROGRESS_S: Final = 60.0


def hold_the_box(stack: contextlib.ExitStack, what: str, *, wait_s: float, poll_s: float) -> None:
    """Take the box's ONE seat for the life of *stack*, queueing VISIBLY, or raise naming the holder.

    THE ADOPTION THIS EXISTS TO MAKE, measured missing 2026-09-16: ``lab_commons.dev.verify`` took
    NO lock, a sibling repo ran it for ~194 CPU-minutes holding ~17 GB, and a repo that DID take a
    lock computed 2 workers from what was left and had to report INCONCLUSIVE. A lock only one party
    takes is a tax on whoever obeys it, so the party that took none takes this one.

    THE SEAT IS THE EXCLUSION AND NO MEMORY IS DECLARED HERE. ``BoxLock``'s ``demands`` is what a
    caller expects to CONSUME, and a test-suite driver does not know -- its footprint is whatever
    the suite under it allocates, per repo and per selection. An invented number is a declaration
    the code cannot honour; the seat, one CPU-saturating run at a time, is what the harm needed.

    THE QUEUE IS THIS FUNCTION'S AND NOT THE BROKER'S, deliberately. ``Broker.admit`` queues on the
    same deadline and poll, but SILENTLY -- and a silent queue is indistinguishable from a hang at a
    terminal, the exact misreading ``verify._tee`` records for 2026-09-16. So the take is re-issued
    with ``wait_s=0`` on a loop this function narrates. The EXCLUSION stays the broker's entirely:
    every attempt is a real atomic take.

    Args:
        stack: the caller's exit stack. The grant is entered onto it, so the seat is held for
            exactly the block being protected and released however that block ends.
        what: what this run IS, as the refusal will print it for the next reader.
        wait_s: ceiling on the wait. ``0`` checks once and refuses.
        poll_s: seconds between attempts.

    Raises:
        Exhausted: still held when the wait ran out. NOT wrapped in a new class -- the broker's
            refusal already carries the pool, the dimension and the live holders, and a second
            spelling here would be a second definition of "the box is busy".

    """
    lock = BoxLock(what, wait_s=0.0)
    started = time.monotonic()
    deadline = started + max(0.0, wait_s)
    announced: float | None = None
    while True:
        try:
            stack.enter_context(lock.held())
        except Exhausted as exhausted:
            waited = time.monotonic() - started
            if time.monotonic() >= deadline:
                raise
            if announced is None or waited - announced >= PROGRESS_S:
                announced = waited
                emit(f'{what}: waiting {waited:.0f}s for the box. Held by: {holders_line(exhausted)}', flush=True)
            time.sleep(min(poll_s, max(0.0, deadline - time.monotonic())))
        else:
            return


def holders_line(exhausted: Exhausted) -> str:
    """Who is in the way, as one line. NAMED, because "busy" cannot be acted on.

    A reader of this line has to choose between waiting, stopping a holder and giving up, and only
    the names separate those three.
    """
    return '; '.join(holder.describe() for holder in exhausted.holders) or 'a holder this broker cannot name'
