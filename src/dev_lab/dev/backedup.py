"""A FILE REPLACED WHOLE, its previous content kept: the one write the machine-file doors make.

Split out of :mod:`dev_lab.dev.devhost` (2026-11-20, MODULE-SIZE-ALARM): ``render --write`` and ``local set``
both replace the machine file this way -- staged beside it and renamed over it, so a reader never sees half a
file, and the old bytes copied into a dated backup first, so every door's change can be undone by hand.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

__all__ = ['replace_backed_up']


def replace_backed_up(path: Path, text: str, backups: Path) -> Path:
    """Replace *path* with *text* atomically, its previous content first copied into *backups*; the copy's path."""
    backups.mkdir(parents=True, exist_ok=True)
    backup = backups / f'{path.name}.{datetime.now(UTC):%Y%m%dT%H%M%SZ}'
    if path.is_file():
        backup.write_bytes(path.read_bytes())
    staged = path.with_name(f'{path.name}.{os.getpid()}.tmp')
    staged.write_text(text, encoding='utf-8')
    staged.replace(path)
    return backup
