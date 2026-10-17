"""THE VERIFY DOOR'S BOX CLAIM: a selection's pytest step runs IN THE BOX, at a declared, enforced claim.

Every run on a machine declares its demand on the one box ledger and is held to it (:mod:`lab_commons.box`,
user ruling 2026-10-14) and declares only the cores it uses (user ruling 2026-10-15). A selection declares
:func:`selection_demand` of :func:`selection_workers` -- the ONE number its pytest ``-n`` is built from, one
core when it runs serial -- the MEMORY ITS FILES MEASURED (:func:`selection_mem_gb`, D4/D5: each worker at the
worst selected file's peak from the forge-derived learned table, an unmeasured file at its siblings' median)
and :data:`SELECTION_WALL_S`, and
:func:`boxed` spells its pytest argv through :func:`lab_commons.box.command`, so the box admits it
within the caller's queue ceiling and kills it past its claim. A tree the box already holds (its
``INSIDE_ENV``, e.g. a producer serve spawned) is NOT boxed again: it is already held to its claim.

:func:`ended_in_the_box` reads the box's RECORD back (``--outcome``, never the exit code, which is pytest's own):
a refusal means nothing ran (raised, so the door reports INCONCLUSIVE naming the holder), a kill means the
run was cut short and no record means the box itself crashed (each a truncation).
"""

from __future__ import annotations

import hashlib
import importlib.util
import math
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from lab_commons.box import GB, INSIDE_ENV, Capacity, Demand, Outcome, Refused, command, read_ended
from lab_commons.compute import learned
from lab_commons.dev.forgedemand import refresh_checkout
from lab_commons.dev.platformparts import origin_url
from lab_commons.hpc.config import Cost

__all__ = [
    'MEASURE_WAIT_S',
    'SELECTION_CPU',
    'SELECTION_WALL_S',
    'WAIT_S',
    'boxed',
    'ended_in_the_box',
    'learn_ended',
    'selection_demand',
    'selection_files',
    'selection_mem_gb',
    'selection_producer',
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


def selection_files(root: Path, argv: Sequence[str]) -> tuple[str, ...]:
    """The test FILES *argv* selects, as root-relative posix paths.

    A file or node id names itself, a directory every ``test_*.py`` under it; naming nothing is the
    whole ``tests`` tree.
    """
    named = [root / arg.split('::', 1)[0] for arg in argv if not arg.startswith('-')]
    paths = [path for path in named if path.is_dir() or (path.is_file() and path.suffix == '.py')]
    if not paths and (root / 'tests').is_dir():
        paths = [root / 'tests']
    found = {one for path in paths for one in ((path,) if path.is_file() else path.rglob('test_*.py'))}
    return tuple(sorted(one.relative_to(root).as_posix() for one in found))


def selection_mem_gb(repo: str, files: Sequence[str], workers: int) -> float:
    """The memory a selection's tree declares: each worker at the worst file's peak times the box headroom.

    The peaks are the forge's (:mod:`lab_commons.dev.forgedemand`); an unmeasured file is priced at its
    siblings' median (:meth:`~lab_commons.compute.learned.Measured.prior_mb`), and a repository nothing was
    ever measured for at :class:`~lab_commons.hpc.config.Cost`'s per-task floor. A per-file peak is what one
    SMALL item reached, and one process running many files holds more: a selection that ran before is also
    priced at its own whole-tree peak (:func:`learn_ended`) times the headroom -- one the box killed for
    memory at twice the limit it died at -- whichever is larger.
    """
    per = learned.worker_gb(repo, files, prior_gb=Cost().mem_gb, safety=learned.BOX_HEADROOM)
    ran = learned.run_of(repo, selection_producer(files), ())
    whole = 0.0 if ran is None else ran.peak_mem_gb * learned.BOX_HEADROOM
    return round(max(max(1, workers) * per, whole), 3)


def selection_producer(files: Sequence[str]) -> str:
    """The learned-table producer name of the selection *files*: one per distinct set of files."""
    return 'verify:' + hashlib.sha256('|'.join(sorted(files)).encode()).hexdigest()[:16]


def learn_ended(root: Path, argv: Sequence[str], record: Path | None) -> None:
    """Keep what the box measured of this selection's whole tree; a memory kill is a floor that grows."""
    ended = None if record is None else read_ended(record)
    if not isinstance(ended, Outcome) or ended.peak_mem_bytes <= 0:
        return
    run = learned.Run(ended.peak_mem_bytes / GB, ended.cpu_s, max(ended.wall_s, 1e-3))
    producer = selection_producer(selection_files(root, argv))
    learned.record_run(_repo(root), producer, (), run, killed=ended.reason == 'memory')


def selection_demand(workers: int, mem_gb: float) -> Demand:
    """A selection's box claim: one core per worker (one when serial), its measured memory, its wall."""
    return Demand(cpu=max(1, workers), mem_gb=mem_gb, wall_s=SELECTION_WALL_S, seats={})


def boxed(root: Path, argv: list[str], *, queue_s: float, outcome: Path) -> tuple[list[str], Path | None]:
    """*argv* run in the box at :func:`selection_demand` of the workers it runs, and its record.

    The ``-n`` it appends and the cores it declares are ONE number (:func:`selection_workers`). The record
    is *outcome* when the box runs it, ``None`` for a tree the box already holds (not reboxed).
    """
    if INSIDE_ENV in os.environ:
        return argv, None
    size = Capacity.read()
    workers, width = selection_workers(argv, size, xdist=xdist_installed())
    refresh_checkout(root)
    demand = selection_demand(workers, selection_mem_gb(_repo(root), selection_files(root, argv), workers))
    run = [*argv, *width]
    return command(
        run, demand, queue_s, key=f'verify:{root}', what=f'verify:{root.name}', outcome=outcome, capacity=size
    ), outcome


def _repo(root: Path) -> str:
    try:
        return origin_url(root)
    except OSError:  # no origin is no learned table, never a crashed verify
        return ''


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
        return (f'the box killed pytest past its declared memory or {SELECTION_WALL_S} s ({ended.reason})',)
    return ()
