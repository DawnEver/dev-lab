"""Where each declared vendor is installed on THIS machine: the newest directory its family patterns match.

Split from :mod:`dev_lab.dev.devhost` (whose ``detect`` verb prints the result): a pure filesystem reader.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ['detect']


def _matches(pattern: str) -> list[Path]:
    anchored = Path(pattern)
    return list(Path(anchored.anchor).glob(str(anchored.relative_to(anchored.anchor))))


def detect(patterns: Mapping[str, list[str]]) -> dict[str, str]:
    """Each vendor's install home on THIS machine: the last (newest-named) directory its patterns match."""
    found = {}
    for name, globs in patterns.items():
        hits = sorted({hit for pattern in globs for hit in _matches(pattern) if hit.is_dir()})
        if hits:
            found[name] = hits[-1].as_posix()
    return found
