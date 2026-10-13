"""THE CLAIM PASS of a tick (:mod:`lab_commons.dev.forgetick`): walk the ranked queue, claim each candidate that admits.

Each candidate becomes a :class:`~lab_commons.compute.model.Job` carrying its need-set and its origin
(login, vouched host, session) -- a part's need-set from its name, a REQUEST's from the producer its sha
declares (:mod:`lab_commons.dev.forgerequest`; an undeclared name is refused, never run). It is blocked
by a refused declaration, a producer its sha cannot build, its sha's tree being busy here, its ref's
budget, or admission -- and otherwise claimed, its demand then counted as running for every later
candidate -- ON LOAN from a reservation when it borrows one's idle part, and DISPLACING the loans it
preempts when it holds one (:func:`lab_commons.compute.admission.admit`); those loans are collected
in :attr:`ClaimPass.preempt` for the serve loop to stop and release.
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
from lab_commons.dev.forgeclaim import CLAIMABLE, MINE, Claim, Serving, Work, assess, claim
from lab_commons.dev.forgerequest import Declared, UndeclaredRequest, declared_request, request_context
from lab_commons.dev.forgeschedule import NO_HOST, NOT_ADMITTED, over_budget
from lab_commons.dev.forgestatus import Status
from lab_commons.dev.forgework import Client
from lab_commons.dev.platformparts import UndeclaredPart, cluster_part, part_context, producer_argv
from lab_commons.hpc.needsets import Vocabulary, declared_at, needs_of

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
    unproducible: dict[str, str] = dataclasses.field(default_factory=dict)  # sha -> why its producer cannot be built
    store_why: str = ''  # why the large artefact store is unusable here; '' when it is usable
    tables: dict[str, tuple[Vocabulary, str]] = dataclasses.field(default_factory=dict)
    history: Callable[[str], Sequence[Status]] = lambda _sha: ()  # every status of a sha, read once a tick
    work: list[Work] = dataclasses.field(default_factory=list)
    claimed: list[Work] = dataclasses.field(default_factory=list)
    refused: list[str] = dataclasses.field(default_factory=list)
    queue: list[Ranked] = dataclasses.field(default_factory=list)
    preempt: list[Held] = dataclasses.field(default_factory=list)  # loans a holder's claim here displaces
    admitted: dict[str, tuple[Job, Admission]] = dataclasses.field(default_factory=dict)
    requests: dict[tuple[str, str], Declared] = dataclasses.field(default_factory=dict)  # (sha, name) -> it

    def consider(self, item: Ranked) -> None:
        """Assess *item*, claim it when nothing blocks it, and keep it in the queue while it waits."""
        wanted = item.candidate
        context = request_context(wanted.number) if wanted.kind == REQUEST else part_context(wanted.platform)
        if wanted.kind == REQUEST:
            try:  # the producer BEFORE anything else: an undeclared name is refused, never run
                self._declared(wanted)
            except UndeclaredRequest as why:
                self.refused.append(f'{context}: not claimed -- {why}')
                self.queue.append(dataclasses.replace(item, blocked=str(why)))
                return
        state, holder = assess(self.history(wanted.sha), context, me=self.me, now=self.now)
        one = Work(wanted.ref, wanted.sha, wanted.platform, state, holder, context=context)
        blocked, needed = self._blocked(wanted) if state in CLAIMABLE else ('', frozenset[str]())
        if state in CLAIMABLE and not blocked and self.dry_run:
            self._took(wanted, needed)
        elif state in CLAIMABLE and not blocked:
            one, blocked = self._take(one, wanted, needed)
        self.work.append(one)
        if one.state in CLAIMABLE:
            self.queue.append(dataclasses.replace(item, blocked=blocked))

    def reserved(self, wanted: Candidate) -> bool:
        """Whether a live lease on this host is for *wanted*: it then ranks first here."""
        try:
            job = self._job(wanted, self._needs(wanted))
        except (UndeclaredRequest, ValueError):  # refused by name when it is considered
            return False
        return any(one.holds_for(job, self.supply.scope, self.now) for one in self.reservations)

    def _declared(self, wanted: Candidate) -> Declared:
        """A request's producer as its sha declares it, read once a tick; raises :class:`UndeclaredRequest`."""
        key = (wanted.sha, wanted.producer)
        if key not in self.requests:
            self.requests[key] = declared_request(self.root, wanted.sha, wanted.producer)
        return self.requests[key]

    def _needs(self, wanted: Candidate) -> frozenset[str]:
        """The need-set: a request's as its producer declares it, a part's as its name spells it."""
        return self._declared(wanted).needs if wanted.kind == REQUEST else needs_of(wanted.platform)

    def _job(self, wanted: Candidate, needed: frozenset[str]) -> Job:
        producer = wanted.producer if wanted.kind == REQUEST else wanted.platform
        return Job(self.repo, wanted.sha, producer, needed, wanted.origin, wanted.origin_host, wanted.session)

    def _blocked(self, wanted: Candidate) -> tuple[str, frozenset[str]]:
        """Why *wanted* is not claimed (``''``: it admits), and the resource names it needs."""
        needed = self._needs(wanted)
        busy = not self.serve.hpc and wanted.sha in self.trees
        if wanted.kind == REQUEST:  # its producer is declared (considered first); it runs in a local tree
            refused = f'{NO_HOST} on a cluster seat runs a request' if self.serve.hpc else ''
        else:
            _, refused = self.tables.setdefault(wanted.sha, declared_at(self.root, wanted.sha))
            refused = refused or self.unproducible.get(wanted.sha, '')
        why = (
            refused
            or (f'the tree of {wanted.sha[:12]} is producing another part here' if busy else '')
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
        self.admitted[wanted.key] = (job, verdict)
        return '' if verdict else f'{NOT_ADMITTED}: {verdict.why}'

    def _took(self, wanted: Candidate, needed: frozenset[str]) -> Admission:
        """Count *wanted*'s claim as running -- on loan, or displacing the loans it preempts -- and say how."""
        job, verdict = self.admitted[wanted.key]
        self.preempt += verdict.preempt
        self.taken = [one for one in self.taken if one not in verdict.preempt]
        self.taken.append(Held(Resources(self.size(wanted, needed)), job, verdict.on_loan, self.now))
        return verdict

    def _take(self, one: Work, wanted: Candidate, needed: frozenset[str]) -> tuple[Work, str]:
        try:  # what produces it BEFORE the claim: a job nobody can produce is never claimed
            one = self._producer(one, wanted)
        except (UndeclaredPart, FileNotFoundError) as why:
            self.refused.append(f'{one.context}: not claimed -- {why}')
            self.unproducible[wanted.sha] = f'{NO_HOST} can produce it: {why}'
            return one, self.unproducible[wanted.sha]
        if one.cluster is not None and one.cluster.outputs and self.store_why:
            why = f'its declared outputs could exceed threshold_mb and {self.store_why}'
            self.refused.append(f'{one.context}: not claimed -- {why}')
            return one, why
        _, verdict = self.admitted[wanted.key]
        one = claim(self.client, one, dataclasses.replace(self.me, on_loan=verdict.on_loan))
        if one.state == MINE:
            self.claimed.append(one)
            self._took(wanted, needed)
            self.trees.add(wanted.sha)
        return one, ''

    def _producer(self, work: Work, wanted: Candidate) -> Work:
        """*work* carrying what produces it: a request's declared argv, a cluster part, or a part's producer."""
        if wanted.kind == REQUEST:  # run in a tree at its sha by that tree's python, like a local part
            return dataclasses.replace(work, argv=self._declared(wanted).argv)
        if self.serve.hpc:
            return dataclasses.replace(work, cluster=cluster_part(self.root, work.sha))
        return dataclasses.replace(work, argv=tuple(producer_argv(self.root, work.platform, sha=work.sha)))
