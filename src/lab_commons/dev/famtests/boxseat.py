"""ONE BOX, ONE SEAT -- the assertion half, shared, over :mod:`lab_commons.dev.boxlock`/``boxwait``.

:mod:`lab_commons.dev.boxlock` publishes the EXCLUSION and :mod:`lab_commons.dev.boxwait` publishes
the bounded, narrated WAIT on it. What stayed forked was the eight-arm test that drives them.
MEASURED 2026-09-19 by two independent audit lanes that did not know of each other: wdg-lab's and
optimi-lab's ``tests/architecture/test_the_verdict_run_takes_the_box.py`` are **84.6% identical**,
and a byte diff says what the 15.4% is --

* a docstring, narrating each repo's own refuted "no runner, so the rule has no subject here";
* ONE value, the private pool name (``<repo>-private-pool``);
* a ``tempfile`` prefix, and four assertion messages that differ only in where the line wraps.

The wrapping is the tell. Two repos whose difference is a line break are not two answers.

WHY THE BODY IS WORTH SHARING RATHER THAN DELETING. The rule's own sentence is that a lock only one
party takes is a TAX on whoever obeys it: the party that takes none runs, the party that takes one is
starved by what it cannot see, and BOTH report clean. Four repos share this box. What was missing in
each was never the lock -- every one of them already took it through
:func:`lab_commons.dev.verify.run_verify` -- but any statement that could NOTICE the lock being
dropped.

WHAT ARRIVES WITH NO DEFAULT:

* *entry_point* -- the repo's own verdict function. NOT :func:`lab_commons.dev.verify.run_verify`
  hard-coded, which is what both forks did: a repo with a runner of its own would then have asserted
  about a function it does not call, and read green while its real entry point took nothing.
* *pool_name* -- the private pool this repo would use if it opted out. It must NOT buy an exemption,
  and it is per-repo because the point of the plant is that it is a name the seat never agreed to.
* *root* -- the checkout the rendezvous must be OUTSIDE of.
* *progress_share_ceiling* -- how long a queue may stay silent, as a FRACTION of the wait it reports
  on. A ratio rather than two absolute readings, because what makes a queue legible is how often it
  speaks RELATIVE to how long it may wait. An argument rather than a constant for the reason
  :mod:`lab_commons.dev.famtests.approxfloors` states: a bar is a policy, and a policy closed over
  in the kit is one repo's answer handed silently to another.

THE ``>=`` IN BOTH FORKS IS FIXED HERE AND THAT IS THE ONE BEHAVIOURAL CHANGE AN ADOPTER MEETS. Both
copies assert ``signature(hold_the_box).parameters.keys() >= {'stack', 'what', 'wait_s', 'poll_s'}``.
A ``>=`` is satisfied by every LONGER signature, so it cannot see a parameter ADDED -- and a new
required parameter on a shared wait is exactly the change that breaks the other three repos' callers
silently. It is the declared-``<=``-live shape that hid six wrong constants in this family in one
week. :data:`HOLD_THE_BOX_PARAMETERS` is compared for EQUALITY, both directions red.
"""

from __future__ import annotations

import inspect
import sys
from typing import TYPE_CHECKING, Any, Final

from lab_commons.dev.boxlock import BOX_POOL, BoxLock
from lab_commons.dev.boxwait import PROGRESS_S, WAIT_S, hold_the_box, holders_line
from lab_commons.resources import BOX_SEATS, Broker, Exhausted

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

__all__ = [
    'HOLD_THE_BOX_PARAMETERS',
    'assert_a_pool_name_of_its_own_does_not_opt_a_run_out',
    'assert_a_second_run_is_refused_while_one_holds_the_box',
    'assert_asking_who_holds_the_box_is_not_taking_it',
    'assert_the_box_pool_is_a_name_rather_than_a_measurement',
    'assert_the_rendezvous_is_outside_this_repository',
    'assert_the_seat_is_released_when_the_run_ends',
    'assert_the_verdict_entry_point_takes_the_box',
    'assert_the_wait_is_bounded_and_narrates',
]

