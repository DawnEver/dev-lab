"""SERVE'S ROUNDS -- claim while producing: admit, claim, start, wait; again while a local producer lives.

Extracted from :mod:`lab_commons.dev.forgeserve` (its module docstring states the sequence). A round reads
what this host admits against NOW (:func:`supply_now`: a cluster's standing, else what the box ledger can
still admit -- every producer this serve started and every interactive run is a claim on it already), runs
:func:`lab_commons.dev.forgetick.tick` with each cluster run in flight as running demand and every live
producer's sha as busy, and starts a producer thread for each local part it claimed (:class:`Producing`,
each one :func:`lab_commons.dev.forgeproduce.produce`). The next round comes one tick period later or when a
producer ends; none comes after a producer was STOPPED on purpose (:mod:`lab_commons.dev.stoprun`). Every
producer thread is joined before the rounds return or raise.
"""

from __future__ import annotations

import dataclasses
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from lab_commons.box import Capacity, Holding
from lab_commons.compute import probe
from lab_commons.compute.model import Demand, Supply
from lab_commons.dev import forge as _forge
from lab_commons.dev import forgerun
from lab_commons.dev.forgealarm import AUTH, Alarm
from lab_commons.dev.forgeclaim import Work
from lab_commons.dev.forgehosts import publish_card
from lab_commons.dev.forgeproduce import Produced
from lab_commons.dev.forgetick import TickReport, tick
from lab_commons.dev.forgework import ForgeCallFailed
from lab_commons.hpc.needsets import needs_of

__all__ = ['Producing', 'Rounds', 'locked_fetch', 'supply_now']


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

    *ticking* and *carding* are the keywords every :func:`~lab_commons.dev.forgetick.tick` and every host card
    share; *supplied* is :func:`supply_now` with its host bound, *holding* the box ledger's claims now (none on a
    cluster); *runs* the cluster runs here, each running at *sized* of its need-set.
    """

    root: Path
    repo: str
    alarm: Callable[[Alarm], object]
    runs: list[forgerun.Run]
    slurm: forgerun.Cluster | None
    say: Callable[[str], None]
    sized: Callable[[frozenset[str]], Demand]
    supplied: Callable[[Sequence[Holding]], Supply]
    holding: Callable[[], Sequence[Holding]]
    ticking: Mapping[str, Any]
    carding: Mapping[str, Any]
    produce: Callable[..., Produced]
    latest: dict[str, Any] = dataclasses.field(default_factory=dict)  # the last round: what the card shows

    def __post_init__(self) -> None:
        """The producers, publishing this host's card at every beat."""
        self.producing = Producing(self.produce, card=self.card)

    def serve(self, beat_s: float) -> tuple[list[TickReport], list[Produced]]:
        """A round, then one per *beat_s* or per producer that ended, until none lives or one was stopped.

        Every producer is joined before this returns or raises.
        """
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
        running = [self.sized(needs_of(run.platform)) for run in self.runs]
        ticked = _tick(
            self.repo, self.root, self.alarm, **self.ticking,
            supply=supply, running=running, busy=self.producing.shas(),
        )  # fmt: skip
        client = self.ticking['client'](self.root)
        self.latest.update(ticked=ticked, supply=supply, held=held)
        for line in ticked.lines:
            self.say(line)
        if self.slurm is not None:
            self.runs = forgerun.supersede_moved(self.root, self.runs, client=client, cluster=self.slurm, say=self.say)
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
            running=(*(f'{run.sha[:12]} {run.platform}' for run in self.runs),
                     *(f'{one.what} (pid {one.pid})' for one in self.latest['held'])),
        )  # fmt: skip


def supply_now(
    held: Sequence[Holding],
    *,
    name: str,
    standing: forgerun.Standing | None,
    capacity: Callable[[], Capacity] = Capacity.read,
) -> Supply:
    """What this round admits against: the cluster standing, else the box's capacity less its ledger's claims *held*."""
    if standing is not None:
        return dataclasses.replace(standing.supply, scope=name)
    return probe.box(name, capacity=capacity(), holdings=held)


def _tick(repo: str, root: Path, alarm: Callable[[Alarm], object], **kwargs: object) -> TickReport:
    """One :func:`~lab_commons.dev.forgetick.tick`; the forge refusing the stored credential alarms before it raises."""
    try:
        return tick(root, **kwargs)
    except ForgeCallFailed as failed:
        if failed.report.attempts and failed.report.attempts[-1].returncode in _forge.AUTH_REFUSED:
            machine = kwargs.get('machine') or 'this host'
            alarm(Alarm(AUTH, repo, f'the forge refused the stored credential on {machine}', str(failed)))
        raise


class Producing:
    """The local producers this serve runs, one thread each (the module docstring): started, measured, joined.

    *produce* is :func:`lab_commons.dev.forgeproduce.produce` with everything but the part bound; each call
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

    def shas(self) -> frozenset[str]:
        """The shas a live producer is judging: their trees are taken."""
        with self._lock:
            return frozenset(sha for sha, _platform in self._live)

    def stopped(self) -> bool:
        """Whether a producer was stopped on purpose (:mod:`lab_commons.dev.stoprun`)."""
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
