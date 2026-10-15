"""THE VERIFY DOOR'S BOX CLAIM: a selection's pytest step runs IN THE BOX, at a declared, enforced claim.

Every run on a machine declares its demand on the one box ledger and is held to it (:mod:`lab_commons.box`,
user ruling 2026-10-14). A selection declares :func:`selection_demand` -- at most :data:`SELECTION_CPU`
cores (as many pytest workers), :data:`SELECTION_MEM_GB` for its whole tree and :data:`SELECTION_WALL_S` --
and :func:`boxed` spells its pytest argv through :func:`lab_commons.box.command`, so the box admits it
within the caller's queue ceiling and kills it past its claim. A tree the box already holds (its
``INSIDE_ENV``, e.g. a producer serve spawned) is NOT boxed again: it is already held to its claim.

:func:`ended_in_the_box` reads the box's RECORD back (``--outcome``, never the exit code, which is pytest's own):
a refusal means nothing ran (raised, so the door reports INCONCLUSIVE naming the holder), a kill means the
run was cut short and no record means the box itself crashed (each a truncation).
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Final

from lab_commons.box import Capacity, Demand, Refused, command, read_ended
from lab_commons.box.run import INSIDE_ENV

__all__ = [
    'MEASURE_WAIT_S',
    'SELECTION_CPU',
    'SELECTION_MEM_GB',
    'SELECTION_WALL_S',
    'WAIT_S',
    'boxed',
    'ended_in_the_box',
    'selection_demand',
]

#: The ceiling on a SELECTION's wait for the box and its environment, in seconds: a developer's measure must
#: never block development, so a held box is a fast refusal naming the holder, not a queue.
MEASURE_WAIT_S: Final = 60.0

#: The ceiling on the PRODUCER's wait for its environment seat, in seconds (its box claim is serve's).
WAIT_S: Final = 1800.0

#: The cores a selection declares at most, and the pytest-xdist workers it runs.
SELECTION_CPU: Final = 4

#: The memory a selection's whole process tree declares, in GB: killed past it.
SELECTION_MEM_GB: Final = 8.0

#: The wall a selection declares, in seconds: killed past it.
SELECTION_WALL_S: Final = 3600


def selection_demand(capacity: Capacity) -> Demand:
    """A selection's box claim: :data:`SELECTION_CPU` cores capped at the box, memory and wall as declared."""
    cpu = max(1, min(SELECTION_CPU, math.floor(capacity.cpu)))
    return Demand(cpu=cpu, mem_gb=SELECTION_MEM_GB, wall_s=SELECTION_WALL_S, seats={})


def boxed(
    root: Path, argv: list[str], *, queue_s: float, outcome: Path
) -> tuple[list[str], dict[str, str], Path | None]:
    """*argv* run in the box at :func:`selection_demand`, the env capping pytest-xdist at its cores, and its record.

    The record is *outcome* when the box runs it, ``None`` for a tree the box already holds (not reboxed).
    """
    if INSIDE_ENV in os.environ:
        return argv, {}, None
    demand = selection_demand(Capacity.read())
    spelled = command(argv, demand, queue_s, key=f'verify:{root}', what=f'verify:{root.name}', outcome=outcome)
    return spelled, {'PYTEST_XDIST_AUTO_NUM_WORKERS': str(demand.cpu)}, outcome


def ended_in_the_box(record: Path | None) -> tuple[str, ...]:
    """Why the box ended the step it recorded at *record*, as a truncation; raises :class:`Refused` when it never ran.

    ``None`` is a step the box did not run (already inside a claim): pytest's own code judges it.
    """
    if record is None:
        return ()
    ended = read_ended(record)
    if isinstance(ended, Refused):
        raise ended
    if ended is None:
        return (f'the box crashed: it left no record at {record} of how pytest ended',)
    if ended.killed:
        return (
            f'the box killed pytest past its declared {SELECTION_MEM_GB:g} GB or {SELECTION_WALL_S} s ({ended.reason})',
        )
    return ()
