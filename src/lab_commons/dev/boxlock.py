"""One CPU-saturating run at a time on this box, built ON ``lab_commons.resources``.

THERE IS NO SECOND LOCK HERE, and that is the design rather than a shortcut. ``lab_commons``
already ships cross-process admission, a refusal that names its holders, and a running ceiling
(``resources.Broker/Grant/Exhausted``), written for exactly this box and already consumed by a
consumer that outlives its driver. A second lock -- a byte-range lock, a pid file, a heartbeat --
would be a second definition of the same thing, and the two would drift on the first fix applied to
one of them. So this module is a POLICY: it names the dimension, declares the one seat, and drives
the broker that exists.

WHAT MAKES IT BOX-WIDE IS THE DIMENSION, NOT THE POOL NAME. The broker rations per pool, and a pool
is just a string, so "box-wide" used to be a property of every caller passing the SAME string: a
consumer that passed its own name silently opted out of contending, and nothing in the broker could
tell it so. That is now a property of the MECHANISM -- :data:`lab_commons.resources.BOX_SEATS` is a
``Scope.BOX`` dimension, whose record files are one set per box rather than one set per pool, so two
repos that never agree on a pool name still meet on the same seat. :data:`BOX_POOL` remains what
this lock's records are NAMED by (records need a pool), and it is no longer what excludes anybody.

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
    BOX_SEATS,
    DEFAULT_POLL_S,
    SEATS,
    Broker,
    Capacity,
    CapacityRegistry,
    Grant,
    Holder,
)

__all__ = ['BOX_POOL', 'BoxLock']

#: The name this lock's records carry. NOT the exclusion -- see the module docstring: what excludes
#: is the box-scoped seat below. Kept as a named constant because a record still has to say which
#: pool wrote it, and a caller that wants to read this lock's records has to know where they are.
BOX_POOL: Final = 'lab-commons-box'

#: The rule, as data the broker MUST read. A STRUCTURAL capacity is a property of the tool rather
#: than of the machine, which is exactly what "this pool runs one at a time" is -- and because
#: :meth:`CapacityRegistry.capacity` composes several declarations by taking the SMALLEST, no
#: per-box seat measurement can lift it.
_ONE_SEAT: Final = Capacity.structural(
    SEATS.name,
    1,
    note=(
        'the exclusion within this pool: one CPU-saturating run at a time, for every repo that '
        'names BOX_POOL. Serialising an unmeasured box is the direction that cannot crash it, and '
        'a measurement of four seats cannot lift a structural constant.'
    ),
)

#: THE BOX-WIDE HALF OF THE SAME RULE, and the half that does not depend on anyone's spelling.
#: ``BOX_SEATS`` is ``Scope.BOX``, so this declaration binds every pool on the box: a run that
#: demanded it under a pool name of its own meets this lock on the same record file. Structural for
#: the same reason as :data:`_ONE_SEAT` -- nothing about a measurement of THIS machine can make a
#: box run two CPU-saturating jobs at once sanely.
_ONE_BOX_SEAT: Final = Capacity.structural(
    BOX_SEATS.name,
    1,
    note=(
        'the box-wide exclusion: one CPU-saturating run at a time on this box, for every pool that '
        'demands this dimension. It is the seat a consumer cannot opt out of by naming its own pool.'
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
        """Refuse a request that does not say WHAT is being locked, at construction."""
        if not self.what.strip():
            msg = (
                'a lock holder with no name produces a refusal that cannot be acted on. The reader '
                'has to choose between waiting, stopping a holder and re-measuring the box, and '
                'only the name separates those three.'
            )
            raise ValueError(msg)

    @staticmethod
    def _broker(broker: Broker | None) -> Broker:
        """The broker to drive, WITH both seats declared on it.

        An injected broker is given the two declarations as well, rather than replacing them. The
        alternative -- honouring the caller's registry wholesale -- is a hole with a friendly name:
        a consumer with a measured four-seat registry would inject it and silently lose the
        box-wide exclusion, which is the one thing this class exists to state. Declaring them here
        is idempotent in EFFECT, because several declarations for one dimension compose by taking
        the smallest, so a second call cannot tighten or loosen anything.
        """
        if broker is None:
            return Broker(CapacityRegistry([(BOX_POOL, _ONE_SEAT), (BOX_POOL, _ONE_BOX_SEAT)]))
        broker.registry.declare(BOX_POOL, _ONE_SEAT)
        broker.registry.declare(BOX_POOL, _ONE_BOX_SEAT)
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
        # NEITHER SEAT IS A CALLER OPTION, so they are applied AFTER the caller's demands and a
        # `seats=` key in `demands` cannot widen them. What a caller may add is what else its run
        # costs; what it may not add is a second seat, which would be this class contradicting its
        # own name.
        demands = {**self.demands, SEATS.name: 1, BOX_SEATS.name: 1}
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
        reads records, and this method adds no write of its own. It reports the box-scoped seat
        whatever pool its holder named, so a second repo's run is named here rather than invisible.
        """
        return tuple(BoxLock._broker(broker).holders(BOX_POOL))

    @staticmethod
    def resource_dir(*, broker: Broker | None = None) -> Path:
        """Where the exclusion lives on disk -- outside every repository, by the broker's design."""
        return BoxLock._broker(broker).resource_dir()
