"""THE VERIFY DOOR'S BOX CLAIM: a selection's pytest step runs IN THE BOX, at a declared, enforced claim.

Every run on a machine declares its demand on the one box ledger and is held to it (:mod:`lab_commons.box`,
user ruling 2026-10-14). A selection declares :func:`selection_demand` -- at most :data:`SELECTION_CPU`
cores (as many pytest workers), :data:`SELECTION_MEM_GB` for its whole tree and :data:`SELECTION_WALL_S` --
and :func:`boxed` spells its pytest argv through :func:`lab_commons.box.command`, so the box admits it
within the caller's queue ceiling and kills it past its claim. A producer ``forge serve`` spawned is NOT
boxed again: serve already runs it in the box at the demand it admitted it at.

:func:`ended_in_the_box` reads the CLI's two exit codes back: a refusal means nothing ran (raised, so the
door reports INCONCLUSIVE naming the holder), a kill means the run was cut short (a truncation).
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Final

from lab_commons.box import KILLED, REFUSED, Capacity, Demand, Refused, command
from lab_commons.dev.producer import PRODUCING_VAR

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

#: What the box CLI prints before it exits :data:`~lab_commons.box.REFUSED` (``lab_commons.box.__main__``).
_REFUSED_PREFIX: Final = 'box: refused -- '


def selection_demand(capacity: Capacity) -> Demand:
    """A selection's box claim: :data:`SELECTION_CPU` cores capped at the box, memory and wall as declared."""
    cpu = max(1, min(SELECTION_CPU, math.floor(capacity.cpu)))
    return Demand(cpu=cpu, mem_gb=SELECTION_MEM_GB, wall_s=SELECTION_WALL_S, seats={})


def boxed(root: Path, argv: list[str], *, queue_s: float) -> tuple[list[str], dict[str, str]]:
    """*argv* run in the box at :func:`selection_demand`, and the env capping pytest-xdist at its cores."""
    if PRODUCING_VAR in os.environ:
        return argv, {}
    demand = selection_demand(Capacity.read())
    spelled = command(argv, demand, queue_s, key=f'verify:{root}', what=f'verify:{root.name}')
    return spelled, {'PYTEST_XDIST_AUTO_NUM_WORKERS': str(demand.cpu)}


def ended_in_the_box(code: int, log: Path) -> tuple[str, ...]:
    """Why the box ended the step whose output is *log*, as a truncation; raises :class:`Refused` when it never ran.

    A refused step printed one line and nothing else, so reading its log back is reading a few bytes.
    """
    if code == REFUSED:
        with log.open(encoding='utf-8', errors='replace') as handle:
            said = [line.strip().removeprefix(_REFUSED_PREFIX) for line in handle if line.startswith(_REFUSED_PREFIX)]
        raise Refused(said[-1] if said else 'the box refused the run')
    if code == KILLED:
        return (f'the box killed pytest past its declared {SELECTION_MEM_GB:g} GB or {SELECTION_WALL_S} s',)
    return ()
