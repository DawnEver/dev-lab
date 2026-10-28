"""SERVE'S ROUNDS -- claim while producing: admit, claim, start, wait; again while a local producer lives.

Extracted from :mod:`dev_lab.dev.forgeserve` (its module docstring states the sequence). A round reads
what this host admits against NOW (:func:`supply_now`: a cluster's standing, else what the box ledger can
still admit -- every producer this serve started and every interactive run is a claim on it already), runs
:func:`dev_lab.dev.forgetick.tick` with each cluster run in flight as running demand, and starts a producer
thread for each local part it claimed (:class:`Producing`,
each one :func:`dev_lab.dev.forgeproduce.produce`). The next round comes one tick period later or when a
producer ends; none comes after a producer was STOPPED on purpose (:mod:`dev_lab.dev.stoprun`). Every
producer thread is joined before the rounds return or raise.
"""

from __future__ import annotations

import dataclasses
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from lab_commons.box import Capacity, Holding, Refused, take
from lab_commons.box.ledger import Read
from lab_commons.box.providers import box_engine
from lab_commons.box.supply import Reading
from lab_commons.compute.model import Demand, Supply
from lab_commons.compute.presence import cached
from lab_commons.hpc.account import ClusterAccount
from lab_commons.hpc.needsets import needs_of

from dev_lab.dev import forgerun, forgerunstate
from dev_lab.dev.forgealarm import AUTH, Alarm
from dev_lab.dev.forgeclaim import Work
from dev_lab.dev.forgefleet import watch as fleet_watch
from dev_lab.dev.forgehosts import HostCard, card_host, publish_card
from dev_lab.dev.forgeproduce import Produced, box_claim
from dev_lab.dev.forgetick import TickReport, tick
from dev_lab.dev.forgewait import Box
from dev_lab.dev.forgework import ForgeCallFailed

__all__ = ['Producing', 'Rounds', 'box_now', 'locked_fetch', 'reserve', 'supply_now']


def locked_fetch(fetch: Callable[[Path], None]) -> Callable[[Path], None]:
    """*fetch*, one call at a time: two fetches into one repository race on its refs."""
    lock = threading.Lock()

    def fetched(here: Path) -> None:
        with lock:
            fetch(here)

    return fetched


@dataclass
class Rounds:
    """Serve's ROUNDS (the module docstring): admit and claim, start what was claimed, wait; while a producer lives.

    *ticking* and *carding* are the keywords every :func:`~dev_lab.dev.forgetick.tick` and every host card
    share; *supplied* is :func:`supply_now` with its host bound, *holding* the box ledger's claims now (none on a
    cluster); *runs* the cluster runs here, each NOT YET SUBMITTED one running at *sized* of its need-set -- a
    submitted one's tasks are already held in the cluster's standing, and counting them twice starved the queue.
    *room* is this box as a round's pass sees it (:func:`box_now`; ``None`` on a cluster), *cards* every host card.
    """

    root: Path
    repo: str
    alarm: Callable[[Alarm], object]
    runs: list[forgerunstate.Run]
    slurm: forgerunstate.Cluster | None
    say: Callable[[str], None]
    sized: Callable[[frozenset[str]], Demand]
    supplied: Callable[[Sequence[Holding]], Supply]
    holding: Callable[[], Sequence[Holding]]
    ticking: Mapping[str, Any]
    carding: Mapping[str, Any]
    produce: Callable[..., Produced]
    latest: dict[str, Any] = dataclasses.field(default_factory=dict)  # the last round: what the card shows
    room: Callable[[Sequence[Holding]], Box | None] = lambda _held: None
    cards: Sequence[HostCard] = ()

    def __post_init__(self) -> None:
        """The producers, publishing this host's card at every beat."""
        self.producing = Producing(self.produce, card=self.card)

    def serve(self, beat_s: float) -> tuple[list[TickReport], list[Produced]]:
        """A round, then one per *beat_s* or per producer that ended, until none lives or one was stopped.

        Every producer is joined before this returns or raises. A platform none of *cards* serves alarms first
        (:func:`dev_lab.dev.forgefleet.watch`).
        """
        fleet_watch(self.cards, datetime.now(UTC), alarm=self.alarm, repo=self.repo)  # a platform with no live host
        rounds: list[TickReport] = []
        try:
            rounds.append(self.one())
            while self.producing.wait(beat_s) and not self.producing.stopped():
                rounds.append(self.one())
        finally:
            produced = self.producing.join()
        return rounds, produced

    def one(self) -> TickReport:
        """One round: what this host admits against now, the tick, and a start for everything it claimed."""
        held = tuple(self.holding())
        supply = self.supplied(held)
        # a run Slurm holds is in the standing already (every pending and running task): only an unsubmitted one is not
        unsubmitted = (forgerunstate.CLAIMED_PHASE, forgerunstate.SUBMITTING)
        running = [self.sized(needs_of(run.platform)) for run in self.runs if run.phase in unsubmitted]
        box = self.room(held)
        ticked = _tick(
            self.repo, self.root, self.alarm, **self.ticking,
            supply=supply, running=running, box=box, cards=self.cards,
        )  # fmt: skip
        self.latest.update(ticked=ticked, supply=supply, held=held, box=box)
        for line in ticked.lines:
            self.say(line)
        local = [item for item in ticked.claimed if item.cluster is None or item.holder is None]
        self.runs += [forgerun.start(item, item.holder) for item in ticked.claimed if item not in local and item.holder]
        for item in local:
            self.producing.start(item)
        return ticked

    def card(self, claimed: Sequence[Work], progress: Mapping[tuple[str, str], str] | None = None) -> None:
        """Publish this host's card: *claimed* with their *progress*, and the last round's queue and supply."""
        ticked = self.latest['ticked']
        publish_card(
            self.root, ticked.queue, claimed, **self.carding, artefacts=ticked.artefacts,
            supply=self.latest['supply'], progress=progress,
            size=self.latest['box'].size() if self.latest.get('box') else {},
            running=(*(f'{run.sha[:12]} {run.platform}' for run in self.runs),
                     *(f'{one.what} (pid {one.pid})' for one in self.latest['held'])),
        )  # fmt: skip


