"""THE CLAIM PASS of a tick (:mod:`lab_commons.dev.forgetick`): walk the ranked queue, claim each candidate that admits.

Each candidate becomes a :class:`~lab_commons.compute.model.Job` carrying its origin (login, vouched host,
session); it is blocked by a refused declaration, a lacking capability, an unproducible repo, its sha's
tree being busy here, its ref's budget, or admission -- and otherwise claimed, its demand then counted as
running for every later candidate. :meth:`ClaimPass.reserved` is what ranks a lease holder's job first.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from lab_commons.compute.model import REQUEST, Candidate, Job, Ranked, Reservation, Schedule, Supply, admit
from lab_commons.dev.forgeclaim import CLAIMABLE, MINE, Claim, Serving, Work, assess, claim
from lab_commons.dev.forgeprovides import lacking, needs
from lab_commons.dev.forgeschedule import NO_HOST, NOT_ADMITTED, over_budget
from lab_commons.dev.forgestatus import status_history
from lab_commons.dev.forgework import Client
from lab_commons.dev.platformparts import UndeclaredPart, cluster_part, part_argv, part_context
from lab_commons.hpc.platforms import Table, declared_at
from lab_commons.hpc.shell import FULL

__all__ = ['ClaimPass']


@dataclass
class ClaimPass:
    """The claim pass over the ranked queue: each candidate that admits is claimed, the rest say why not."""

    root: Path
    client: Client
    serve: Serving
    me: Claim
    now: datetime
    schedule: Schedule
    usage: Mapping[str, float] | None
    dry_run: bool
    repo: str
    supply: Supply
    size: Callable[[Candidate, frozenset[str]], Mapping[str, float]]
    reservations: tuple[Reservation, ...] = ()
    taken: list[Mapping[str, float]] = dataclasses.field(default_factory=list)  # what runs, then each claim
    trees: set[str] = dataclasses.field(default_factory=set)  # the shas a local claim of this tick holds
    unproducible: str = ''  # why the repo's producer cannot be built here; blocks every later candidate
    store_why: str = ''  # why the large artefact store is unusable here; '' when it is usable
    provides: Mapping[str, Any] = dataclasses.field(default_factory=dict)
    tables: dict[str, tuple[Table, str]] = dataclasses.field(default_factory=dict)
    work: list[Work] = dataclasses.field(default_factory=list)
    claimed: list[Work] = dataclasses.field(default_factory=list)
    refused: list[str] = dataclasses.field(default_factory=list)
    queue: list[Ranked] = dataclasses.field(default_factory=list)

    def consider(self, item: Ranked) -> None:
        """Assess *item*, claim it when nothing blocks it, and keep it in the queue while it waits."""
        wanted = item.candidate
        if wanted.kind == REQUEST:  # requests are ranked and shown; no producer claims one yet
            self.queue.append(dataclasses.replace(item, blocked=f'{NO_HOST} claims requests yet'))
            return
        state, holder = assess(status_history(self.client, wanted.sha), wanted.platform, me=self.me, now=self.now)
        one = Work(wanted.ref, wanted.sha, wanted.platform, state, holder)
        blocked, needed = self._blocked(wanted) if state in CLAIMABLE else ('', frozenset[str]())
        if state in CLAIMABLE and not blocked and not self.dry_run:
            one, blocked = self._take(one, wanted, needed)
        self.work.append(one)
        if one.state in CLAIMABLE:
            self.queue.append(dataclasses.replace(item, blocked=blocked))

    def reserved(self, wanted: Candidate) -> bool:
        """Whether a live lease on this host is for *wanted*: it then ranks first here."""
        needed = self._needs(wanted) if wanted.sha else frozenset[str]()
        job = self._job(wanted, needed)
        return any(one.holds_for(job, self.supply.scope, self.now) for one in self.reservations)

    def _needs(self, wanted: Candidate) -> frozenset[str]:
        table, _ = self.tables.setdefault(wanted.sha, declared_at(self.root, wanted.sha))
        return frozenset(needs(table, wanted.platform))

    def _job(self, wanted: Candidate, needed: frozenset[str]) -> Job:
        return Job(self.repo, wanted.sha, wanted.platform, needed, wanted.origin, wanted.origin_host, wanted.session)

    def _blocked(self, wanted: Candidate) -> tuple[str, frozenset[str]]:
        """Why *wanted* is not claimed (``''``: it admits), and the resource names it needs."""
        _, refused = self.tables.setdefault(wanted.sha, declared_at(self.root, wanted.sha))
        needed = self._needs(wanted)
        busy = not self.serve.hpc and wanted.sha in self.trees
        why = (
            refused
            or lacking(sorted(needed), self.provides)
            or self.unproducible
            or (f'the tree of {wanted.sha[:12]} is producing another part here' if busy else '')
            or over_budget(self.root, wanted, self.schedule, self.usage)
            or self._admission(wanted, needed)
        )
        return why, needed

    def _admission(self, wanted: Candidate, needed: frozenset[str]) -> str:
        verdict = admit(
            self._job(wanted, needed), self.size(wanted, needed), self.supply,
            reservations=self.reservations, running=self.taken, now=self.now,
        )  # fmt: skip
        return '' if verdict else f'{NOT_ADMITTED}: {verdict.why}'

    def _take(self, one: Work, wanted: Candidate, needed: frozenset[str]) -> tuple[Work, str]:
        try:  # what produces it BEFORE the claim: a part nobody can produce is never claimed
            one = _producer(self.root, one, self.serve)
        except (UndeclaredPart, FileNotFoundError) as why:
            self.refused.append(f'{part_context(one.platform)}: not claimed -- {why}')
            self.unproducible = f'{NO_HOST} can produce it: {why}'
            return one, self.unproducible
        if one.cluster is not None and one.cluster.outputs and self.store_why:
            why = f'its declared outputs could exceed threshold_mb and {self.store_why}'
            self.refused.append(f'{part_context(one.platform)}: not claimed -- {why}')
            return one, why
        one = claim(self.client, one, self.me)
        if one.state == MINE:
            self.claimed.append(one)
            self.taken.append(self.size(wanted, needed))
            self.trees.add(wanted.sha)
        return one, ''


def _producer(root: Path, work: Work, serve: Serving) -> Work:
    if serve.hpc:
        return dataclasses.replace(work, cluster=cluster_part(root, work.sha))
    return dataclasses.replace(work, argv=tuple(part_argv(root, work.platform, scope=FULL, sha=work.sha)))
