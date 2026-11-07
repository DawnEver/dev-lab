"""WHAT A HEAD RUNS: the full suite on the integration tip, else only what its diff reaches (user ruling 2026-11-07).

One PR's tests finish within an hour. :func:`scope_of` is the scope a candidate is claimed at
(:mod:`dev_lab.dev.forgeschedule`); an INCREMENTAL cluster run submits :class:`ReachedFiles` as
``RunSpec.only`` (:func:`dev_lab.dev.forgeslurm.scoped_files`), the files
:func:`dev_lab.dev.forgecarry.reached_tests` selects.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from lab_commons.compute.model import INTEGRATION, REQUEST
from lab_commons.hpc.shell import FULL, INCREMENTAL

__all__ = ['FULL_SUITE_LABEL', 'ReachedFiles', 'scope_of']

#: The label that asks a PR head for the FULL suite instead of what its diff reaches (:func:`scope_of`).
FULL_SUITE_LABEL: Final = 'forge:full'


def scope_of(kind: str, labels: Sequence[str]) -> str:
    """The scope a part of a *kind* head runs at: FULL on the integration tip, else INCREMENTAL.

    User ruling 2026-11-07 (one PR's tests within an hour): the full suite runs only on the integration ref's
    tip; every other head runs only the test files its diff from the integration branch reaches
    (:func:`dev_lab.dev.forgecarry.reached_tests`), the rest standing on the integration tip's verdict. A head
    labelled :data:`FULL_SUITE_LABEL` asks for the full suite; a request is always full.
    """
    if kind in {INTEGRATION, REQUEST} or FULL_SUITE_LABEL in labels:
        return FULL
    return INCREMENTAL


class ReachedFiles(frozenset[str]):
    """Test FILE paths read as :attr:`lab_commons.hpc.shell.RunSpec.only`: a node id is in it when its file is.

    :func:`lab_commons.hpc.run.submit_run` keeps a collected id ``in`` *only* and a collection error whose path
    an element of *only* names; a set of files answers both, so every id of a reached file runs, parametrized
    and class-held ones too, and a reached file that fails to collect is still reported.
    """

    __slots__ = ()

    def __contains__(self, node: object) -> bool:
        """Whether *node* (an id or a path) lies in one of these files."""
        return isinstance(node, str) and frozenset.__contains__(self, node.split('::', 1)[0])