#: The parameters :func:`lab_commons.dev.boxwait.hold_the_box` takes, as a NAMED SET compared for
#: EQUALITY. Not a superset assertion -- see this module's docstring -- and not a count, which could
#: not say which of the four moved and would invite being edited to match whatever it found.
HOLD_THE_BOX_PARAMETERS: Final[frozenset[str]] = frozenset({'stack', 'what', 'wait_s', 'poll_s'})

#: The call every arm looks for in the entry point's own source. The paren is load-bearing: a module
#: that merely IMPORTS the name would otherwise satisfy an assertion about calling it.
_THE_CALL: Final = 'hold_the_box('


def assert_the_verdict_entry_point_takes_the_box(*, entry_point: Callable[..., Any]) -> None:
    """THE PARTICIPATION, read off the code this repo runs to get a verdict rather than off a comment.

    Both halves are asserted because either alone is weak: the IDENTITY says the name the entry
    point's module bound is the family's function and not a same-named local, and the SOURCE says the
    entry point actually CALLS it rather than merely importing it. A repo that stopped holding the
    box would be the party-that-takes-none the rule names -- it would run through whatever else is on
    the box and report clean.

    Args:
        entry_point: the repo's own verdict function, e.g. ``lab_commons.dev.verify.run_verify``.

    Raises:
        AssertionError: the entry point's module bound another ``hold_the_box``, or does not call it.

    """
    module = sys.modules.get(entry_point.__module__)
    if module is None:
        msg = (
            f'{entry_point.__module__} is not imported, so nothing can be read off it. This arm is '
            f'about the code the repo RUNS; an unimportable entry point is a louder finding still.'
        )
        raise AssertionError(msg)
    bound = getattr(module, 'hold_the_box', None)
    if bound is not hold_the_box:
        msg = (
            f'{entry_point.__module__} bound {bound!r} as `hold_the_box`, not '
            f'{hold_the_box!r}. This repo is a party to the box rendezvous only if the function its '
            f'verdict entry point calls is the FAMILY one -- a same-named local excludes nobody.'
        )
        raise AssertionError(msg)
    source = inspect.getsource(entry_point)
    if _THE_CALL not in source:
        msg = (
            f'{entry_point.__module__}.{entry_point.__qualname__} no longer calls {_THE_CALL}. That '
            f'is the party-that-takes-none state the rule names: it would run through whatever else '
            f'is on the box, starve every repo that does take the seat, and report clean.'
        )
        raise AssertionError(msg)


def assert_a_second_run_is_refused_while_one_holds_the_box(*, records: Path) -> None:
    """PLANTED CONTENTION on the REAL ``BoxLock``, and the refusal must NAME who is in the way.

    TWO BROKER INSTANCES OVER ONE RECORDS DIRECTORY, because that is the shape the rule is about: two
    parties sharing nothing but a path. One object handing itself a refusal would prove only that a
    dataclass can count.

    Args:
        records: an ISOLATED records directory. Not squeamishness -- this body runs INSIDE a verdict
            run holding the real seat, so a case taking the real box would be refused by its own
            runner, and one releasing it would hand the box to whoever is queued behind this process.

    Raises:
        AssertionError: both runs held the box, or the refusal did not name the holder.

    """
    planted = 'the-planted-holder'
    with BoxLock(planted, broker=Broker(resource_dir=records)).held():
        try:
            with BoxLock('the-run-that-must-queue', broker=Broker(resource_dir=records)).held():
                pass
        except Exhausted as refusal:
            named = holders_line(refusal)
        else:
            msg = (
                'two CPU-saturating runs held the box at once; the seat excluded nothing. Every '
                'timing either of them reports is a measurement of the other one.'
            )
            raise AssertionError(msg) from None
    if planted not in named:
        msg = (
            f'the refusal said {named!r}. A reader has to choose between waiting, stopping the '
            f'holder and giving up, and only the NAME separates those three -- "busy" sends them to '
            f'the process table to guess, and guessing wrong kills evidence that was not theirs.'
        )
        raise AssertionError(msg)


