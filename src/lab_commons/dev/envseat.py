"""THE ENVIRONMENT SEAT: a verdict and a mutation never share one Python environment.

TWO RESOURCES, TWO NAMES. :class:`~lab_commons.dev.cpuseat.CpuSeat` is the MACHINE's CPU capacity,
contended by RUNS only -- a dependency sync is not CPU-saturating and never takes it. This seat is
keyed by ONE environment (the resolved prefix of its interpreter), and is what a run and a mutation
of THAT environment contend for. A verify in repo A therefore never refuses a sync of repo B's venv,
while a sync of A's venv mid-verify is refused naming the run.
"""

from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from lab_commons.resources import DEFAULT_POLL_S, SEATS, Broker, Capacity, CapacityRegistry, Grant, Holder

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ['EnvironmentSeat', 'environment_pool']


def environment_pool(prefix: Path | str) -> str:
    """The broker pool of the environment at *prefix*: one per RESOLVED, case-normalised prefix."""
    identity = os.path.normcase(str(Path(prefix).resolve()))
    return 'environment-' + hashlib.sha256(identity.encode()).hexdigest()


class EnvironmentSeat:
    """One structural seat per environment, independent of the machine's CPU seat."""

    def __init__(
        self,
        prefix: Path | str,
        what: str,
        *,
        wait_s: float = 0.0,
        poll_s: float = DEFAULT_POLL_S,
        broker: Broker | None = None,
    ) -> None:
        """Bind the seat of the environment at *prefix*, declared on *broker* (a fresh one by default)."""
        self.pool = environment_pool(prefix)
        self.what = what
        self.wait_s = wait_s
        self.poll_s = poll_s
        self.broker = _declared(self.pool, broker)

    @contextmanager
    def held(self) -> Iterator[Grant]:
        """Hold the environment for the operation, or raise ``Exhausted`` naming its holder."""
        with self.broker.admit(
            self.pool, {SEATS.name: 1}, what=self.what, wait_s=self.wait_s, poll_s=self.poll_s
        ) as grant:
            yield grant

    @staticmethod
    def holders(prefix: Path | str, *, broker: Broker | None = None) -> tuple[Holder, ...]:
        """Who holds THIS environment now, without taking it; a holder of another environment is not named."""
        pool = environment_pool(prefix)
        return tuple(holder for holder in _declared(pool, broker).holders(pool) if holder.pool == pool)


def _declared(pool: str, broker: Broker | None) -> Broker:
    broker = broker or Broker(CapacityRegistry())
    broker.registry.declare(
        pool, Capacity.structural(SEATS.name, 1, note='a verdict and a mutation may not share an environment')
    )
    return broker
