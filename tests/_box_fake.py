"""What a fake box run leaves behind: the ``--outcome`` record a spawned ``python -m lab_commons.box run`` writes.

Shared by the producer tests (``test_dev_forgeserve.py``, ``test_dev_forgecarry.py``,
``test_dev_forgerequest.py``) and the supervise runner fakes, each standing in for the box CLI: the caller
reads the box's decision from this record, never from the exit code.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

from lab_commons.box import Capacity, Outcome, Refused, write_ended
from lab_commons.box.supply import Reading
from lab_commons.supervise.process.base import Ran


def ended(code: int, reason: str = 'exit') -> Outcome:
    """The Outcome of a boxed child that exited *code*, ended by *reason* (``exit``, ``memory`` or ``wall``)."""
    return Outcome(code, reason, 0, 0.0, 0.0, 'fake', 'k', None)


def record(argv: Sequence[str], what: Outcome | Refused | None) -> None:
    """Write *what* where the box argv *argv* names its ``--outcome``; ``None`` writes nothing (a crashed box)."""
    if what is not None:
        path = Path(argv[list(argv).index('--outcome') + 1])
        path.parent.mkdir(parents=True, exist_ok=True)  # beside a tree the fake never built
        write_ended(path, what)


def boxed_as_run(argv: Sequence[str], ran: Ran) -> Ran:
    """*ran*, after recording the child's own exit when *argv* is a box run (``--outcome`` in it); else as is."""
    if '--outcome' in argv:
        record(argv, ended(ran.code))
    return ran


def quiet(capacity: Capacity) -> Callable[[Iterable[int]], Reading]:
    """An OS reader of a box nobody but its claims uses: idle and available are its whole size and margins.

    On it the measured room equals the declared one (*capacity* less the claims), so a test that hands the
    ledger a size by hand is not decided by how loaded the machine running it happens to be.
    """
    reading = Reading(
        cores=capacity.cpu + capacity.kept_cpu,
        idle_cores=capacity.cpu + capacity.kept_cpu,
        total_bytes=capacity.mem_bytes + capacity.kept_bytes,
        available_bytes=capacity.mem_bytes + capacity.kept_bytes,
    )
    return lambda _pids: reading
