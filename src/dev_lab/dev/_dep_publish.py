"""After a ``dep`` build: publish the new environment (or drop a failed one) and reclaim the stale ones.

Carved out of :mod:`dev_lab.dev.dep` so the door stays inside the module-size band; what follows a successful
sync lives in :mod:`dev_lab.dev._dep_aftersync`.
"""

from __future__ import annotations

from pathlib import Path

from lab_commons.log import emit

from dev_lab.dev import venvcurrent
from dev_lab.dev._dep_components import record
from dev_lab.dev.liverun import Census

__all__ = ['publish_built']


def publish_built(root: Path, prefix: Path, live: Path, *, ok: bool, census: Census) -> int:
    """Publish the environment just built (or drop a failed build), then reclaim every one nothing runs from.

    Nonzero when the build cannot be published: a plain ``.venv`` directory a process still runs from
    (:class:`~dev_lab.dev.venvcurrent.PublishRefused`).
    """
    if prefix == live or not ok:
        if prefix != live:
            venvcurrent.abandon(prefix)
        return 0
    record(root, prefix)  # the trees this environment now holds its components at
    try:
        emit(f'published {prefix}: {venvcurrent.publish(root, prefix, census=census)}')
    except venvcurrent.PublishRefused as refused:
        emit(f'REFUSED: {refused}')
        return 1
    for line in venvcurrent.reclaim(root, census=census, building_here=True):
        emit(line)
    return 0
