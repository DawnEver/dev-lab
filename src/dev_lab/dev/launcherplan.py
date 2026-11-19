"""What the installer does with a repo's agent launcher: keep it, keep the repo's own, or (re)write dev-lab's.

A launcher dev-lab shipped carries :data:`LAUNCHER_PROVENANCE`; present with other bytes it is STALE and is
replaced. A launcher without that line is the repo's own and is kept. Reads one file; writes nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['LAUNCHER_PROVENANCE', 'launcher_plan']

#: The line every launcher dev-lab ever shipped carries: present with other bytes means a STALE shipped launcher.
LAUNCHER_PROVENANCE: Final = 'Launcher shipped by dev-lab'


def launcher_plan(launcher: Path, shipped: str) -> tuple[str | None, str]:
    """``(text to write or None, the action line)`` for *launcher* against the *shipped* source."""
    present = launcher.read_text(encoding='utf-8') if launcher.exists() else None
    if present is not None and present.replace('\r\n', '\n') == shipped.replace('\r\n', '\n'):
        return None, f'launcher already current: {launcher}'
    if present is not None and LAUNCHER_PROVENANCE not in present:
        return None, f'launcher is the repo own, kept: {launcher}'
    replaced = 'replaced (a stale dev-lab launcher)' if present is not None else 'installed'
    return shipped, f'launcher {replaced}: {launcher}'
