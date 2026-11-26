"""A VOLUME UNDER ITS FLOOR IS HEARD AT SESSION START, not when a write fails (dev-lab#46).

2026-11-01: an agent session filled a workstation's checkout volume to 0.1 MB free and every other session on it
stopped; no hook had warned. The floor already existed -- ``[storage] free_floor_gb`` / ``free_floor_files``
(:func:`lab_commons.storage.free_floor`), the bound every regenerable cache keeps -- but only a cache write read it.

:func:`notice` reads the SAME floor against the volume holding the session's checkout (:func:`lab_commons.compute.
floor.measure`: the volume's free bytes, capped by a declared quota, and its files where a quota limits them) and
says one line when it does not hold, naming the reclaim door. Silent when it holds. It never blocks a session.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from lab_commons.compute.floor import measure
from lab_commons.storage import free_floor

from dev_lab.dev.venvpath import running_interpreter

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from lab_commons.headroom import Floor

__all__ = ['DOOR', 'notice']

#: What frees a checkout volume: reclaim the landed worktrees, each of which holds its own environment.
DOOR: Final = '{python} -m dev_lab.dev.reclaimrun --root <main checkout>'

_GB: Final = 1024**3


def notice(
    volume: Path,
    *,
    floor: Floor | None = None,
    reads: Callable[[Path, Floor], tuple[int, tuple[int, int] | None]] = measure,
) -> str | None:
    """The line saying *volume* is under the ``[storage]`` floor, with the door; ``None`` when the floor holds."""
    held = floor if floor is not None else free_floor()
    free, files = reads(volume, held)
    short = [f'{free / _GB:.1f} GB free under the {held.bytes / _GB:g} GB floor'] if free < held.bytes else []
    if files is not None and files[1] < files[0]:
        short.append(f'{files[1]} files left under the {files[0]} files floor')
    if not short:
        return None
    door = DOOR.replace('{python}', running_interpreter())
    return f'[storage] the volume holding {volume} is under its [storage] floor: {"; ".join(short)} -- free it: {door}'
