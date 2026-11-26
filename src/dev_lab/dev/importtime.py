"""The import-time report: what each package costs to import, cold, heaviest first -- a part of the complexity report.

F9 (a consumer request, 2026-11-26): import cost was measured by hand in a consumer venv -- optimi_lab 9.7 s,
lab_commons.viz.bokeh 8.8 s, scipy.sparse.linalg 7.5 s -- and nothing in the family could repeat the measurement.
This is that measurement as a door: ``python -m dev_lab.dev.complexity imports [MODULE ...]``.

HOW IT MEASURES. Each module is imported in a FRESH interpreter (``<python> -X importtime -c "import <module>"``), so
every run is cold with respect to the interpreter (the OS file cache is not flushed: that is the "cold" a developer
meets on the second start of a day). The reading is CPython's own cumulative microseconds for the module's line in
the ``-X importtime`` table, never a wall clock around the process, so interpreter start-up and ``site`` are not
charged to the module. The best of *runs* is kept: noise only ever adds time.

A REPORT, NOT A GATE, like the rest of :mod:`dev_lab.dev.complexity`: nothing here refuses a value. A module that
fails to import is reported with its error, never dropped, so an absent extra cannot read as a fast import.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final

import lab_commons.launch as _door

__all__ = ['DEFAULT_RUNS', 'ImportCost', 'measure', 'parse', 'report']

#: Best of three, as the hand measurement this replaces was taken.
DEFAULT_RUNS: Final = 3
#: Seconds one import may take before it is reported as timed out.
_WALL_S: Final = 300.0
#: One row of ``-X importtime``: ``import time: <self us> | <cumulative us> | <indented module>``.
_ROW: Final = re.compile(r'^import time:\s+(\d+)\s*\|\s*(\d+)\s*\|\s?(\s*)(\S+)\s*$')
_US_PER_S: Final = 1e6


@dataclass(frozen=True, slots=True)
class ImportCost:
    """One module's cold import: the best cumulative seconds, or the error that stopped it."""

    module: str
    seconds: float | None
    error: str = ''

    def line(self) -> str:
        """``  9.700 s  optimi_lab`` -- or the module with its error."""
        if self.seconds is None:
            return f'  failed    {self.module}: {self.error}'
        return f'{self.seconds:8.3f} s  {self.module}'


def parse(table: str) -> dict[str, float]:
    """``{module: cumulative seconds}`` read off a ``-X importtime`` table; a module seen twice keeps its first row."""
    found: dict[str, float] = {}
    for raw in table.splitlines():
        if (row := _ROW.match(raw.rstrip())) is not None:
            found.setdefault(row[4], int(row[2]) / _US_PER_S)
    return found


def measure(module: str, *, python: str, runs: int = DEFAULT_RUNS, run: Callable[..., Any] = _door.run) -> ImportCost:
    """*module*'s best cold cumulative import time over *runs* fresh interpreters of *python*."""
    best: float | None = None
    for _ in range(max(1, runs)):
        done = run(
            [python, '-X', 'importtime', '-c', f'import {module}'],
            capture_output=True, text=True, encoding='utf-8', errors='replace', check=False, timeout=_WALL_S,
        )  # fmt: skip
        if done.returncode != 0:
            tail = (done.stderr or '').strip().splitlines()
            return ImportCost(module, None, tail[-1] if tail else f'exit {done.returncode}')
        seconds = parse(done.stderr or '').get(module)
        if seconds is None:
            return ImportCost(module, None, 'already imported at start-up (no -X importtime row)')
        best = seconds if best is None else min(best, seconds)
    return ImportCost(module, best)


def report(
    modules: Sequence[str], *, python: str, runs: int = DEFAULT_RUNS, run: Callable[..., Any] = _door.run
) -> list[ImportCost]:
    """Every module measured, the heaviest first and the failures last."""
    costs = [measure(module, python=python, runs=runs, run=run) for module in dict.fromkeys(modules)]
    return sorted(costs, key=lambda c: (c.seconds is None, -(c.seconds or 0.0), c.module))
