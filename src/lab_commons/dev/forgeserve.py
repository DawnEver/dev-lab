"""THE HARNESS ENTRY -- ``python -m lab_commons.dev.forge serve``, one call that serves a checkout.

ONE SOURCE FOR THE PROTOCOL. A harness used to restate the forge protocol step by step -- tick, run the
claimed argv, watch, publish, route -- and with it this family's venv layout and output tree, so every
protocol change needed a matching harness commit (audit 2026-10-10, item 4). This module owns the
sequence; a harness (a workstation's Scheduled Task, or a cluster account's crontab line under ``flock``)
keeps only scheduling, and calls this. ``forge serve --lock [PATH]`` first takes an exclusive lock
(:func:`lab_commons.dev.servelock.locked`): a second serve on the same lock exits 0 having done nothing.

THE SEQUENCE, in order: read the cluster runs in flight here (:func:`lab_commons.dev.forgerun.live`,
a run of another state schema refused); then ROUNDS while any local producer lives -- read what this
host can admit against (below), :func:`lab_commons.dev.forgetick.tick` (flush the outbox, fetch, claim
in rank order while jobs admit), start each claimed cluster part as a run and each claimed LOCAL part
as a producer of its own, and wait one tick period or until a producer ends; then advance every
cluster run one step
(:func:`lab_commons.dev.forgerun.advance`: submit, gather, store declared outputs, publish, route,
release -- whatever is due); on a cluster, clean the artefact stores (:func:`lab_commons.dev.forgeship.tidy`);
on any host, prune merged idle origin branches (idempotent) (:func:`lab_commons.dev.branchprune.serve_prune`)
and tidy the repo's issues (``forge tidy``, :func:`lab_commons.dev.forgetidy.tidy`) -- every served repo, every tick;
run the storage retention pass, every tick (:mod:`lab_commons.dev.retention`; still over quota raises a
``storage`` alarm); flush the outbox again.

SERVE IS THE ONE DOOR TO A FULL SUITE (``VERDICTS-FROM-THE-FORGE``): the producer it spawns carries the
claimed part in its environment (:func:`lab_commons.dev.producer.producing`), and a full tier refuses to
run in any process without it.

WHAT THE TICK ADMITS AGAINST (:func:`lab_commons.compute.admission.admit`), read here before it:

* SUPPLY -- a cluster account's standing (:mod:`lab_commons.dev.forgeslurm`); on a box, what its ONE
  ledger can still admit (:func:`lab_commons.dev.forgerounds.supply_now`): the box's capacity after the
  machine file's ``[reserve]`` margins less every claim on it -- each producer this serve runs (it runs in
  the box at its declared demand, :mod:`lab_commons.dev.forgeproduce`) and each interactive ``verify``
  (:mod:`lab_commons.dev.verify`) alike. Named as the card is (:func:`~lab_commons.dev.forgehosts.card_host`).
* RUNNING -- each cluster run in flight here, at its learned demand
  (:func:`~lab_commons.compute.learned.cluster_demand`).

SEVERAL LOCAL PARTS AT ONCE, ONE THREAD EACH, and why that shape: ``produce`` already owns one child --
its stream, its beats, its renewals, its release -- and is blocking, so N admitted parts are N calls of
it side by side. A second, multi-child producer loop would restate all of that; detached children
advanced per tick (the cluster's shape) would need a state file per child and a tick that adopts them.
Threads share two things, each behind a lock: the git fetch of the serving checkout (two fetches into
one repository race on its refs, and the tick fetches too) and the host card, published with EVERY live
part's progress. Each job is judged in its own tree, keyed by sha and context, so two jobs of one sha run side by side.

CLAIMING WHILE PRODUCING, and how it ends. A host busy with one part keeps claiming what still fits, a
round per tick period or per producer that ended. A producer STOPPED on purpose
(:mod:`lab_commons.dev.stoprun`) ends the claiming: no round starts after it, the live producers are
waited for, and serve exits -- what a stop means. However a round fails, every producer thread is joined
before serve returns or raises, so no claim is left held by a thread nobody waits for.

A LOCAL PRODUCER HOLDS ITS CLAIM: its output streams prefixed ``[platform]``, its
claim is renewed (the same claim, ``until`` = the forge's time plus the lease) every third of the
lease while it lives, its host card is published every tick period while it lives (``holds <sha>
<part> producing <minutes>m``, so a busy host never reads STALE), and when it ends with its context
still pending the claim is RELEASED as ``error`` with the reason its exit code names, so nobody
waits out a lease for a dead producer. A CLUSTER part is never a blocking process: each call
advances it and returns (:mod:`lab_commons.dev.forgerun`).

EXIT CODES ARE READ BY ONE CONTRACT, :mod:`lab_commons.dev.producer`: 0/1 a posted PASS/FAIL part,
2 the argv refused, 3 INCONCLUSIVE (released, a human decides), 4 UNREACHABLE infrastructure
(released retryable -- the next tick claims it again; an outage is never a red part), else a crash.
A CONTRACT BREAK FAILS LOUDLY: a produced argv exiting 2 -- what a renamed flag or verb looks like --
is a FAILURE of this call (exit 2) with the argv shown, never a quiet skip.

THE QUEUE DECIDES WHAT IS CLAIMED (:mod:`lab_commons.dev.forgeschedule`). Before the tick a cluster host
reads its standing locally -- its supply, the last day's core-hours, partitions -- and a box probes its own
(:mod:`lab_commons.compute.probe`); the tick claims the best feasible candidate and names why every
other waits. After it, a run whose ref moved on is SUPERSEDED (cancelled and released); on ANY host,
a part no host admits waiting past its class's bound keeps one ``starved`` forge issue (:func:`raise_once`),
read across every host card; and this host's CARD is published on the forge
(:mod:`lab_commons.dev.forgehosts`):
who it is, what it serves, its supply, what it holds with progress, and the queue as it saw it.

THE FORGE PROMPTS THE INTEGRATOR: every host derives the integration queue
(:func:`lab_commons.dev.integrator.observe`) and keeps ONE ``integration`` forge issue per row that asks
for action (:func:`raise_once`): N hosts write one issue, and only the host that creates or changes it
pages. No host owns integration. The same tick runs the behind/conflict report on every child branch
(:func:`lab_commons.dev.forgeintegration.tick`), and a child conflicting with integration or past the lane
policy's ``behind_max`` joins those rows as one more ``integration`` issue.

NOTHING FAILS SILENTLY ON AN UNATTENDED HOST (:mod:`lab_commons.dev.forgealarm`): the forge refusing
the credential, a lease that cannot be renewed, a run that cannot advance, and an account IDLE while
work it could serve is pending each raise an alarm.
"""

