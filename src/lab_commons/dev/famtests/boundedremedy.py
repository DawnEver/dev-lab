"""A BOUNDED WAIT NAMES ITS REMEDY -- the LIVE half, driven on a real process tree and a real clock.

WHAT THE CONSUMER'S FILE ASSERTS. Three properties of :mod:`lab_commons.dev.bounded`, each with its
violation PLANTED rather than described: a wall terminates the TREE and not the wrapper, a reaper
never kills its own lineage, and a refusal names a DIFFERENT remedy per state. The incident behind
the first is written into both consumers' prose: ``timeout 600 cargo test`` killed the cargo WRAPPER
while the release executable ran forty more minutes at full core count and froze the workstation,
twice. The second is the self-match a rules page asks a HUMAN to notice and ignore, which is exactly
the step that is missing at 2am.

WHY THIS IS A SHARED BODY. Measured 2026-09-18 at each lab's HEAD -- wdg-lab ``ef5fa9fc`` (165 lines)
and optimi-lab ``e3502ec`` (138) -- ``test_a_bounded_wait_names_its_remedy.py`` is a near-twin:
identical ``WALL_SECONDS_LIMIT = 3.0`` and ``REAP_SECONDS_CEILING = 4.0``, a BYTE-IDENTICAL parent
snippet, and 6 of 7 arm names shared. What differs is each repo's own answer -- its ``WIDER_TIER``
wording, the capacity it prices the remedy arm at, the width it calls narrowed, and wdg-lab's extra
arm asserting that the two rule pages this file answers for are still on disk. Those are the keyword
arguments below, with no defaults: a default is one repo's answer handed silently to another.

WHY THIS IS NOT INSIDE :mod:`~lab_commons.dev.famtests.untimedwaits`, which is the nearest neighbour
and shares this module's subject word for word. They are the SCAN and the RUN, and the three measured
differences are the same three that separated ``untimedwaits`` from ``bounded``, pointing the other
way:

* THEY READ NOTHING IN COMMON. ``untimedwaits`` imports ``ast``, takes a ``Path``, and returns a
  pinnable SET of offender sites. This imports ``subprocess``, ``time`` and ``os``, takes an
  interpreter and a clock, and SPAWNS A REAL PROCESS TREE. Measured 2026-09-18, the overlap between
  the two surfaces is EMPTY.
* THE REFUSALS ARE OPPOSITE IN TIME. ``untimedwaits`` refuses BEFORE anything runs, over a whole
  tree, in bulk -- the originating repo found eleven sites at once, and a first-offender exception
  would have reported one of them eleven times. This refuses ONE LIVE WAIT while it is happening.
* ONLY ONE OF THEM HAS A POPULATION. ``untimedwaits`` scans, so its silence is vacuous and every arm
  goes through :mod:`lab_commons.dev.floors` first. This reads no population at all and needs no
  floor. It has a CALIBRATION instead, which is the opposite instrument: a floor asks whether enough
  was read, and a calibration asks whether this box can tell the two answers apart.

NOR IS IT BOLTED ONTO ``dev.bounded``. That module is 293 lines and this body plus its readings and
controls lands past the 400-line band, so the split would have been built in advance -- but the
placement argument decides it without the arithmetic: ``famtests`` is where a body a CONSUMER'S
ARCHITECTURE TEST is judged by lives, and ``dev`` holds the runtime those repos CALL. This is the
first kind. ``untimedwaits``' own docstring already points at ``bounded.wall_reason`` for the
sized-ceiling claim it declines to make; the pointer existed and the module it should have pointed at
did not.

THIS IS THE ONE MODULE IN THIS PACKAGE THAT ASSERTS ON ELAPSED TIME, SO IT IS THE ONE THAT CAN BE
FLAKY, and the answer is not a bigger number -- raising the wall makes a hang detector strictly
worse. The three mechanisms live next door in ``_boundedremedy_readings`` and are stated there: the
claim is a SEPARATION rather than a duration, the slack is PRICED from this box in the same second,
and the pricing has a CEILING past which the arm reports :exc:`~lab_commons.dev.famtests.
_boundedremedy_readings.BoxTooLoaded` -- INCONCLUSIVE, neither green nor red -- because an arm that
can no longer fail must not report a pass. The family's own measurement is why: this box has run four
lanes at once all day, and a gate that normally takes 17 minutes took an hour.

WHAT THIS DOES NOT PROVE, and it is the axis every arm here is blind to. Returning on time says THE
CALL came back; it does not say the grandchild died. A child that crashed on its own produces the
same clock reading as a correct reap. That is why :func:`assert_the_reaper_kills_what_is_not_ours`
confirms its planted process by the process's OWN EXIT rather than by a return value, and why no arm
asserts over a pid table: a pid table on a busy box is a snapshot of a mutating machine.
"""

