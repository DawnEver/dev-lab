"""One CPU-saturating run at a time on this box, built ON ``lab_commons.resources``.

THERE IS NO SECOND LOCK HERE, and that is the design rather than a shortcut. ``lab_commons``
already ships cross-process admission, a refusal that names its holders, and a running ceiling
(``resources.Broker/Grant/Exhausted``), written for exactly this box and already consumed by a
consumer that outlives its driver. A second lock -- a byte-range lock, a pid file, a heartbeat --
would be a second definition of the same thing, and the two would drift on the first fix applied to
one of them. So this module is a POLICY: it names the pool, declares the one seat, and drives the
broker that exists.

WHAT A POOL NAME IS, AND WHY IT IS A CONSTANT HERE. The broker rations PER POOL, and a pool is just
a string -- so "box-wide" is not a property the broker can enforce, it is a property of every
caller passing the SAME string. That is a real limit and it is stated rather than papered over:
:data:`BOX_POOL` is the one name the family agrees on, and a consumer that passes its own name has
silently opted out of contending with the others. See the module docstring of
:mod:`lab_commons.resources` for what a per-box mechanism can and cannot decide.

WHY ``seats=1`` AND NOT A CPU DEMAND. A CPU-saturating run wants the box's whole width, and an
unmeasured box's cpu ceiling is one, so DEMANDING cores would refuse the very runs this lock exists
to serialise. The seat is the exclusion; ``demands`` is how a caller declares what else it expects
to consume (memory, most usefully), and it is passed through to the broker rather than interpreted
here.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from lab_commons.resources import (
    DEFAULT_POLL_S,
    SEATS,
    Broker,
    Capacity,
    CapacityRegistry,
    Grant,
    Holder,
)

__all__ = ['BOX_POOL', 'BoxLock']

#: The one pool every repo in this family contends through. A CONSTANT rather than a default
#: argument, because a default is a value a caller can quietly replace and this string IS the
#: mechanism -- two spellings of it are two locks that never meet.
BOX_POOL: Final = 'lab-commons-box'

#: The rule, as data the broker MUST read. A STRUCTURAL capacity is a property of the tool rather
#: than of the machine, which is exactly what "this pool runs one at a time" is -- and because
#: :meth:`CapacityRegistry.capacity` composes several declarations by taking the SMALLEST, no
#: per-box seat measurement can lift it.
_ONE_SEAT: Final = Capacity.structural(
    SEATS.name,
    1,
    note=(
        'the box-wide exclusion: one CPU-saturating run at a time, on every box, for every repo '
        'that names BOX_POOL. Serialising an unmeasured box is the direction that cannot crash it, '
        'and a measurement of four seats cannot lift a structural constant.'
    ),
)


@dataclass
class BoxLock:
    """The exclusion, as an object a caller describes itself to and then holds.

    ``what`` is not decoration: it is what the refusal PRINTS, and a refusal that says "busy" sends
    its reader to the process table to guess -- and guessing wrong kills somebody's evidence. Name
    the run (`'gate:integrate/main'`), not the program.
    """

    what: str
    demands: Mapping[str, int] = field(default_factory=dict)
    wait_s: float = 0.0
    poll_s: float = DEFAULT_POLL_S
    broker: Broker | None = None

    def __post_init__(self) -> None:
        if not self.what.strip():
            msg = (
                'a lock holder with no name produces a refusal that cannot be acted on. The reader '
                'has to choose between waiting, stopping a holder and re-measuring the box, and '
                'only the name separates those three.'
            )
            raise ValueError(msg)

    @staticmethod
    def _broker(broker: Broker | None) -> Broker:
        """The broker to drive, WITH the box-wide seat declared on it.

        An injected broker is given :data:`_ONE_SEAT` as well, rather than replacing it. The
        alternative -- honouring the caller's registry wholesale -- is a hole with a friendly name:
        a consumer with a measured four-seat registry would inject it and silently lose the
        box-wide exclusion, which is the one thing this class exists to state. Declaring it here is
        idempotent in EFFECT, because several declarations for one pool compose by taking the
        smallest, so a second call cannot tighten or loosen anything.
        """
        if broker is None:
            return Broker(CapacityRegistry([(BOX_POOL, _ONE_SEAT)]))
        broker.registry.declare(BOX_POOL, _ONE_SEAT)
        return broker

    @contextmanager
    def held(self) -> Iterator[Grant]:
        """Hold the box until the ``with`` block ends, or refuse naming the holder.

        NOT WRAPPED IN A NEW EXCEPTION. The refusal is :class:`lab_commons.resources.Exhausted`,
        which already carries the pool, the dimension, the basis and the live holders -- a second
        class here would be a second spelling of the same fact, and a caller catching this layer's
        exhaustion would stop catching the broker's.

        Raises:
            Exhausted: another live holder has the seat. With ``wait_s=0`` (the default) this is
                decided at the first check rather than after a queue.

        """
        # THE SEAT IS NOT A CALLER OPTION, so it is applied AFTER the caller's demands and a
        # `seats=` key in `demands` cannot widen it. What a caller may add is what else its run
        # costs; what it may not add is a second seat, which would be this class contradicting its
        # own name.
        demands = {**self.demands, SEATS.name: 1}
        with self._broker(self.broker).admit(
            BOX_POOL,
            demands,
            what=self.what,
            wait_s=self.wait_s,
            poll_s=self.poll_s,
        ) as grant:
            yield grant

    @staticmethod
    def holders(*, broker: Broker | None = None) -> tuple[Holder, ...]:
        """Who holds the box now, WITHOUT taking it.

        ASKING IS NOT TAKING, which this family has already paid for once: a reader that probed
        takeability by acquiring and releasing the lock became a WRITER of the state it reported,
        and two agents reading it refused each other over a phantom holder. ``Broker.holders`` only
        reads records, and this method adds no write of its own.
        """
        return tuple(BoxLock._broker(broker).holders(BOX_POOL))

    @staticmethod
    def resource_dir(*, broker: Broker | None = None) -> Path:
        """Where the exclusion lives on disk -- outside every repository, by the broker's design."""
        return BoxLock._broker(broker).resource_dir()
