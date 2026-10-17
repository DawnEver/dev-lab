"""THE CLAIM PASS of a tick (:mod:`lab_commons.dev.forgetick`): walk the ranked queue, claim each candidate that admits.

Each candidate becomes a :class:`~lab_commons.compute.model.Job` carrying its need-set and its origin
(login, vouched host, session) -- a part's need-set from its name, a REQUEST's from the producer its sha
declares (:mod:`lab_commons.dev.forgerequest`). A job whose OWN commit is defective -- its declaration
refused, a request name it does not declare, or a producer NO host kind can build -- is refused on that
commit's own context once (:func:`lab_commons.dev.forgeclaim.refuse`) and never queued; a table this kit
does not know is the serving host's defect, so that sha waits. Any other job is blocked by this host's
kind lacking its producer, its ref's budget, or admission -- and otherwise
claimed, its demand then counted as running for every later candidate
(:func:`lab_commons.compute.admission.admit`).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from lab_commons.compute.admission import Admission, admit
from lab_commons.compute.model import REQUEST, Candidate, Job, Ranked, Resources, Schedule, Supply
from lab_commons.dev.forgeclaim import CLAIMABLE, MINE, REFUSED_AT_COMMIT, Claim, Serving, Work, assess, claim, refuse
from lab_commons.dev.forgecoalesce import behind
from lab_commons.dev.forgerequest import (
    Declared,
    UndeclaredRequest,
    declared_request,
    request_context,
    unreachable_source,
    unreproducible,
    unserved,
    untrusted,
)
from lab_commons.dev.forgeschedule import NO_HOST, NOT_ADMITTED, over_budget
from lab_commons.dev.forgestatus import Status
from lab_commons.dev.forgework import Client
from lab_commons.dev.platformparts import UndeclaredPart, cluster_part, part_context, producer_argv
from lab_commons.hpc.declared import OutdatedKit
from lab_commons.hpc.needsets import declared_at, needs_of

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
    taken: list[Mapping[str, float]] = dataclasses.field(default_factory=list)  # what runs, then each claim
    store_why: str = ''  # why the large artefact store is unusable here; '' when it is usable
    declarations: dict[str, str] = dataclasses.field(default_factory=dict)  # sha -> why its declaration is refused
    unservable: set[str] = dataclasses.field(default_factory=set)  # keys whose producer this host kind cannot build
    history: Callable[[str], Sequence[Status]] = lambda _sha: ()  # every status of a sha, read once a tick
    work: list[Work] = dataclasses.field(default_factory=list)
    claimed: list[Work] = dataclasses.field(default_factory=list)
    refused: list[str] = dataclasses.field(default_factory=list)
    queue: list[Ranked] = dataclasses.field(default_factory=list)
    pending: list[Work] = dataclasses.field(default_factory=list)  # left open here that this host could serve
    admitted: dict[str, tuple[Job, Admission]] = dataclasses.field(default_factory=dict)
    requests: dict[tuple[str, str], Declared] = dataclasses.field(default_factory=dict)  # (sha, name) -> it
    trunks: tuple[str, ...] = ()  # origin refs whose code runs for any requester (X1)
    authors: frozenset[str] = frozenset()  # whose requests run here at any served sha (X1)
    reached: dict[str, str] = dataclasses.field(default_factory=dict)  # sha -> why a git source is unreachable here

    def consider(self, item: Ranked) -> None:
        """Assess *item*, claim it when nothing blocks it, and keep it in the queue while it waits."""
        wanted = item.candidate
        context = request_context(wanted.number) if wanted.kind == REQUEST else part_context(wanted.platform)
        state, holder = assess(self.history(wanted.sha), context, me=self.me, now=self.now)
        one = Work(wanted.ref, wanted.sha, wanted.platform, state, holder, request=context)
        blocked, needed = '', frozenset[str]()
        if state in CLAIMABLE:
            try:
                one, blocked = self._own(one, wanted)
            except OutdatedKit as why:  # this host's defect: the sha waits for a kit that reads it
                blocked = str(why)
            if blocked.startswith(REFUSED_AT_COMMIT) and not self.dry_run:
                self.work.append(refuse(self.client, one, blocked.removeprefix(REFUSED_AT_COMMIT).strip()))
                return
            if not blocked:
                blocked, needed = self._blocked(wanted)
        if state in CLAIMABLE and not blocked and self.dry_run:
            self._took(wanted, needed)
        elif state in CLAIMABLE and not blocked:
            one, blocked = self._take(one, wanted, needed)
        self.work.append(one)
        if one.state in CLAIMABLE:
            self.queue.append(dataclasses.replace(item, blocked=blocked))
            if wanted.key not in self.unservable and self._servable(wanted):
                self.pending.append(one)

    def _servable(self, wanted: Candidate) -> bool:
        """Whether every need of *wanted* is present on this host (an unreadable request declaration: no)."""
        try:
            return self._needs(wanted) <= self.supply.present
        except (UndeclaredRequest, OutdatedKit):
            return False

    def _declared(self, wanted: Candidate) -> Declared:
        """A request's producer as its sha declares it, read once a tick; raises :class:`UndeclaredRequest`."""
        key = (wanted.sha, wanted.producer, wanted.paths)
        if key not in self.requests:
            self.requests[key] = declared_request(self.root, wanted.sha, wanted.producer, wanted.paths)
        return self.requests[key]

    def _needs(self, wanted: Candidate) -> frozenset[str]:
        """The need-set: a request's as its producer declares it, a part's as its name spells it."""
        return self._declared(wanted).needs if wanted.kind == REQUEST else needs_of(wanted.platform)

    def _job(self, wanted: Candidate, needed: frozenset[str]) -> Job:
        producer = wanted.producer if wanted.kind == REQUEST else wanted.platform
        return Job(self.repo, wanted.sha, producer, needed)

    def _own(self, one: Work, wanted: Candidate) -> tuple[Work, str]:
        """*one* with what produces it here, and why not (``''``: it is producible here).

        The commit's OWN defect is prefixed :data:`REFUSED_AT_COMMIT`: a request name its sha does not declare,
        a part's declaration refused, or neither host kind able to build the part's producer (a box needs
        ``produce``, a cluster ``hpc install``). Only this host's kind lacking it is no such defect: another kind
        serves it. A declaration this kit is too old to read raises :class:`OutdatedKit` for the caller.
        """
        if wanted.kind == REQUEST:
            return self._own_request(one, wanted)
        if one.sha not in self.declarations:
            self.declarations[one.sha] = declared_at(self.root, one.sha)[1]
        if self.declarations[one.sha]:
            return one, f'{REFUSED_AT_COMMIT} {self.declarations[one.sha]}'
        try:
            return _part_producer(self.root, one, hpc=bool(self.serve.hpc)), ''
        except (UndeclaredPart, FileNotFoundError) as here:
            try:
                _part_producer(self.root, one, hpc=not self.serve.hpc)
            except (UndeclaredPart, FileNotFoundError) as there:
                return one, f'{REFUSED_AT_COMMIT} {NO_HOST} can produce {one.context}: {here}; {there}'
            self.unservable.add(wanted.key)
            return one, f'this host cannot produce {one.context}: {here}'

    def _own_request(self, one: Work, wanted: Candidate) -> tuple[Work, str]:
        """A request: refused at its commit when no host could ever reproduce it, waiting while THIS host cannot.

        The commit's own defects -- a sha origin does not serve, an undeclared producer, no lock -- are
        refused on its context. This host's -- a cluster seat, an author it does not run for off the
        trunks, a git source it cannot fetch -- leave it waiting, named, for a host that can.
        """
        why, declared = wanted.refused or unserved(self.root, one.sha), None
        try:
            declared = self._declared(wanted)
        except UndeclaredRequest as undeclared:
            why = why or str(undeclared)
        why = why or unreproducible(self.root, one.sha)
        if why or declared is None:
            return one, f'{REFUSED_AT_COMMIT} {why}'
        if why := self._not_here(one, wanted):
            self.unservable.add(wanted.key)
            return one, why
        return dataclasses.replace(
            one, argv=declared.argv, producer=declared.name, wall_s=round(declared.wall_h * 3600)
        ), ''

    def _not_here(self, one: Work, wanted: Candidate) -> str:
        """Why THIS host does not run the request *one*, ``''`` when it does (its sources probed once a tick)."""
        if self.serve.hpc:
            return f'{NO_HOST} on a cluster seat runs a request'
        if why := untrusted(self.root, one.sha, wanted.origin, trunks=self.trunks, authors=self.authors):
            return why
        if one.sha not in self.reached:
            self.reached[one.sha] = unreachable_source(self.root, one.sha)
        return self.reached[one.sha]

    def _blocked(self, wanted: Candidate) -> tuple[str, frozenset[str]]:
        """Why *wanted* is not claimed (``''``: it admits), and the resource names it needs."""
        needed = self._needs(wanted)
        why = (
            behind(self.root, wanted, self.schedule, self.history, self.now)
            or over_budget(self.root, wanted, self.schedule, self.usage)
            or self._admission(wanted, needed)
        )
        return why, needed

    def _admission(self, wanted: Candidate, needed: frozenset[str]) -> str:
        job = self._job(wanted, needed)
        verdict = admit(job, self.size(wanted, needed), self.supply, running=self.taken)
        self.admitted[wanted.key] = (job, verdict)
        return '' if verdict else f'{NOT_ADMITTED}: {verdict.why}'

    def _took(self, wanted: Candidate, needed: frozenset[str]) -> None:
        """Count *wanted*'s claim as running at its demand."""
        self.taken.append(Resources(self.size(wanted, needed)))

    def _take(self, one: Work, wanted: Candidate, needed: frozenset[str]) -> tuple[Work, str]:
        if one.cluster is not None and one.cluster.outputs and self.store_why:
            why = f'its declared outputs could exceed threshold_mb and {self.store_why}'
            self.refused.append(f'{one.context}: not claimed -- {why}')
            return one, why
        one = claim(self.client, dataclasses.replace(one, demand=self.size(wanted, needed)), self.me)
        if one.state == MINE:
            self.claimed.append(one)
            self._took(wanted, needed)
        return one, ''


def _part_producer(root: Path, work: Work, *, hpc: bool) -> Work:
    """*work* carrying what produces its part: a cluster part on a cluster seat, else the sha's producer argv."""
    if hpc:
        return dataclasses.replace(work, cluster=cluster_part(root, work.sha))
    return dataclasses.replace(work, argv=tuple(producer_argv(root, work.platform, sha=work.sha)))
