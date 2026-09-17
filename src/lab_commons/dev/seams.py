"""REBINDING a name for measurement, and the UNDO that makes the rebinding safe to do in-process.

Migrated 2026-09-17 from motronics-studio's ``scripts/gate/seam_install.py``. A profiling harness
instruments production by rebinding a name in the module that CALLS it, because ``from x import y``
binds ``y`` into the importer's namespace at IMPORT time -- so wrapping the DEFINITION site instead
lands on a name nobody reads and the seam measures ``0.000 s``. That direction is well known and
every harness that does this documents it.

WHAT NOBODY HAD WAS THE OTHER DIRECTION, and it is the whole reason this is a module rather than a
``setattr``. A rebinding installed in a long-lived process is PERMANENT, and a test process is
long-lived. MEASURED 2026-09-05: three tests installed wrappers for their own floor and each left one
in place for the rest of the session; their siblings then read the wrapper as the pristine object
and asserted ``x is before`` -- so the failure surfaced IN THE SIBLING, never in the leaker. Spread
over parallel workers, each file passed alone and one failed whenever a pair shared a worker, and
four agents in a row carried it as "pre-existing, not mine".

THE ORIGINAL IS CAPTURED AT THE FIRST REBINDING OF A NAME AND NEVER OVERWRITTEN, so installing twice
-- a profile run inside a captured run -- restores the pristine object rather than the first wrapper.

:func:`restore_all` RETURNS ITS COUNT rather than swallowing it. "Restored nothing" and "restored
everything" have the same shape otherwise, and a caller that checks the number against one it knows
independently is the only thing that tells them apart.

WHAT THE MIGRATION DISSOLVED. The version this came from ended with two
``sys.modules.setdefault`` lines forcing one module object under two spellings, because a harness
reached it as a top-level script module and a test reached it as a package attribute -- two
registers, two empty undo lists, and a ``restore_all`` returning a perfectly plausible ``0`` while
restoring nothing. A module inside an installed package has ONE import spelling, so the hazard and
its workaround both go; that is a defect REMOVED BY THE MOVE rather than a fact carried through it,
and it is worth naming because it is the only one of its kind found in this tranche.

A MISSING SEAM IS AN ANSWER. :func:`install` returns the labels that did not resolve, because a
profile silently missing its dominant term reads as "that term is free" -- the declaration-that-lies
defect in measurement form. An unresolved label is this scan's floor.
"""

from __future__ import annotations

import importlib
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

__all__ = ['Seam', 'Timing', 'install', 'rebind', 'restore_all', 'timings']

#: ``(owner, attr, original)``, appended in install order and unwound in reverse. The owner is held
#: by this list, which is also what keeps identity comparison honest for the caller checking its undo.
_ORIGINALS: list[tuple[object, str, object]] = []

_TOTALS: dict[str, float] = defaultdict(float)
_CALLS: dict[str, int] = defaultdict(int)


@dataclass(frozen=True, slots=True)
class Seam:
    """One thing to measure: a LABEL, the module to import, and the dotted path inside it.

    The path is dotted so a method on a module-level object is reachable (``Solver.solve``) without
    this module learning what any of those names mean.
    """

    #: What the measurement is called in the report. Also the key :func:`timings` answers under.
    label: str
    #: The module to import. The one it is rebound IN -- which for an imported name is the CALLER.
    module: str
    #: The dotted attribute path inside that module.
    path: str


@dataclass(frozen=True, slots=True)
class Timing:
    """What one seam cost: the total wall time under it, and how many calls that was over."""

    #: Seconds accumulated inside the wrapped callable, excluding nothing.
    total_s: float
    #: How many times it was entered. ZERO with a nonzero total is impossible and says so.
    calls: int


def rebind(owner: object, attr: str, replacement: object) -> None:
    """Set ``owner.attr`` to *replacement*, RECORDING what was there so it can be put back.

    Raises:
        AttributeError: *owner* has no *attr*. Refused rather than created, because a rebinding of a
            name that did not exist has nothing to restore and measures a seam nobody calls.

    """
    current = getattr(owner, attr)
    if not any(held is owner and name == attr for held, name, _ in _ORIGINALS):
        _ORIGINALS.append((owner, attr, current))
    setattr(owner, attr, replacement)


def restore_all() -> int:
    """Put every recorded name back, NEWEST FIRST, and return HOW MANY were restored.

    Newest first is what makes a double install unwind correctly even though the recorded original
    is already the pristine one: the invariant holds by both routes rather than by one.
    """
    restored = len(_ORIGINALS)
    while _ORIGINALS:
        owner, attr, original = _ORIGINALS.pop()
        setattr(owner, attr, original)
    return restored


def timings() -> dict[str, Timing]:
    """What each installed seam has cost so far, by label. A snapshot; the counters keep running."""
    return {label: Timing(total, _CALLS[label]) for label, total in _TOTALS.items()}


def _wrap(label: str, func: Callable[..., Any]) -> Callable[..., Any]:
    """*func*, timed under *label*, counting an exception as a call that happened."""

    def timed(*args: object, **kwargs: object) -> object:
        started = time.perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            # IN A ``finally``: a call that RAISED still consumed the time and still happened, and a
            # wrapper that counted only successes would report a failing seam as free.
            _TOTALS[label] += time.perf_counter() - started
            _CALLS[label] += 1

    timed.__name__ = getattr(func, '__name__', label)
    timed.__doc__ = getattr(func, '__doc__', None)
    return timed


def _resolve(seam: Seam) -> tuple[object, str] | None:
    """``(owner, attribute)`` for *seam*, or ``None`` when any hop of the path is absent."""
    try:
        owner: object = importlib.import_module(seam.module)
    except ImportError:
        return None
    parts = seam.path.split('.')
    for part in parts[:-1]:
        owner = getattr(owner, part, None)
        if owner is None:
            return None
    return (owner, parts[-1]) if getattr(owner, parts[-1], None) is not None else None


def install(seams: Iterable[Seam]) -> tuple[str, ...]:
    """Patch every seam that RESOLVES, and return the labels that did NOT, in the order given.

    Every patch goes through :func:`rebind`, so one :func:`restore_all` undoes the whole set.

    Returns:
        The labels that could not be resolved. An EMPTY tuple means every named seam was found --
        which is the reading a caller must check before trusting the numbers, because an unresolved
        dominant term reports as a term that costs nothing.

    """
    missing: list[str] = []
    for seam in seams:
        resolved = _resolve(seam)
        if resolved is None:
            missing.append(seam.label)
            continue
        owner, attribute = resolved
        rebind(owner, attribute, _wrap(seam.label, getattr(owner, attribute)))
    return tuple(missing)
