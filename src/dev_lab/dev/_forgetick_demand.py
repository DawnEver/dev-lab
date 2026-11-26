"""WHAT A TICK SIZES BY: the supply it admits against and the demand each candidate asks of it.

A box tick measures this box now; a cluster tick is handed its account's measured standing and never guesses it.
The tick that admits with these is :mod:`dev_lab.dev.forgetick`.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from lab_commons.box import GB, Capacity
from lab_commons.box.providers import box_engine
from lab_commons.compute.learned import box_demand, request_demand
from lab_commons.compute.model import (
    REQUEST,
    Candidate,
    Supply,
)
from lab_commons.compute.presence import cached

from dev_lab.dev.forgedemand import part_demand
from dev_lab.dev.forgerequest import declared_request
from dev_lab.dev.forgestatus import CommitStatus
from dev_lab.dev.platformparts import origin_url, parts_of


def whole_supply(scope: str, *, cluster: bool) -> Supply:
    """A tick given no supply: this box as its providers measure it now; an account is never guessed.

    Raises:
        ValueError: on a cluster seat -- an account's supply is its measured standing, and an unmeasured one admits
            nothing rather than a default task.

    """
    if cluster:
        msg = f"{scope}: a cluster tick needs the account's measured supply (forgeslurm standing); none was given"
        raise ValueError(msg)
    return dataclasses.replace(free_box_supply(), scope=scope)


def free_box_supply() -> Supply:
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
    free = (room or free_box_supply()).resources

    def sized(wanted: Candidate, needed: frozenset[str]) -> Mapping[str, float]:
        if wanted.kind == REQUEST:
            row = declared_request(root, wanted.sha, wanted.producer, wanted.paths)
            return request_demand(repo_url, row.name, needed, cpu=row.cpu, mem_gb=row.mem / GB)
        ids = handed(history(wanted.sha), wanted.platform)
        return box_demand(repo_url, needed, cpu=free['cpu'], mem_gb=free['mem_gb'], ids=ids)

    return sized
