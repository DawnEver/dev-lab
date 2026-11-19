"""The offline half of :class:`dev_lab.dev.forgeunit.ForgeResults`: a post or grave the forge did not take waits here.

A transient failure (a dropped connection, a transient answer) with a pending directory set is HELD, never raised;
a FINAL refusal still raises. :func:`flush_held` lands held results before the graves that close them and stops
at the first the forge still cannot take. Carved out of ``forgeunit`` to keep it inside the module-size band.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lab_commons.compute.durable import durable_write
from lab_commons.log import emit

from dev_lab.dev.forgefailure import ForgeCallFailed

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

__all__ = ['flush_held', 'hold', 'transient', 'unread']

#: A held grave's name; graves land after the results they close.
_GRAVE_PREFIX = 'grave-'


def transient(failed: OSError) -> bool:
    """A forge call that may land later: a dropped connection or a transient answer, never a FINAL refusal."""
    return not (isinstance(failed, ForgeCallFailed) and failed.final is not None)


def hold(pending: Path | None, path: Path, failed: OSError) -> None:
    """Keep *path* in *pending* when *failed* is transient and there is one; else raise *failed*."""
    if pending is None or not transient(failed):
        raise failed
    durable_write(pending / path.name, path.read_bytes())
    emit(f'[results] held {path.name}: the forge did not take it ({failed}); a forge tick lands it', err=True)


def unread(pending: Path | None, failed: OSError, what: str) -> None:
    """An offline read: unknown, said, when *pending* is set and *failed* is transient; else raise."""
    if pending is None or not transient(failed):
        raise failed
    emit(f'[results] {what} unread: the forge did not answer ({failed}); read as nothing posted', err=True)


def flush_held(pending: Path | None, land: Callable[[Path], None]) -> list[str]:
    """Land every held result, then every held grave; stop at the first the forge still cannot take."""
    from dev_lab.dev.forgeunit import Nondeterministic  # noqa: PLC0415 -- the store's own error; no import cycle

    if pending is None or not pending.is_dir():
        return []
    lines: list[str] = []
    for held in sorted(pending.iterdir(), key=lambda one: (one.name.startswith(_GRAVE_PREFIX), one.name)):
        try:
            land(held)
        except Nondeterministic as differs:
            lines.append(f'results: dropped {held.name} -- {differs}')
        except OSError as failed:
            if transient(failed):
                lines.append(f'results: kept {held.name} -- the forge is unreachable ({failed})')
                break
            lines.append(f'results: dropped {held.name} -- the forge refused it, final ({failed})')
        else:
            lines.append(f'results: landed {held.name}')
        held.unlink()
    return lines