from __future__ import annotations

import argparse
import functools
import json
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from lab_commons.box import Holding, declared_seats, holdings
from lab_commons.compute.learned import cluster_demand
from lab_commons.compute.model import Supply
from lab_commons.compute.presence import Presence, declared_versions, refresh
from lab_commons.compute.priority import PRIORITY_TABLE, Priority
from lab_commons.compute.probe import inventory
from lab_commons.config import section
from lab_commons.dev import forgerun, forgeship, retention
from lab_commons.dev.branchprune import serve_prune
from lab_commons.dev.forge import NoCredential, Transport, fetch_origin, https_transport
from lab_commons.dev.forgealarm import AUTH, IDLE, INTEGRATION, ISSUE_KINDS, RUN, STARVED, STORAGE, Alarm, sound
from lab_commons.dev.forgeclaim import DEFAULT_LEASE, Claim, forge_now, this_machine, this_seat
from lab_commons.dev.forgehosts import HostCard, card_host, card_owners, read_cards, recording
from lab_commons.dev.forgeintegration import alarms as sync_alarms
from lab_commons.dev.forgeintegration import tick as integration_tick
from lab_commons.dev.forgeintegration import venues
from lab_commons.dev.forgeoutbox import PostFailed, flush, unprompted_client
from lab_commons.dev.forgeproduce import Produced, demote_unreachable, produce
from lab_commons.dev.forgepulls import ListingIncomplete
from lab_commons.dev.forgequeue import forge_queue, unadmitted
from lab_commons.dev.forgerounds import Rounds, locked_fetch, supply_now
from lab_commons.dev.forgeroute import reconcile
from lab_commons.dev.forgeschedule import host_weights, load_schedule, starved_alarms
from lab_commons.dev.forgeslurm import slurm_cluster, standing_of
from lab_commons.dev.forgestatus import status_list
from lab_commons.dev.forgetidy import load_hygiene
from lab_commons.dev.forgetidy import tidy as issue_tidy
from lab_commons.dev.forgework import Client, ForgeCallFailed, client_for
from lab_commons.dev.integrator import observe
from lab_commons.dev.lanepolicy import load_policy
from lab_commons.dev.platformparts import origin_url
from lab_commons.dev.producer import ProducerExit
from lab_commons.hpc.account import ClusterAccount
from lab_commons.hpc.retired import refuse_retired_keys
from lab_commons.log import emit

