"""THE CLAIM PASS of a tick (:mod:`lab_commons.dev.forgetick`): walk the ranked queue, claim each candidate that admits.

A candidate whose OWN commit is defective -- its declaration refused, or a producer it cannot build -- is
no candidate: it is refused on that commit once (:func:`lab_commons.dev.forgeclaim.refuse`) and never queued.
A table this kit does not know is NOT such a defect -- the serving kit is older -- so that sha waits here.
Every other candidate becomes a :class:`~lab_commons.compute.model.Job` carrying its need-set and its
origin (login, vouched host, session); it is blocked by its sha's tree being busy here, its ref's budget, or
admission -- and otherwise claimed, its demand then counted as
running for every later candidate -- ON LOAN from a reservation when it borrows one's idle part, and
DISPLACING the loans it preempts when it holds one (:func:`lab_commons.compute.admission.admit`); those loans
are collected in :attr:`ClaimPass.preempt` for the serve loop to stop and release.
:meth:`ClaimPass.reserved` is what ranks a lease holder's job first.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from lab_commons.compute.admission import Admission, Held, admit
from lab_commons.compute.model import REQUEST, Candidate, Job, Ranked, Reservation, Resources, Schedule, Supply
from lab_commons.dev.forgeclaim import CLAIMABLE, MINE, REFUSED_AT_COMMIT, Claim, Serving, Work, assess, claim, refuse
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
    reservations: tuple[Reservation, ...] = ()
    taken: list[Held] = dataclasses.field(default_factory=list)  # what runs, then each claim
    trees: set[str] = dataclasses.field(default_factory=set)  # the shas a local claim of this tick holds
    store_why: str = ''  # why the large artefact store is unusable here; '' when it is usable
    declarations: dict[str, str] = dataclasses.field(default_factory=dict)  # sha -> why its declaration is refused
    unservable: set[tuple[str, str]] = dataclasses.field(default_factory=set)  # (sha, part) this host kind cannot build
    history: Callable[[str], Sequence[Status]] = lambda _sha: ()  # every status of a sha, read once a tick
    work: list[Work] = dataclasses.field(default_factory=list)
    claimed: list[Work] = dataclasses.field(default_factory=list)
    refused: list[str] = dataclasses.field(default_factory=list)
    queue: list[Ranked] = dataclasses.field(default_factory=list)
    pending: list[Work] = dataclasses.field(default_factory=list)  # left open here that this host could serve
    preempt: list[Held] = dataclasses.field(default_factory=list)  # loans a holder's claim here displaces
    admitted: dict[tuple[str, str], tuple[Job, Admission]] = dataclasses.field(default_factory=dict)

    def consider(self, item: Ranked) -> None:
        """Assess *item*, claim it when nothing blocks it, and keep it in the queue while it waits."""
        wanted = item.candidate
        if wanted.kind == REQUEST:  # requests are ranked and shown; no producer claims one yet
            self.queue.append(dataclasses.replace(item, blocked=f'{NO_HOST} claims requests yet'))
            return
        state, holder = assess(self.history(wanted.sha), wanted.platform, me=self.me, now=self.now)
        one = Work(wanted.ref, wanted.sha, wanted.platform, state, holder)
        blocked, needed = '', frozenset[str]()
        if state in CLAIMABLE:
            try:
                one, blocked = self._own(one)
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
            if needs_of(wanted.platform) <= self.supply.present and (one.sha, one.platform) not in self.unservable:
                self.pending.append(one)

    def reserved(self, wanted: Candidate) -> bool:
        """Whether a live lease on this host is for *wanted*: it then ranks first here."""
        job = self._job(wanted, needs_of(wanted.platform))
        return any(one.holds_for(job, self.supply.scope, self.now) for one in self.reservations)

    def _job(self, wanted: Candidate, needed: frozenset[str]) -> Job:
        return Job(self.repo, wanted.sha, wanted.platform, needed, wanted.origin, wanted.origin_host, wanted.session)

    def _own(self, one: Work) -> tuple[Work, str]:
        """*one* with what produces it here, and why not (``''``: it is producible here).

        The commit's OWN defect is prefixed :data:`REFUSED_AT_COMMIT`: its declaration refused, or neither host
        kind can build its producer (a box needs ``produce``, a cluster ``hpc install``). Only this host's kind
        lacking its producer is no such defect -- another kind serves it. A declaration this kit is too old to
        read is this host's defect: :class:`OutdatedKit` is raised for the caller.
        """
        if one.sha not in self.declarations:
            self.declarations[one.sha] = declared_at(self.root, one.sha)[1]
        if self.declarations[one.sha]:
            return one, f'{REFUSED_AT_COMMIT} {self.declarations[one.sha]}'
        try:
            return _producer(self.root, one, self.serve), ''
        except (UndeclaredPart, FileNotFoundError) as here:
            other = dataclasses.replace(self.serve, hpc='' if self.serve.hpc else 'any')
            try:
                _producer(self.root, one, other)
            except (UndeclaredPart, FileNotFoundError) as there:
                return one, f'{REFUSED_AT_COMMIT} {NO_HOST} can produce {part_context(one.platform)}: {here}; {there}'
            self.unservable.add((one.sha, one.platform))
            return one, f'this host cannot produce {part_context(one.platform)}: {here}'

    def _blocked(self, wanted: Candidate) -> tuple[str, frozenset[str]]:
        """Why *wanted* is not claimed (``''``: it admits), and the resource names it needs."""
        needed = needs_of(wanted.platform)
        busy = not self.serve.hpc and wanted.sha in self.trees
        why = (
            (f'the tree of {wanted.sha[:12]} is producing another part here' if busy else '')
            or over_budget(self.root, wanted, self.schedule, self.usage)
            or self._admission(wanted, needed)
        )
        return why, needed

    def _admission(self, wanted: Candidate, needed: frozenset[str]) -> str:
        job = self._job(wanted, needed)
        verdict = admit(
            job,
            self.size(wanted, needed),
            self.supply,
            reservations=self.reservations,
            running=self.taken,
            now=self.now,
        )
        self.admitted[wanted.sha, wanted.platform] = (job, verdict)
        return '' if verdict else f'{NOT_ADMITTED}: {verdict.why}'

    def _took(self, wanted: Candidate, needed: frozenset[str]) -> Admission:
        """Count *wanted*'s claim as running -- on loan, or displacing the loans it preempts -- and say how."""
        job, verdict = self.admitted[wanted.sha, wanted.platform]
        self.preempt += verdict.preempt
        self.taken = [one for one in self.taken if one not in verdict.preempt]
        self.taken.append(Held(Resources(self.size(wanted, needed)), job, verdict.on_loan, self.now))
        return verdict

    def _take(self, one: Work, wanted: Candidate, needed: frozenset[str]) -> tuple[Work, str]:
        if one.cluster is not None and one.cluster.outputs and self.store_why:
            why = f'its declared outputs could exceed threshold_mb and {self.store_why}'
            self.refused.append(f'{part_context(one.platform)}: not claimed -- {why}')
            return one, why
        _, verdict = self.admitted[wanted.sha, wanted.platform]
        one = claim(self.client, one, dataclasses.replace(self.me, on_loan=verdict.on_loan))
        if one.state == MINE:
            self.claimed.append(one)
            self._took(wanted, needed)
            self.trees.add(wanted.sha)
        return one, ''


def _producer(root: Path, work: Work, serve: Serving) -> Work:
    if serve.hpc:
        return dataclasses.replace(work, cluster=cluster_part(root, work.sha))
    return dataclasses.replace(work, argv=tuple(producer_argv(root, work.platform, sha=work.sha)))
