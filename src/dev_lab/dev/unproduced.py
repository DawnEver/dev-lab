"""AN UNPRODUCED RESOURCE -- a need-set a repo declares no part for, so no reading waits on one.

User ruling 2026-10-30: the toolchain repos live on GitHub, and no hosted runner is a workstation. A repo
whose tests marked with a resource can run nowhere it is served declares it ONCE, in its pyproject::

    [tool.dev_lab.parts]
    unproduced = ["workstation"]

Its marked tests keep their need-set (:mod:`lab_commons.hpc.needsets`) and are run by no part. Every part
needing it is WAIVED by every reading -- ``integrate promote``, the queue, the tick, the integration
feedback (:func:`unproduced_waived`) -- and has no workflow row (:mod:`dev_lab.dev.jobparts`), so nothing
waits on, or posts ``absent`` for, a part no producer will post. A name outside the repo's
``[tool.lab_commons.tests] resources`` is refused by name; an unreadable declaration waives nothing.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from lab_commons.hpc.declared import pyproject_at
from lab_commons.hpc.needsets import needs_of, read_vocabulary

from dev_lab.dev.family import declared_in
from dev_lab.dev.partrows import row_part
from dev_lab.dev.platformparts import UndeclaredPart, derived

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Sequence
    from pathlib import Path

    from dev_lab.dev.forgestatus import CommitStatus

__all__ = ['unproduced', 'unproduced_at', 'unproduced_parts', 'unproduced_waived']


def unproduced(text: str) -> frozenset[str]:
    """The resources pyproject *text* declares unproduced; a name it does not mark is refused."""
    value = declared_in(text, 'parts').get('unproduced', [])
    resources = set(read_vocabulary(text).resources)
    if not isinstance(value, list) or not all(isinstance(name, str) and name in resources for name in value):
        msg = f'[tool.dev_lab.parts] unproduced = {value!r}: names from tests resources {sorted(resources)}'
        raise UndeclaredPart(msg)
    return frozenset(value)


def unproduced_at(root: Path, sha: str) -> frozenset[str]:
    """:func:`unproduced` of the declaration commit *sha* of *root* carries."""
    return unproduced(pyproject_at(root, sha))


def unproduced_parts(names: Iterable[str], resources: Collection[str]) -> frozenset[str]:
    """The parts (or rows) of *names* needing any of *resources*."""
    return frozenset(name for name in names if needs_of(row_part(name)) & set(resources))


def unproduced_waived(root: Path, sha: str, statuses: Sequence[CommitStatus]) -> frozenset[str]:
    """The derived parts of *statuses* commit *sha* declares unproduced; an unreadable declaration waives nothing."""
    try:
        resources = unproduced_at(root, sha)
    except (ValueError, subprocess.SubprocessError):
        return frozenset()
    return unproduced_parts(derived(statuses), resources)
