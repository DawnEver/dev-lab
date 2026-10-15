"""THE VERIFY DOOR'S BOX CLAIM: a selection's pytest step runs IN THE BOX, at a declared, enforced claim.

Every run on a machine declares its demand on the one box ledger and is held to it (:mod:`lab_commons.box`,
user ruling 2026-10-14) and declares only the cores it uses (user ruling 2026-10-15). A selection declares
:func:`selection_demand` of :func:`selection_workers` -- the ONE number its pytest ``-n`` is built from, one
core when it runs serial -- :data:`SELECTION_MEM_GB` for its whole tree and :data:`SELECTION_WALL_S`, and
:func:`boxed` spells its pytest argv through :func:`lab_commons.box.command`, so the box admits it
within the caller's queue ceiling and kills it past its claim. A tree the box already holds (its
``INSIDE_ENV``, e.g. a producer serve spawned) is NOT boxed again: it is already held to its claim.

:func:`ended_in_the_box` reads the box's RECORD back (``--outcome``, never the exit code, which is pytest's own):
a refusal means nothing ran (raised, so the door reports INCONCLUSIVE naming the holder), a kill means the
run was cut short and no record means the box itself crashed (each a truncation).
"""

from __future__ import annotations

import importlib.util
import math
import os
from collections.abc import Sequence
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
    'selection_workers',
    'xdist_installed',
]

#: The ceiling on a SELECTION's wait for the box and its environment, in seconds: a developer's measure must
#: never block development, so a held box is a fast refusal naming the holder, not a queue.
MEASURE_WAIT_S: Final = 60.0

#: The ceiling on the PRODUCER's wait for its environment seat, in seconds (its box claim is serve's).
WAIT_S: Final = 1800.0

#: The pytest-xdist workers a selection runs at most when its caller names no width.
SELECTION_CPU: Final = 4

#: The memory a selection's whole process tree declares, in GB: killed past it.
SELECTION_MEM_GB: Final = 8.0

#: The wall a selection declares, in seconds: killed past it.
SELECTION_WALL_S: Final = 3600


#: The spellings of an explicit pytest-xdist width, and the ones that mean "as many as the box".
_WIDTH_FLAGS: Final = ('-n', '--numprocesses')
_AUTO: Final = frozenset({'auto', 'logical'})


def xdist_installed() -> bool:
    """Whether this interpreter -- the one the step's pytest runs in -- can run workers at all."""
    return importlib.util.find_spec('xdist') is not None


def _explicit_width(argv: Sequence[str]) -> str | None:
    """The width *argv* names itself (last one wins, as in pytest), ``'0'`` for ``-p no:xdist``, else ``None``."""
    width = None
    for index, arg in enumerate(argv):
        following = argv[index + 1] if index + 1 < len(argv) else None
        if arg in _WIDTH_FLAGS:
            width = following
        elif arg.startswith('--numprocesses='):
            width = arg.partition('=')[2]
        elif arg.startswith('-n'):  # '-n' itself is a _WIDTH_FLAGS token above
            width = arg[2:]
        elif (arg == '-p' and following == 'no:xdist') or arg == '-pno:xdist':
            return '0'
    return width


def selection_workers(argv: Sequence[str], capacity: Capacity, *, xdist: bool) -> tuple[int, list[str]]:
    """The workers *argv*'s pytest runs, and the ``-n`` to append so it runs exactly that many.

    The caller's own width is honoured as given (``auto`` is the cap); without one, xdist runs
    :data:`SELECTION_CPU` capped at the box, and without xdist the step is one interpreter: ``0``.
    """
    cap = max(1, min(SELECTION_CPU, math.floor(capacity.cpu)))
    if not xdist:
        return 0, []
    given = _explicit_width(argv)
    if given is None:
        return cap, ['-n', str(cap)]
    return (cap if given in _AUTO else int(given)), []


def selection_demand(workers: int) -> Demand:
    """A selection's box claim: one core per worker (one when serial), memory and wall as declared."""
    return Demand(cpu=max(1, workers), mem_gb=SELECTION_MEM_GB, wall_s=SELECTION_WALL_S, seats={})


def boxed(root: Path, argv: list[str], *, queue_s: float, outcome: Path) -> tuple[list[str], Path | None]:
    """*argv* run in the box at :func:`selection_demand` of the workers it runs, and its record.

    The ``-n`` it appends and the cores it declares are ONE number (:func:`selection_workers`). The record
    is *outcome* when the box runs it, ``None`` for a tree the box already holds (not reboxed).
    """
    if INSIDE_ENV in os.environ:
        return argv, None
    workers, width = selection_workers(argv, Capacity.read(), xdist=xdist_installed())
    demand = selection_demand(workers)
    run = [*argv, *width]
    return command(run, demand, queue_s, key=f'verify:{root}', what=f'verify:{root.name}', outcome=outcome), outcome


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