def assert_the_seat_is_released_when_the_run_ends(*, records: Path) -> None:
    """THE OTHER SIDE OF THE RATCHET. A seat nothing can ever take again is a HANG, not an exclusion.

    A ratchet has two sides: an exclusion that never releases and an exclusion that never excludes
    are the same defect pointing opposite ways, and the arm above passes on the first of them.

    The inner reading is the FLOOR: a held box that reports no holder means the records say nothing,
    so the refusal above could never have named anybody.

    Args:
        records: an ISOLATED records directory.

    Raises:
        AssertionError: the second run could not take the seat, or a held box named no holder.

    """
    broker = Broker(resource_dir=records)
    with BoxLock('the-first-run', broker=broker).held():
        pass
    try:
        with BoxLock('the-run-after-it', broker=broker).held():
            held = BoxLock.holders(broker=broker)
    except Exhausted as refusal:
        msg = (
            f'the seat was never released: {holders_line(refusal)}. A lock that outlives the run '
            f'that took it is a hang wearing an exclusion, and it starves every other repo on this '
            f'box until somebody deletes a file by hand.'
        )
        raise AssertionError(msg) from refusal
    if not held:
        msg = 'a HELD box reported no holder, so the records say nothing and no refusal above could name anybody'
        raise AssertionError(msg)


def assert_a_pool_name_of_its_own_does_not_opt_a_run_out(*, records: Path, pool_name: str) -> None:
    """THE PATH, WHICH IS THE RULE'S ACTUAL CLAIM: agreeing on the mechanism alone measures nothing.

    A repo that adopted ``BoxLock`` and then named its own pool would be excluded from nobody. So a
    job is admitted under a pool name of its OWN and must STILL be refused, because it demands the
    BOX dimension, whose records are one set per box rather than one set per pool -- it meets a
    holder it never agreed on a name with.

    Args:
        records: an ISOLATED records directory.
        pool_name: the private pool this repo would opt out under. Per-repo and with no default,
            because a shared spelling here would be the two parties agreeing again by accident.

    Raises:
        AssertionError: the private pool ran while the box was held, or the refusal named nobody.

    """
    if not pool_name.strip():
        msg = 'the private pool has no name, so this arm plants nothing and cannot fail'
        raise AssertionError(msg)
    shared = 'the-run-under-the-shared-name'
    with BoxLock(shared, broker=Broker(resource_dir=records)).held():
        try:
            with Broker(resource_dir=records).admit(
                pool_name,
                {BOX_SEATS.name: 1},
                what='the-run-with-its-own-pool',
            ):
                pass
        except Exhausted as refusal:
            named = holders_line(refusal)
        else:
            msg = (
                f'{pool_name} ran while the box was held. A private pool name bought an exemption, '
                f'which is the unifying-the-mechanism-without-the-path failure the rule names: both '
                f'parties adopt the lock, neither meets the other, and both report clean.'
            )
            raise AssertionError(msg) from None
    if shared not in named:
        msg = (
            f'the refusal said {named!r} and not {shared!r}. A cross-pool refusal that cannot name '
            f'its holder says only "busy", which sends its reader to the process table to guess.'
        )
        raise AssertionError(msg)


def assert_asking_who_holds_the_box_is_not_taking_it(*, records: Path) -> None:
    """A reader that probes by ACQUIRING becomes a WRITER of the state it reports.

    Already paid for once in this family: two agents reading takeability by acquire-and-release
    refused each other over a phantom holder. Asked TWICE on a fresh directory, because a read with a
    write in it shows up on the second call and not the first.

    The middle reading is the FLOOR and it is pinned as an EQUALITY on a named list: a reader that
    cannot see a real holder is precisely why a second run would start.

    Args:
        records: an ISOLATED records directory.

    Raises:
        AssertionError: a phantom holder appeared, the real one was invisible, or it outlived its block.

    """
    broker = Broker(resource_dir=records)
    first = BoxLock.holders(broker=broker)
    second = BoxLock.holders(broker=broker)
    if first or second:
        msg = (
            f'a fresh records directory named {first or second} as a holder. Asking is not taking: a '
            f'reader that acquires to find out becomes the holder it then reports.'
        )
        raise AssertionError(msg)
    taken = 'the-run-that-really-takes-it'
    with BoxLock(taken, broker=broker).held():
        held = [holder.what for holder in BoxLock.holders(broker=broker)]
    if held != [taken]:
        msg = (
            f'the read reported {held} while exactly one run held the box. Equality and not a '
            f'membership test: a reader that sees the real holder PLUS a phantom is as wrong as one '
            f'that sees neither, and both end with a second run starting.'
        )
        raise AssertionError(msg)
    after = BoxLock.holders(broker=broker)
    if after:
        msg = f'the holder outlived the block that took it: {[holder.what for holder in after]}'
        raise AssertionError(msg)


