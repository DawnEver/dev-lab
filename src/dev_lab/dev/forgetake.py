"""THE CLAIM PASS of a tick (:mod:`dev_lab.dev.forgetick`): walk the ranked queue, claim each candidate that admits.

Each candidate becomes a :class:`~lab_commons.compute.model.Job` carrying its need-set and its origin
(login, vouched host, session) -- a part's need-set from its name, a REQUEST's from the producer its sha
declares (:mod:`dev_lab.dev.forgerequest`). A job whose OWN commit is defective -- its declaration
refused, a request name it does not declare, or a producer NO host kind can build -- is refused on that
commit's own context once (:func:`dev_lab.dev.forgeclaim.refuse`) and never queued; a table this kit
does not know is the serving host's defect, so that sha waits. Any other job is blocked by this host's
kind lacking its producer, its ref's budget, or admission -- and otherwise
claimed, its demand then counted as running for every later candidate
(:func:`lab_commons.resources.admits`).

ON A BOX THE LEDGER DECIDES LAST, AND ONCE: a local part is claimed only after its box claim is TAKEN
(*reserve*, :func:`dev_lab.dev.forgerounds.reserve`) at exactly the demand its producer declares; the
producer adopts that row, so a started part is never refused by the same box a moment later. A part the
ledger refuses posts nothing -- it stays open and waits ``not admitted`` -- so no false ``error`` is published.

ON A BOX A WAIT IS BOUNDED AND SAID (:mod:`dev_lab.dev.forgewait`): a part the box does not admit is told its
outlook -- larger than the box (``never fits``, kept in :attr:`ClaimPass.unfit` for the tick to answer), its
earliest start and the claims that end first, or no start while the room is used outside the ledger -- and a
part with a start is PROTECTED: a lower-ranked one is claimed past it only when that does not delay its start
(:meth:`~dev_lab.dev.forgewait.Box.delays`, the ledger's backfill rule), so a stream of small parts never
starves a large one.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from lab_commons.box import Claim as BoxClaim
from lab_commons.box import release
from lab_commons.compute.admission import Admission
from lab_commons.compute.learned import BOX_WALL_S
from lab_commons.compute.model import REQUEST, Candidate, Job, Ranked, Resources, Schedule, Supply
from lab_commons.compute.serves import Serves
from lab_commons.hpc.declared import OutdatedKit
from lab_commons.hpc.needsets import declared_at, needs_of
from lab_commons.resources import admits

from dev_lab.dev.forgecarry import docs_only, part_standing
from dev_lab.dev.forgeclaim import (
    CLAIMABLE,
    DONE,
    MINE,
    REFUSED_AT_COMMIT,
    Claim,
    Serving,
    Work,
    assess,
    claim,
    refuse,
)
from dev_lab.dev.forgecoalesce import behind
from dev_lab.dev.forgerequest import (
    Declared,
    UndeclaredRequest,
    declared_request,
    request_context,
    unreachable_source,
    unreproducible,
    unserved,
    untrusted,
)
from dev_lab.dev.forgeschedule import NO_HOST, NOT_ADMITTED, held, over_budget
from dev_lab.dev.forgestatus import CommitStatus
from dev_lab.dev.forgewait import Box, Outlook
from dev_lab.dev.forgework import Client
from dev_lab.dev.platformparts import UndeclaredPart, cluster_part, part_context, producer_argv

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
    history: Callable[[str], Sequence[CommitStatus]] = lambda _sha: ()  # every status of a sha, read once a tick
    work: list[Work] = dataclasses.field(default_factory=list)
    claimed: list[Work] = dataclasses.field(default_factory=list)
    refused: list[str] = dataclasses.field(default_factory=list)
    queue: list[Ranked] = dataclasses.field(default_factory=list)
    pending: list[Work] = dataclasses.field(default_factory=list)  # left open here that this host could claim
    admitted: dict[str, tuple[Job, Admission]] = dataclasses.field(default_factory=dict)
    requests: dict[tuple[str, str], Declared] = dataclasses.field(default_factory=dict)  # (sha, name) -> it
    trunks: tuple[str, ...] = ()  # origin refs whose code runs for any requester (X1)
    authors: frozenset[str] = frozenset()  # whose requests run here at any served sha (X1)
    reached: dict[str, str] = dataclasses.field(default_factory=dict)  # sha -> why a git source is unreachable here
    serves: Serves = dataclasses.field(default_factory=Serves)  # [serve] parts: a skipped part waits for another host
    #: Takes a LOCAL part's box claim before it is claimed: its ledger row, or why the box refused (None: no box).
    reserve: Callable[[Work], int | str] | None = None
    #: This box as the pass sees it (None: a cluster seat): what tells a waiting part its outlook and protects it.
    box: Box | None = None
    ahead: list[tuple[str, Mapping[str, float]]] = dataclasses.field(default_factory=list)  # (key, demand) to protect
    over: dict[str, tuple[Candidate, Mapping[str, float], Outlook]] = dataclasses.field(default_factory=dict)

    @property
    def unfit(self) -> dict[str, tuple[Work, Mapping[str, float], Outlook]]:
        """Every open part larger than this box: its work, its demand and its outlook, by candidate key."""
        works = {(one.sha, one.platform): one for one in self.work if one.state in CLAIMABLE}
        return {
            key: (works[wanted.sha, wanted.platform], demand, seen)
            for key, (wanted, demand, seen) in self.over.items()
            if (wanted.sha, wanted.platform) in works
        }

    def consider(self, item: Ranked) -> None:
        """Assess *item*, claim it when nothing blocks it, and keep it in the queue while it waits."""
        wanted = item.candidate
        context = request_context(wanted.number) if wanted.kind == REQUEST else part_context(wanted.platform)
        state, holder = assess(self.history(wanted.sha), context, me=self.me, now=self.now)
        one = Work(wanted.ref, wanted.sha, wanted.platform, state, holder, request=context)
        blocked, needed = '', frozenset[str]()
        if state in CLAIMABLE and wanted.kind != REQUEST:  # DOCS-ONLY-CARRIES: no claim, no run
            one, blocked = self._carried(one, context)
        if one.state in CLAIMABLE and not blocked:
            try:
                one, blocked = self._own(one, wanted)
            except OutdatedKit as why:  # this host's defect: the sha waits for a kit that reads it
                blocked = str(why)
            if blocked.startswith(REFUSED_AT_COMMIT) and not self.dry_run:
                self.work.append(refuse(self.client, one, blocked.removeprefix(REFUSED_AT_COMMIT).strip()))
                return
            if not blocked:
                blocked, needed = self._blocked(wanted)
        if one.state in CLAIMABLE and not blocked and self.dry_run:
            self._took(wanted, needed)
        elif one.state in CLAIMABLE and not blocked:
            one, blocked = self._take(one, wanted, needed)
        self.work.append(one)
        if one.state in CLAIMABLE:
            self.queue.append(dataclasses.replace(item, blocked=blocked))
            skipped = wanted.kind != REQUEST and self.serves.skips(needs_of(wanted.platform))
            if not held(blocked) and not skipped and wanted.key not in self.unservable and self._servable(wanted):
                self.pending.append(one)

    def _carried(self, one: Work, context: str) -> tuple[Work, str]:
        """DOCS-ONLY-CARRIES: *one* and why it is never claimed (``''``: it runs itself).

        A settled source's verdict is posted on *one* (outside a dry run), which comes back settled (``DONE``).
        """
        carry = docs_only(self.root, one.sha, part_standing(self.history, context, self.now))
        if carry is None:
            return one, ''
        if carry.verdict is not None and not self.dry_run:
            carry.post(self.client, one.sha, one.platform)
            one = dataclasses.replace(one, state=DONE)
        return one, carry.hold

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
            (self.serves.skips(needed) if wanted.kind != REQUEST else '')
            or behind(self.root, wanted, self.schedule, self.history, self.now)
            or over_budget(self.root, wanted, self.schedule, self.usage)
            or self._admission(wanted, needed)
        )
        return why, needed

    def _admission(self, wanted: Candidate, needed: frozenset[str]) -> str:
        job, demand = self._job(wanted, needed), self.size(wanted, needed)
        verdict = admits(
            self.supply.resources, demand, present=self.supply.present, needs=job.needs, running=self.taken,
            what=job.producer,
        )  # fmt: skip
        self.admitted[wanted.key] = (job, verdict)
        if verdict:
            return self._behind(wanted, demand)
        if self.box is None:
            return f'{NOT_ADMITTED}: {verdict.why}'
        seen = self.box.outlook(demand)
        if seen.over:
            self.over[wanted.key] = (wanted, demand, seen)
        elif not math.isinf(seen.start):
            self.ahead.append((wanted.key, demand))
        return f'{NOT_ADMITTED}: {verdict.why}; {seen.text(self.box.now)}'

    def _wall_s(self, wanted: Candidate) -> int:
        """How long *wanted*'s box claim holds: a request's declared wall, else a part's day."""
        return round(self._declared(wanted).wall_h * 3600) if wanted.kind == REQUEST else BOX_WALL_S

    def _behind(self, wanted: Candidate, demand: Mapping[str, float]) -> str:
        """Why *wanted*, admitted, still waits: claiming it would delay a higher-ranked part's start (``''``: never)."""
        if self.box is None or not self.ahead:
            return ''
        wall_s = self._wall_s(wanted)
        for key, ahead in self.ahead:
            if self.box.delays(ahead, demand, wall_s):
                return f'{NOT_ADMITTED}: queued behind {key}, which ranks first: claiming this would delay its start'
        return ''

    def _took(self, wanted: Candidate, needed: frozenset[str]) -> None:
        """Count *wanted*'s claim as running at its demand -- in the box's view too, until its wall."""
        demand = self.size(wanted, needed)
        self.taken.append(Resources(demand))
        if self.box is not None:
            self.box.hold(demand, self._wall_s(wanted))

    def _take(self, one: Work, wanted: Candidate, needed: frozenset[str]) -> tuple[Work, str]:
        if one.cluster is not None and one.cluster.outputs and self.store_why:
            why = f'its declared outputs could exceed threshold_mb and {self.store_why}'
            self.refused.append(f'{one.context}: not claimed -- {why}')
            return one, why
        one = dataclasses.replace(one, demand=self.size(wanted, needed))
        if self.reserve is not None and one.cluster is None:
            held = self.reserve(one)  # the box's one ledger decides BEFORE anything is posted on the part
            if isinstance(held, str):
                return one, f'{NOT_ADMITTED}: the box ledger refused it -- {held}'
            one = dataclasses.replace(one, box=held)
        try:
            one = claim(self.client, one, self.me)
        except BaseException:
            if one.box:
                release(BoxClaim(one.box, 0.0))
            raise
        if one.state == MINE:
            self.claimed.append(one)
            self._took(wanted, needed)
        elif one.box:
            release(BoxClaim(one.box, 0.0))  # another host holds the part: its box claim is not ours to keep
        return one, ''


def _part_producer(root: Path, work: Work, *, hpc: bool) -> Work:
    """*work* carrying what produces its part: a cluster part on a cluster seat, else the sha's producer argv."""
    if hpc:
        return dataclasses.replace(work, cluster=cluster_part(root, work.sha))
    return dataclasses.replace(work, argv=tuple(producer_argv(root, work.platform, sha=work.sha)))
