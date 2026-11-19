"""After a ``dep`` build: publish the new environment (or drop a failed one) and render the local auto-mode prose.

Carved out of :mod:`dev_lab.dev.dep` so the door stays inside the module-size band; :func:`publish_built` and
:func:`refresh_automode` are its last two steps, unchanged.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from lab_commons.log import emit

from dev_lab.dev import venvcurrent
from dev_lab.dev._dep_components import record
from dev_lab.dev._dep_network import CHILD_WALL_S
from dev_lab.dev.liverun import Census

__all__ = ['publish_built', 'refresh_automode']


def publish_built(root: Path, prefix: Path, live: Path, *, ok: bool, census: Census, base: str) -> int:
    """Publish the environment just built (or drop a failed build), then reclaim every one nothing runs from.

    Nonzero when the build is published but the :data:`~dev_lab.dev.venvpointer.ALIAS` still runs another
    environment (a held legacy ``.venv`` directory): a caller of ``.venv`` would still meet the stale one.
    """
    if prefix == live or not ok:
        if prefix != live:
            venvcurrent.abandon(prefix)
        return 0
    record(root, prefix)  # the trees this environment now holds its components at
    emit(f'published {prefix}: {venvcurrent.publish(root, prefix)}')
    for line in venvcurrent.reclaim(root, census=census, building_here=True):
        emit(line)
    if why := venvcurrent.stale_alias(root, prefix, prefix.joinpath(*Path(base).relative_to(live).parts)):
        emit(f'REFUSED: {why}')
        return 1
    return 0


def refresh_automode(root: Path, *, run: Callable[..., Any]) -> None:
    """Render the checkout's machine-local auto-mode prose (:mod:`dev_lab.dev.automode`), in its own process.

    Its own process so this door imports nothing of the forge it does not need; it always exits 0 and prints
    why it wrote nothing when a fleet source is unreadable here, so it never fails the sync.
    """
    run(
        [sys.executable, '-m', 'dev_lab.dev.automode', 'write', '--repo', str(root)],
        check=False,
        timeout=CHILD_WALL_S,
        cwd=root,
    )
