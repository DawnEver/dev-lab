"""The task ledger PUBLISHES its own write (v1 FAM-15): a ledger commit nobody pushes is a clone drifting silently.

* :func:`publish` -- after each ledger commit, push the clone to its ``origin`` through the netverb retry loop
  (:func:`dev_lab.dev.netverb.run_network_verb`). A failed publish is REPORTED by name with its door and never
  raised: the local write already stands;
* :func:`ahead_warning` -- every task verb names a clone ahead of its origin: the count and the same door.

A clone with no ``origin`` remote has nowhere to publish: both stay silent.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Final

from dev_lab.dev._task_io import GIT, git

__all__ = ['REMOTE', 'ahead_warning', 'door', 'publish']

#: The remote the ledger clone publishes to.
REMOTE: Final = 'origin'
_sleep = time.sleep


def door(root: Path) -> str:
    """The exact command that retries the publish of the ledger clone at *root*."""
    return f'python -m dev_lab.dev.netverb --cwd {root.as_posix()} -- git push {REMOTE} HEAD'


def _has_origin(root: Path) -> bool:
    return git(root, 'remote', 'get-url', REMOTE)[0] == 0


def publish(root: Path) -> str | None:
    """Push the ledger clone at *root* to its origin; ``None`` when published (or no origin), else the report."""
    from dev_lab.dev.netverb import run_network_verb  # noqa: PLC0415 -- the retry loop, only when a write landed

    if not _has_origin(root):
        return None
    report = run_network_verb([GIT, 'push', '-q', REMOTE, 'HEAD'], cwd=root, sleep=_sleep)
    if report.ok:
        return None
    return f'[task] the ledger write committed locally but was not published: {report.remedy}\nDoor: {door(root)}'


def ahead_warning(root: Path) -> str | None:
    """The warning naming how far the ledger clone at *root* is ahead of its origin; ``None`` when in sync."""
    if not _has_origin(root):
        return None
    code, said = git(root, 'rev-list', '--count', 'HEAD', '--not', f'--remotes={REMOTE}')
    if code != 0 or not said.isdigit() or int(said) == 0:
        return None
    count = int(said)
    return (
        f'[task] the ledger {root.as_posix()} is {count} commit{"s" if count != 1 else ""} ahead of {REMOTE}: '
        f'its writes are unpublished.\nDoor: {door(root)}'
    )