from __future__ import annotations

import os
import subprocess
import time

from lab_commons.dev import bounded
from lab_commons.dev.famtests._boundedremedy_readings import (
    CHILD_LIFETIME_SECONDS,
    PARENT_HOLDING_A_GRANDCHILD,
    BoxTooLoaded,
    UnprovableSeparation,
    allowance,
    default_interpreter,
    separation_verdict,
    spawn_overhead,
)
from lab_commons.proc import process_tree

__all__ = [
    'CHILD_LIFETIME_SECONDS',
    'PARENT_HOLDING_A_GRANDCHILD',
    'BoxTooLoaded',
    'UnprovableSeparation',
    'allowance',
    'assert_a_run_inside_the_wall_is_left_alone',
    'assert_each_state_names_its_own_remedy',
    'assert_the_reaper_kills_what_is_not_ours',
    'assert_the_reaper_refuses_its_own_lineage',
    'assert_the_wall_terminates_the_tree',
    'default_interpreter',
    'separation_verdict',
    'spawn_overhead',
]


def assert_the_wall_terminates_the_tree(
    *,
    interpreter: str,
    wall_seconds: float,
    reap_ceiling_seconds: float,
    overhead_multiple: float,
    separation_factor: float,
) -> float:
    """THE INCIDENT, AS A TEST: ``timeout`` killed the wrapper and the executable ran forty minutes on.

    Asserted on the CLOCK and never on a pid table -- *did this call come back* is a fact nothing can
    blur. The separation is checked BEFORE the spawn, so a run that could not have failed says so
    instead of passing.

    Args:
        interpreter: the Python to spawn the planted tree with.
        wall_seconds: the bound handed to :func:`lab_commons.dev.bounded.run_bounded`.
        reap_ceiling_seconds: this repo's measured ceiling on the reap after the kill.
        overhead_multiple: slack granted per measured spawn-overhead; see :func:`allowance`.
        separation_factor: how many times the permitted return this repo requires the planted
            child's lifetime to be before a pass is evidence at all.

    Returns:
        The elapsed seconds, so a consumer can report the margin it actually had rather than the
        margin it allowed.

    Raises:
        BoxTooLoaded: the calibration reached the wall, or the slack it priced grew far enough that
            a genuine wait on the tree would have fitted inside it. INCONCLUSIVE, not a failure.
        UnprovableSeparation: the DECLARED numbers alone do not clear the separation.
        AssertionError: the planted tree did not start, or the call waited on the tree it was
            supposed to end.

    """
    overhead = spawn_overhead(interpreter=interpreter, ceiling_seconds=wall_seconds)
    slack = allowance(
        reap_ceiling_seconds=reap_ceiling_seconds, overhead_seconds=overhead, overhead_multiple=overhead_multiple
    )
    refusal = separation_verdict(
        wall_seconds=wall_seconds,
        reap_ceiling_seconds=reap_ceiling_seconds,
        slack_seconds=slack,
        child_lifetime_seconds=CHILD_LIFETIME_SECONDS,
        separation_factor=separation_factor,
    )
    if refusal is not None:
        raise refusal
    started = time.monotonic()
    try:
        bounded.run_bounded([interpreter, '-c', PARENT_HOLDING_A_GRANDCHILD], timeout=wall_seconds, text=True)
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - started
    else:
        msg = (
            f'a child sleeping {CHILD_LIFETIME_SECONDS}s returned inside a {wall_seconds}s wall without '
            f'raising. The planted tree did not start, so nothing whatever was proved.'
        )
        raise AssertionError(msg)
    if elapsed >= wall_seconds + slack:
        msg = (
            f'the bounded call took {elapsed:.1f}s against a {wall_seconds}s wall and {slack:.1f}s of allowance '
            f'(spawn overhead measured at {overhead:.2f}s on this box). It waited on the tree it was supposed '
            f'to end: a hang detector that hangs is worse than none, and raising the wall makes it worse still.'
        )
        raise AssertionError(msg)
    return elapsed


