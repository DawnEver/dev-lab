"""THE ENVIRONMENT SEAT: a verdict and a mutation never share one Python environment.

TWO RESOURCES, ONE LEDGER. The box ledger (:mod:`lab_commons.box`) holds the MACHINE's cores and memory for
RUNS, and it holds this seat too: a named exclusion keyed by ONE environment (the resolved prefix of its
interpreter), claimed with no cores and no memory. A run and a mutation of THAT environment contend for it;
a verify in repo A therefore never refuses a sync of repo B's venv, while a sync of A's venv mid-verify is
refused naming the run. (It had a second ledger of its own until D2 of 2026-10-16 folded it in.)
"""

from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons.box import POLL_S, Claim, Demand, Holding, hold, holdings

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ['SEAT_WALL_S', 'EnvironmentSeat', 'environment_seat']

#: How long an environment seat may be held, in seconds: a day, as a hung run's wall.
SEAT_WALL_S: Final = 24 * 3600


def environment_seat(prefix: Path | str) -> str:
    """The seat of the environment at *prefix*: one per RESOLVED, case-normalised prefix."""
    identity = os.path.normcase(str(Path(prefix).resolve()))
    return 'environment_' + hashlib.sha256(identity.encode()).hexdigest()[:32]


class EnvironmentSeat:
    """One seat per environment on the box ledger, independent of the cores and memory a run claims."""

    def __init__(self, prefix: Path | str, what: str, *, wait_s: float = 0.0, poll_s: float = POLL_S) -> None:
        """Bind the seat of the environment at *prefix*."""
        self.seat = environment_seat(prefix)
        self.what = what
        self.wait_s = wait_s
        self.poll_s = poll_s

    @contextmanager
    def held(self) -> Iterator[Claim]:
        """Hold the environment for the operation, or raise :class:`~lab_commons.box.Refused` naming its holder."""
        demand = Demand(cpu=0, mem_gb=0.0, wall_s=SEAT_WALL_S, seats={self.seat: 1})
        with hold(demand, self.what, self.wait_s, poll_s=self.poll_s, key=self.seat) as claim:
            yield claim

    @staticmethod
    def holders(prefix: Path | str) -> tuple[Holding, ...]:
        """Who holds THIS environment now, without taking it; a holder of another environment is not named."""
        seat = environment_seat(prefix)
        return tuple(one for one in holdings() if one.seats.get(seat))
