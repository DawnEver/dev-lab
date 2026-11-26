"""A tick's candidate DEMAND: what a part or request will ask of this box, or of a cluster account.

:mod:`dev_lab.dev.forgetick` ranks candidates against a supply; this module sizes each one -- a box part at the
ids its commit's parts hand it, a box request by its own row, a cluster part by its measured ask.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING

from lab_commons.box import GB, Capacity
from lab_commons.box.providers import box_engine
from lab_commons.compute.learned import box_demand, request_demand
from lab_commons.compute.model import REQUEST, Candidate, Supply
from lab_commons.compute.presence import cached

from dev_lab.dev.forgedemand import part_demand
from dev_lab.dev.forgerequest import declared_request
from dev_lab.dev.platformparts import origin_url, parts_of

if TYPE_CHECKING:
    from pathlib import Path

    from dev_lab.dev.forgestatus import CommitStatus

__all__ = ['box_now', 'demand_of', 'handed']


def box_now() -> Supply:
    """What lies outside this box ledger's claims now (:func:`lab_commons.box.providers.box_engine`)."""
    return box_engine(capacity=Capacity.read(), presence=cached()).available('box')


def handed(statuses: Sequence[CommitStatus], part: str) -> int | None:
    """How many ids the commit's posted parts hand to *part* -- its selection's size; ``None`` when none says."""
    counts = [one.hands[part] for one in parts_of(statuses)[0].values() if part in one.hands]
    return sum(counts) if counts else None


def demand_of(
    root: Path,
    *,
    cluster: bool,
    history: Callable[[str], Sequence[CommitStatus]] = lambda _sha: (),
    room: Supply | None = None,
) -> Callable[[Candidate, frozenset[str]], Mapping[str, float]]:
    """A candidate's demand: a cluster part's measured ask, else what it will declare to this box.

    A box REQUEST is sized by its own row (:func:`~lab_commons.compute.learned.request_demand`), a box part
    by :func:`~lab_commons.compute.learned.box_demand` at the ids its commit's parts hand it (:func:`handed`),
    narrowed to the box's FREE *room* (this tick's supply; measured now when not given).
    """
    repo_url = origin_url(root)
    if cluster:
        asked = part_demand(repo_url, ceiling_gb=None)
        return lambda _wanted, needed: asked(needed)
    free = (room or box_now()).resources

    def sized(wanted: Candidate, needed: frozenset[str]) -> Mapping[str, float]:
        if wanted.kind == REQUEST:
            row = declared_request(root, wanted.sha, wanted.producer, wanted.paths)
            return request_demand(repo_url, row.name, needed, cpu=row.cpu, mem_gb=row.mem / GB)
        ids = handed(history(wanted.sha), wanted.platform)
        return box_demand(repo_url, needed, cpu=free['cpu'], mem_gb=free['mem_gb'], ids=ids)

    return sized
