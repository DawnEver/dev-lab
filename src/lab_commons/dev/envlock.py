"""Verdicts and mutations exclude each other in the same canonical environment."""

import hashlib
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from lab_commons.resources import SEATS, Broker, Capacity, CapacityRegistry, Grant

__all__ = ['EnvLock']


class EnvLock:
    """One broker seat per resolved prefix, independent of the box's CPU seat."""

    def __init__(self, prefix: Path | str, what: str, *, broker: Broker | None = None) -> None:
        """Identify the actual target prefix and bind its existing broker seat."""
        identity = os.path.normcase(str(Path(prefix).resolve()))
        self.pool = 'environment-' + hashlib.sha256(identity.encode()).hexdigest()
        self.what = what
        self.broker = broker or Broker(CapacityRegistry())
        self.broker.registry.declare(
            self.pool, Capacity.structural(SEATS.name, 1, note='a verdict and mutation may not share an environment')
        )

    @contextmanager
    def held(self) -> Iterator[Grant]:
        """Hold through the operation, closing both directions of the start/mutation race."""
        with self.broker.admit(self.pool, {SEATS.name: 1}, what=self.what) as grant:
            yield grant