__all__ = ['ServeReport', 'main', 'raise_once', 'serve']


@dataclass(frozen=True)
class ServeReport:
    """The tick's lines, every local part produced, the cluster runs still in flight, the flush, broken contracts."""

    tick: tuple[str, ...]
    produced: tuple[Produced, ...]
    in_flight: tuple[str, ...]
    published: tuple[str, ...]
    broken: tuple[str, ...]


def serve(
    root: Path,
    *,
    client: Callable[[Path], Client],
    machine: str,
    seat: ClusterAccount | None,
    cluster: Callable[[], forgerun.Cluster],
    lease: timedelta = DEFAULT_LEASE,
    fetch: Callable[[Path], None] = fetch_origin,
    spawn: Callable[..., Any] = subprocess.Popen,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    say: Callable[[str], None] = emit,
    alarm: Callable[[Alarm], object] = sound,
    renew_s: float | None = None,
    host: str | None = None,
    table: Mapping[str, Any] | None = None,
    supplied: Callable[..., Supply] = supply_now,
    present: Callable[[Path], Mapping[str, Presence]] = lambda here: refresh(declared_versions(here)),
    holding: Callable[[], Sequence[Holding]] = holdings,
    retain: Callable[..., retention.Outcome | None] = retention.serve_pass,
) -> ServeReport:
    """The module docstring's sequence. *table* is the machine file's ``[schedule]`` (weights, tick_minutes).

    *present* re-probes this host's tools where due (:func:`lab_commons.compute.presence.refresh`), before
    anything reads them; *supplied* is what a round admits against
    (:func:`~lab_commons.dev.forgerounds.supply_now`), *holding* the box ledger's claims now, *retain* the
    retention pass -- each a seam a test fakes.
    """
    repo = origin_url(root)
    table = section('schedule') if table is None else table
    raised: list[Alarm] = []  # every alarm this tick, for its host card
    alarm = recording(alarm, raised)
    runs = list(forgerun.live(repo)) if seat is not None else []
    refuse_retired_keys('serve', section('serve'))
    tools = {name: one.row() for name, one in inventory(declared_seats(), present(root)).items()}
    priority = Priority.of(section(PRIORITY_TABLE))
    slurm, standing, why = standing_of(cluster) if seat is not None else (None, None, '')
    name = card_host(machine, seat)
    cards = read_cards(client(root))
    every = lease.total_seconds() / 3 if renew_s is None else renew_s
    beat_s = float(table.get('tick_minutes', 5)) * 60
    fetched = locked_fetch(fetch)  # the tick and every producer fetch into one repository
    host_rounds = Rounds(
        root, repo, alarm, runs, slurm=slurm, say=say, sized=cluster_demand(repo),
        supplied=functools.partial(supplied, name=name, standing=standing),
        holding=(lambda: ()) if seat is not None else holding,
        ticking={
            'client': client, 'machine': machine, 'seat': seat, 'lease': lease, 'fetch': fetched, 'host': host,
            'usage': standing.usage if standing else None, 'weights': host_weights(table),
            'owners': card_owners(cards), 'priority': priority,
        },
        carding={
            'client': client, 'machine': machine, 'seat': seat, 'host': host, 'standing': standing, 'table': table,
            'say': say, 'alarms': raised, 'tools': tools, 'priority': priority.row(),
        },
        produce=functools.partial(
            produce, root, client=client, spawn=spawn, clock=clock, say=say, lease=lease, renew_s=every,
            fetch=fetched, beat_s=beat_s,
        ),
    )  # fmt: skip
    rounds, produced = host_rounds.serve(beat_s)
    demote_unreachable(produced)
    runs, card = host_rounds.runs, host_rounds.card
    ticked = rounds[-1]
    claimed = [item for one in rounds for item in one.claimed]
    left = _advance(
        root, runs, client=client, machine=machine, seat=seat, lease=lease, slurm=slurm, why=why, say=say, alarm=alarm
    )
    _tidy(root, client, repo, seat=seat, say=say, alarm=alarm)
    _retain(root, repo, retain, cluster=seat is not None, who=name, say=say, alarm=alarm)
    serve_prune(root, client(root), now=clock(), say=say, alarm=alarm)
    _hygiene(root, client(root), say=say)
    if ticked.pending and not claimed and not left:
        refused = '; '.join(ticked.refused) or 'nothing was claimed'
        named = ', '.join(f'{item.ref} {item.sha[:12]} {item.platform}' for item in ticked.pending)
        alarm(Alarm(IDLE, repo, f'{machine or "this host"} is idle with work pending', f'{named}: {refused}'))
    _starved(root, repo, client(root), cards, say=say, alarm=alarm)
    card(claimed)
    _prompt(root, repo, client(root), say=say, alarm=alarm)
    broken = tuple(
        f'{p.platform} {p.sha[:12]}: the producer refused its argv: {" ".join(p.argv)}'
        for p in produced
        if p.returncode == ProducerExit.USAGE
    )
    published = tuple(flush(root, client=client))
    lines = tuple(line for one in rounds for line in one.lines)
    return ServeReport(lines, tuple(produced), tuple(left), published, broken)