def supply_now(
    held: Sequence[Holding],
    *,
    name: str,
    standing: forgerunstate.Standing | None,
    capacity: Callable[[], Capacity] = Capacity.read,
    read: Read = Reading.now,
) -> Supply:
    """What this round admits against: the cluster standing, else what lies outside the box ledger's claims.

    The box's providers read the ledger themselves (:func:`lab_commons.box.providers.box_engine`), so *held* -- the
    round's own read of it -- is not read twice.
    """
    del held
    if standing is not None:
        return dataclasses.replace(standing.supply, scope=name)
    available = box_engine(capacity=capacity(), read=read, presence=cached()).available('box')
    return dataclasses.replace(available, scope=name)


def box_now(
    held: Sequence[Holding],
    *,
    capacity: Callable[[], Capacity] = Capacity.read,
    read: Read = Reading.now,
    clock: Callable[[], float] = time.time,
) -> Box:
    """The box as a round's claim pass sees it: its size, the ledger's claims *held*, the OS, the clock."""
    return Box(capacity(), list(held), read, clock())


def reserve(
    item: Work, *, root: Path, capacity: Callable[[], Capacity] = Capacity.read, read: Read = Reading.now
) -> int | str:
    """TAKE *item*'s box claim now, at exactly what its producer declares: its ledger row.

    The demand is :func:`~dev_lab.dev.forgeproduce.box_claim`'s. The tick calls this before it claims the
    part and the producer's box run adopts the row, so the one admission is the tick's. A box with no room
    returns why (nothing held, nothing to post).
    """
    size = capacity()
    try:
        held = take(box_claim(item, size, root=root), item.wall_s, f'{item.context}@{item.sha[:12]}', key=item.context,
                    capacity=size, read=read)  # fmt: skip
    except Refused as refused:
        return str(refused)
    return held.id


def _tick(repo: str, root: Path, alarm: Callable[[Alarm], object], **kwargs: object) -> TickReport:
    """One :func:`~dev_lab.dev.forgetick.tick`; the forge refusing the stored credential alarms before it raises."""
    try:
        return tick(root, **kwargs)
    except ForgeCallFailed as failed:
        if failed.credential_refused:
            seat = kwargs.get('seat')
            host = card_host(str(kwargs.get('machine') or ''), seat if isinstance(seat, ClusterAccount) else None)
            alarm(Alarm(AUTH, repo, f'the forge refused the stored credential on {host}', str(failed)))
        raise


class Producing:
    """The local producers this serve runs, one thread each (the module docstring): started, measured, joined.

    *produce* is :func:`dev_lab.dev.forgeproduce.produce` with everything but the part bound; each call
    is given its own *beat* (publishing the card with EVERY live part's progress). Results are kept in start
    order.
    """

    def __init__(self, produce: Callable[..., Produced], *, card: Callable[..., None]) -> None:
        """Nothing started yet; *card* publishes the host card with every live part."""
        self._produce, self._card = produce, card
        self._lock = threading.Condition()
        self._threads: list[threading.Thread] = []
        self._order: list[Work] = []
        self._live: dict[tuple[str, str], Work] = {}
        self._progress: dict[tuple[str, str], str] = {}
        self._done: dict[tuple[str, str], Produced] = {}
        self._failed: list[BaseException] = []

    def start(self, item: Work) -> None:
        """Produce *item* in a thread of its own."""
        with self._lock:
            self._order.append(item)
            self._live[item.sha, item.platform] = item
        thread = threading.Thread(target=self._one, args=(item,), name=f'produce-{item.platform}-{item.sha[:12]}')
        self._threads.append(thread)
        thread.start()

    def _one(self, item: Work) -> None:
        key = (item.sha, item.platform)

        def beat(elapsed: timedelta) -> None:
            with self._lock:  # one publisher at a time, and the card names every live part
                self._progress[key] = f'producing {elapsed.total_seconds() // 60:.0f}m'
                self._card(list(self._live.values()), progress=dict(self._progress))

        produced: Produced | None = None
        try:
            produced = self._produce(item, beat=beat)
        finally:  # a producer that raised hands its exception to join, which raises it in serve's own thread
            with self._lock:
                if produced is None:
                    self._failed.append(sys.exception() or RuntimeError(f'the producer of {key} ended without a part'))
                else:
                    self._done[key] = produced
                self._live.pop(key, None)
                self._progress.pop(key, None)
                self._lock.notify_all()

    def stopped(self) -> bool:
        """Whether a producer was stopped on purpose (:mod:`dev_lab.dev.stoprun`)."""
        with self._lock:
            return any(one.stopped for one in self._done.values())

    def wait(self, timeout_s: float) -> bool:
        """Wait until a producer ends or *timeout_s* passes; whether to go on claiming (one lives, none raised)."""
        with self._lock:
            ended = len(self._done) + len(self._failed)
            self._lock.wait_for(lambda: len(self._done) + len(self._failed) > ended or not self._live, timeout_s)
            return bool(self._live) and not self._failed

    def join(self) -> list[Produced]:
        """Wait for every producer; what each produced, in start order. A producer that raised raises here."""
        for thread in self._threads:
            thread.join()
        if self._failed:
            raise self._failed[0]
        return [self._done[item.sha, item.platform] for item in self._order]
