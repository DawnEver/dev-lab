"""THE SERIAL PASS: a test marked ``serial`` runs ALONE, on one worker, after the parallel pass.

Some tests cannot shrink without loosening a bar -- an IGD ceiling measured at a fixed budget, a periodic
steady state at ``rtol 1e-8`` -- and sharing a hosted runner with three other workers is what starves them
(D101 follow-ups). The family declares ONE marker for them, :data:`SERIAL_MARK`, here and nowhere else: this
plugin registers it in every run that loads it, so no consumer lists it in its own ``markers``.

:mod:`dev_lab.dev.verify` runs the selection twice under the plugin, the pass named by :data:`STAGE_ENV`:
``parallel`` DESELECTS every marked item (the caller's own ``-m``/``-k`` untouched -- the split composes with
any selection because it is applied after it), ``serial`` deselects every UNMARKED one and runs at ``-n 0``.
The parallel pass also touches the file :data:`SEEN_ENV` names when it deselected a marked item -- under xdist
the summary prints no ``deselected`` count, so that file is how verify knows a serial pass has anything to run.
Without the variables the plugin only registers the marker, so a plain run is unchanged.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    'PLUGIN',
    'SEEN_ENV',
    'SERIAL_BANNER',
    'SERIAL_LINE',
    'SERIAL_MARK',
    'STAGE_ENV',
    'Stage',
    'pytest_collection_modifyitems',
    'pytest_configure',
]

#: The family's one marker for a test that must run alone.
SERIAL_MARK: Final = 'serial'

#: Its ``markers`` ini line.
SERIAL_LINE: Final = (
    f'{SERIAL_MARK}: runs ALONE in verify`s single-worker pass after the parallel one -- a test whose bar '
    f'cannot shrink and which a shared runner starves (dev_lab.dev.serialpass)'
)

#: How verify names the pass to the pytest it launches.
STAGE_ENV: Final = 'DEV_LAB_VERIFY_STAGE'

#: The file the parallel pass touches when it deselected a marked item.
SEEN_ENV: Final = 'DEV_LAB_VERIFY_SERIAL_SEEN'

#: The line that opens the serial stage's half of a verify log; the parallel half's reading stops at it.
SERIAL_BANNER: Final = '--- pytest serial ---\n'

#: The plugin argv a verify run loads.
PLUGIN: Final[tuple[str, ...]] = ('-p', __name__)

type Stage = Literal['parallel', 'serial']


class _Config(Protocol):
    def addinivalue_line(self, name: str, line: str) -> None: ...


class _Item(Protocol):
    def get_closest_marker(self, name: str) -> object | None: ...


class _Hook(Protocol):
    def pytest_deselected(self, *, items: Sequence[_Item]) -> None: ...


class _HookConfig(Protocol):
    @property
    def hook(self) -> _Hook: ...


def pytest_configure(config: _Config) -> None:
    """Register :data:`SERIAL_MARK`, so ``--strict-markers`` accepts it in every repo verify runs."""
    config.addinivalue_line('markers', SERIAL_LINE)


def pytest_collection_modifyitems(config: _HookConfig, items: list[_Item]) -> None:
    """Keep only the items of the pass :data:`STAGE_ENV` names, reporting the rest deselected; inert without it."""
    which = os.environ.get(STAGE_ENV, '')
    if which not in ('parallel', 'serial'):
        return
    keep = which == 'serial'
    kept = [item for item in items if (item.get_closest_marker(SERIAL_MARK) is not None) is keep]
    dropped = [item for item in items if (item.get_closest_marker(SERIAL_MARK) is not None) is not keep]
    if dropped:
        config.hook.pytest_deselected(items=dropped)
        items[:] = kept
        if not keep and (seen := os.environ.get(SEEN_ENV)):
            Path(seen).touch()