def assert_the_rendezvous_is_outside_this_repository(*, root: Path) -> None:
    """A lock named INSIDE one tree is one a sibling checkout cannot find, so it excludes NOBODY.

    Args:
        root: this repo's checkout. Per-repo with no default: a guard rooted at the working
            directory answers, plausibly, about somebody else's tree.

    Raises:
        AssertionError: the box records live inside *root*.

    """
    directory = BoxLock.resource_dir()
    if directory.is_relative_to(root):
        msg = (
            f'the box records live at {directory}, inside {root}. A rendezvous a sibling repo cannot '
            f'reach is a lock only this repo takes -- the tax the rule exists to remove.'
        )
        raise AssertionError(msg)


def assert_the_wait_is_bounded_and_narrates(*, progress_share_ceiling: float) -> None:
    """Queue on a CEILING, SAY who you are waiting for, and take the ceiling as an ARGUMENT.

    Args:
        progress_share_ceiling: the longest the queue may stay silent as a fraction of the wait it
            reports on. A progress line arriving once per ceiling is a silent queue with an epilogue.

    Raises:
        AssertionError: the wait is unbounded, the queue is silent for too long a share of it, or the
            shared wait's parameter set is no longer :data:`HOLD_THE_BOX_PARAMETERS`.

    """
    if not 0 < progress_share_ceiling <= 1:
        msg = (
            f'the declared progress share is {progress_share_ceiling}, which is not a fraction of a '
            f'wait. A ceiling of 0 can never be met and one above 1 is no ceiling at all.'
        )
        raise AssertionError(msg)
    if not 0 < WAIT_S < float('inf'):
        msg = f'the wait ceiling is {WAIT_S}; blocking forever renders a crash as a hang and outlives what it waits for'
        raise AssertionError(msg)
    if not 0 < PROGRESS_S <= WAIT_S * progress_share_ceiling:
        msg = (
            f'the queue speaks every {PROGRESS_S}s against a {WAIT_S}s ceiling, past the declared '
            f'share {progress_share_ceiling}. A silent queue and a hung process look identical from '
            f'a terminal, and the remedy for the two is opposite.'
        )
        raise AssertionError(msg)
    live = frozenset(inspect.signature(hold_the_box).parameters)
    if live != HOLD_THE_BOX_PARAMETERS:
        msg = (
            f'`hold_the_box` takes {sorted(live)}, not {sorted(HOLD_THE_BOX_PARAMETERS)}. Added and '
            f'not pinned: {sorted(live - HOLD_THE_BOX_PARAMETERS)}; pinned and gone: '
            f'{sorted(HOLD_THE_BOX_PARAMETERS - live)}. Both directions: a parameter REMOVED means a '
            f'caller can no longer bound its own wait, and a required one ADDED breaks the other '
            f'three repos silently -- which a superset assertion cannot see.'
        )
        raise AssertionError(msg)


def assert_the_box_pool_is_a_name_rather_than_a_measurement() -> None:
    """FLOOR ON THE READING. An empty pool name would make every plant in this module address nothing.

    Raises:
        AssertionError: the pool or the box-wide dimension has no name.

    """
    if not BOX_POOL.strip():
        msg = 'the records pool has no name, so nothing in this module wrote where it claimed to'
        raise AssertionError(msg)
    if not BOX_SEATS.name.strip():
        msg = 'the box-wide dimension has no name, so the seat cannot be demanded and no plant contends'
        raise AssertionError(msg)