def raise_once(built: Client, kind: str, alarms: Sequence[Alarm], *, alarm: Callable[[Alarm], object]) -> None:
    """Keep ONE forge issue per alarm of *kind* (``<kind>: <subject>``) and page only where it was written.

    Any host may raise these; :func:`lab_commons.dev.forgeroute.reconcile` finds the issue by its title, so
    N hosts deriving the same rows write one issue, the host that creates or changes it pages, and a row
    no longer derived closes its issue. A kind outside :data:`~lab_commons.dev.forgealarm.ISSUE_KINDS` is refused.
    """
    if kind not in ISSUE_KINDS:
        msg = f'{kind!r} is not an issue-kept alarm kind {ISSUE_KINDS} (lab_commons.dev.forgealarm.ISSUE_KINDS)'
        raise ValueError(msg)
    by_title = {f'{kind}: {one.subject}': one for one in alarms}
    for done in reconcile(built, f'{kind}: ', {title: one.body for title, one in by_title.items()}):
        if done.action in {'created', 'updated'} and done.area in by_title:
            alarm(by_title[done.area])


def _starved(
    root: Path,
    repo: str,
    built: Client,
    cards: Sequence[HostCard],
    *,
    say: Callable[[str], None],
    alarm: Callable[[Alarm], object],
) -> None:
    """A ``starved`` issue for each part NO host admits, read across every card; any host may raise it."""
    schedule = load_schedule(root)
    try:
        queue, _ = forge_queue(root, built, cards, now=forge_now(built), schedule=schedule)
        found = starved_alarms([item for item in queue if unadmitted(item.blocked)], schedule, repo)
        raise_once(built, STARVED, found, alarm=alarm)
    except ForgeCallFailed as failed:
        say(f'[serve] the starved parts were not raised: {failed}')


def _prompt(
    root: Path,
    repo: str,
    built: Client,
    *,
    say: Callable[[str], None],
    alarm: Callable[[Alarm], object],
) -> None:
    """The integrator's prompts and every child's behind/conflict report, one issue per row.

    A forge or fetch failure is said, not raised -- and then NO row is reconciled, so a partial derivation
    never closes an issue it merely failed to see.
    """
    try:
        found = observe(root, repo, statuses=lambda sha: status_list(built, sha))
        policy = load_policy(root)
        ticked = integration_tick(root, venues(root, built), policy)
        for line in ticked.lines:
            say(f'[serve] integration: {line}')
        raise_once(built, INTEGRATION, [*found, *sync_alarms(ticked.said, policy, repo)], alarm=alarm)
    except (ForgeCallFailed, ListingIncomplete, OSError) as failed:
        say(f'[serve] the integration queue was not derived: {failed}')


def _tidy(
    root: Path,
    client: Callable[[Path], Client],
    repo: str,
    *,
    seat: ClusterAccount | None,
    say: Callable[[str], None],
    alarm: Callable[[Alarm], object],
) -> None:
    """On a cluster -- one artefact writer -- clean its own account's runs each tick; a failure only alarms."""
    if seat is None:
        return
    try:
        forgeship.tidy(root, client(root), account=seat.account, say=say)
    except (OSError, ValueError) as why:
        alarm(Alarm(RUN, repo, 'the artefact cleanup failed', str(why)))