def assert_a_run_inside_the_wall_is_left_alone(*, interpreter: str, wall_seconds: float) -> None:
    """THE OTHER SIDE. A wall that also breaks the passing case is a fault rather than a bound.

    Args:
        interpreter: the Python to spawn.
        wall_seconds: a wall the trivial child comfortably fits inside.

    Raises:
        AssertionError: the child did not succeed, or its output did not come back through the bound.

    """
    done = bounded.run_bounded([interpreter, '-c', 'print("ok")'], timeout=wall_seconds, text=True)
    if done.returncode != 0:
        msg = f'a trivial child exited {done.returncode} inside a {wall_seconds}s wall; the bound broke the pass case'
        raise AssertionError(msg)
    if done.stdout.strip() != 'ok':
        msg = f'the bound swallowed the output of a child that finished in time: {done.stdout!r}'
        raise AssertionError(msg)


def assert_the_reaper_refuses_its_own_lineage() -> None:
    """PLANTED, AND THE PLANT IS THIS PROCESS: ask for our own tree to be killed, and be refused.

    A REFUSAL RATHER THAN A FILTER, and the difference is the subject. Filtering ourselves out still
    leaves an ANCESTOR in the same tree, and killing that takes the shell or the runner with it,
    after which nobody is left to report what happened. This is the self-match a rules page asks a
    human to notice and ignore, asked of the code instead.

    Raises:
        AssertionError: the tree does not contain its own root, or the reaper did not refuse.

    """
    mine = os.getpid()
    if mine not in process_tree(mine):
        msg = f'the tree of {mine} does not contain {mine}; a tree not containing its own root cannot protect it'
        raise AssertionError(msg)
    reaped = bounded.reap_tree(mine)
    if reaped != frozenset():
        msg = f'the reaper was asked to end its own tree and reaped {sorted(reaped)} instead of refusing'
        raise AssertionError(msg)


def assert_the_reaper_kills_what_is_not_ours(*, interpreter: str, exit_ceiling_seconds: float) -> None:
    """THE OTHER SIDE OF THE SPARING: a reaper that spares everything is not a reaper.

    Confirmed by the planted process's OWN EXIT and not by the return value alone, so the claim rests
    on an observation of the machine rather than on the function agreeing with itself -- which is the
    one axis the clock-based arm above cannot see.

    Args:
        interpreter: the Python to spawn the planted process with.
        exit_ceiling_seconds: how long the planted process gets to actually die. BOUNDED, because an
            unbounded wait inside the guard against unbounded waits is the defect wearing the uniform.

    Raises:
        AssertionError: the planted process did not start, was not reaped, or never exited.

    """
    child = subprocess.Popen([interpreter, '-c', f'import time; time.sleep({CHILD_LIFETIME_SECONDS})'])
    try:
        if child.poll() is not None:
            msg = f'the planted process exited immediately ({child.returncode}), so nothing was proved'
            raise AssertionError(msg)
        reaped = bounded.reap_tree(child.pid)
        if child.pid not in reaped:
            msg = f'{child.pid} is outside this lineage and must be reaped; the reaper returned {sorted(reaped)}'
            raise AssertionError(msg)
        if child.wait(timeout=exit_ceiling_seconds) is None:
            msg = f'the reaped process did not exit within {exit_ceiling_seconds}s, so the reap was a return value'
            raise AssertionError(msg)
    finally:
        if child.poll() is None:
            child.kill()


def assert_each_state_names_its_own_remedy(*, capacity: int, wider_tier: str, narrowed_workers: int) -> None:
    """THE RULE ITSELF -- take the remedy a refusal NAMES -- so three states may not share a sentence.

    Args:
        capacity: the width this repo prices its states against. No default: one lab caps it at 12
            and the other floors it at 4, and a guessed capacity measures neither box.
        wider_tier: what THIS repo calls an unbounded run. A remedy naming a tier that does not exist
            here is a dead end wearing a remedy's clothes, so the word is the repo's.
        narrowed_workers: a width this repo considers narrowed. No default -- one lab passes 1 and
            the other passes :data:`lab_commons.dev.bounded.NARROWED_FLOOR`.

    Raises:
        AssertionError: two states shared a sentence, a state built a refusal naming no remedy at
            all, or the narrowed reading failed to separate a narrowed run from a healthy one.

    THE CLAUSE THAT USED TO BE HERE, AND WHY IT IS NOT. Until 2026-09-18 this body asserted
    ``wider_tier in text`` over all three sentences. Every branch of
    :func:`lab_commons.dev.bounded.wall_reason` INTERPOLATES the argument, so the clause held for
    any string whatever -- driven on ``'ZZZ_NO_SUCH_TIER_ANYWHERE'`` it passed in both labs and in
    the kit, which is how a consumer lane found it. It read as *the refusal names a tier this repo
    can escalate to*, and it could not have checked that: the word arrives here from the same caller
    that would have to be wrong about it, so no argument this function could take would make the
    claim falsifiable. What IS falsifiable is that the producer refuses to build a remedy naming
    NOTHING, and that is the clause below -- driven on the REAL body, with the empty tier as the one
    case a shared module can judge without knowing any repo's vocabulary.
    :mod:`lab_commons.dev.famtests.echoedtoken` is the arm that refuses the next clause of this
    shape rather than this one again.

    """
    sentences = {
        'unmeasured': bounded.wall_reason(workers=None, capacity=capacity, wider_tier=wider_tier),
        'narrowed': bounded.wall_reason(workers=narrowed_workers, capacity=capacity, wider_tier=wider_tier),
        'healthy': bounded.wall_reason(workers=capacity, capacity=capacity, wider_tier=wider_tier),
    }
    shared = sorted(name for name, text in sentences.items() if list(sentences.values()).count(text) > 1)
    if shared:
        msg = f'{shared} share one refusal sentence; one sentence for several states is a diagnosis nobody computed'
        raise AssertionError(msg)
    for state, workers in (('unmeasured', None), ('narrowed', narrowed_workers), ('healthy', capacity)):
        try:
            blank = bounded.wall_reason(workers=workers, capacity=capacity, wider_tier='   ')
        except ValueError:
            continue
        msg = (
            f'the {state} state built a refusal from a blank tier instead of refusing it: {blank!r}. '
            f'A remedy that names nothing reaches the reader as a formatting fault rather than as '
            f'the missing declaration it is.'
        )
        raise AssertionError(msg)
    if 'NARROWED' not in sentences['narrowed']:
        msg = f'a run at {narrowed_workers} of {capacity} must be reported as NARROWED: {sentences["narrowed"]!r}'
        raise AssertionError(msg)
    if 'NARROWED' in sentences['healthy']:
        msg = f'a run at full capacity must not be reported as narrowed: {sentences["healthy"]!r}'
        raise AssertionError(msg)
    if not bounded.is_narrowed(narrowed_workers, capacity):
        msg = f'this repo calls {narrowed_workers} of {capacity} narrowed and the reading disagrees'
        raise AssertionError(msg)
    if bounded.is_narrowed(capacity, capacity):
        msg = f'a run at the full {capacity} was read as narrowed, so the reading convicts everything'
        raise AssertionError(msg)