def _hygiene(root: Path, built: Client, *, say: Callable[[str], None]) -> None:
    """The repo's issue hygiene, on any host every tick (idempotent: a raced close is a no-op); a failure is said."""
    try:
        for line in issue_tidy(built, load_hygiene(root)):
            say(f'[serve] tidy: {line}')
    except (ForgeCallFailed, ListingIncomplete, ValueError) as failed:
        say(f'[serve] the issue hygiene did not run: {failed}')


def _retain(
    root: Path,
    repo: str,
    retain: Callable[..., retention.Outcome | None],
    *,
    cluster: bool,
    who: str,
    say: Callable[[str], None],
    alarm: Callable[[Alarm], object],
) -> None:
    """The retention pass; a failure, or usage still over the pressure line after it, alarms."""
    try:
        done = retain(root, cluster=cluster, say=say)
    except (OSError, ValueError) as why:
        alarm(Alarm(RUN, repo, f'the storage retention pass failed on {who}', str(why)))
        return
    if done is not None and done.over:
        body = done.alarm or f'freed {done.freed_bytes} bytes and {done.freed_files} files; still over pressure'
        alarm(Alarm(STORAGE, repo, f'{who} storage is still near its quota', body))


def _advance(
    root: Path,
    runs: Sequence[forgerun.Run],
    *,
    client: Callable[[Path], Client],
    machine: str,
    seat: ClusterAccount | None,
    lease: timedelta,
    slurm: forgerun.Cluster | None,
    why: str,
    say: Callable[[str], None],
    alarm: Callable[[Alarm], object],
) -> list[str]:
    """Advance every run one tick; the shas still in flight. A run that cannot advance waits and alarms."""
    if not runs:
        return []
    built = client(root)
    me = Claim(machine, built.whoami(), forge_now(built) + lease, str(seat) if seat else '')
    if slurm is None:  # not on a cluster, or no grant for this account
        for run in runs:
            alarm(Alarm(RUN, run.repo_url, f'the cluster run of {run.sha[:12]} cannot advance', why))
        say(f'[serve] no cluster to advance {len(runs)} run(s) on: {why}')
        return [run.sha for run in runs]
    left: list[str] = []
    for run in runs:
        try:
            after = forgerun.advance(
                root, run, client=built, me=me, lease=lease, cluster=slurm, say=say, alarm=alarm,
            )  # fmt: skip
        except (RuntimeError, OSError, ValueError) as stuck:  # Slurm or the build refused: the run waits
            alarm(Alarm(RUN, run.repo_url, f'the cluster run of {run.sha[:12]} cannot advance', str(stuck)))
            say(f'[{run.platform}] {run.sha[:12]}: cannot advance: {stuck}')
            after = run
        if after is not None:
            left.append(after.sha)
    return left


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    transport: Transport = https_transport,
    seat_of: Callable[[], ClusterAccount | None] = this_seat,
) -> int:
    """``serve [--json]``: 0 served, 1 forge or run state failed, 2 contract broke."""
    parser = argparse.ArgumentParser(prog='lab_commons.dev.forge serve', description=__doc__.splitlines()[0])
    parser.add_argument('--lease-hours', type=float, default=DEFAULT_LEASE.total_seconds() / 3600)
    parser.add_argument('--json', action='store_true', help='print the whole report as JSON')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd() if cwd is None else cwd

    def build(here: Path) -> Client:
        return client_for(here, env=env, transport=transport) if env is not None else unprompted_client(here)

    seat = seat_of()
    machine = this_machine(seat)
    try:
        report = serve(
            root,
            client=build,
            machine=machine,
            seat=seat,
            cluster=lambda: slurm_cluster(root, seat),
            lease=timedelta(hours=args.lease_hours),
            say=lambda line: emit(line, err=args.json, flush=True),
        )
    except NoCredential as missing:
        sound(Alarm(AUTH, str(root), f'no stored forge credential on {machine or "this host"}', str(missing)))
        emit(f'[serve] {missing}', err=True)
        return 1
    except (ForgeCallFailed, PostFailed, forgerun.ForeignSchema, OSError) as failed:
        emit(f'[serve] {failed}', err=True)
        return 1
    if args.json:
        emit(json.dumps(asdict(report), indent=2))
    else:
        for line in (
            *(f'produced {p.platform} {p.sha[:12]} exit={p.returncode}' for p in report.produced),
            *(f'in flight {sha[:12]}' for sha in report.in_flight),
            *report.published,
        ):
            emit(line)
    for line in report.broken:
        emit(f'[serve] CONTRACT BROKEN -- {line}', err=True)
    return ProducerExit.USAGE if report.broken else 0
