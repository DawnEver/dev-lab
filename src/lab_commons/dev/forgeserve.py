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
on the host that owns integration, prune merged idle origin branches (:func:`lab_commons.dev.branchprune.serve_prune`);
flush the outbox again.

SERVE IS THE ONE DOOR TO A FULL SUITE (``VERDICTS-FROM-THE-FORGE``): the producer it spawns carries the
claimed part in its environment (:func:`lab_commons.dev.producer.producing`), and a full tier refuses to
run in any process without it.

WHAT THE TICK ADMITS AGAINST (:func:`lab_commons.compute.admission.admit`), read here before it:

* SUPPLY -- a cluster account's standing (:mod:`lab_commons.dev.forgeslurm`); a box's probe
  (:func:`lab_commons.compute.probe.box`) less its user's OWN RESERVE (the machine file's ``[reserve]``
  margins, :func:`lab_commons.compute.ledger.own_reserve`; the probe already reads what is busy now, so
  what the user uses is not subtracted twice). Named as the card is (:func:`~lab_commons.dev.forgehosts.card_host`),
  so a lease on this host is a lease on this supply.
* RESERVATIONS -- every authorised lease on the ledger (:func:`lab_commons.compute.ledger.read`); a lease
  on another scope, expired, or for the job keeps nothing from it; a live one LENDS its idle part, and
  each round withdraws or stops a loan a holder preempts (:mod:`lab_commons.dev.forgerounds`).
* RUNNING -- each cluster run in flight here, at its learned demand; each LOCAL PRODUCER this serve is
  running, at its learned demand -- and since the probe already reads what it busies, what it was last
  measured using (:func:`lab_commons.dev.forgeproduce.produce`'s *watch*) is given back to the supply,
  so it is counted once; and each INTERACTIVE run holding the
  box seat (:class:`~lab_commons.dev.cpuseat.CpuSeat`, a developer's ``gate measure`` or ``verify``), at
  what it declared, else the whole box. The seat no longer decides what serve claims: it only makes an
  interactive run visible to it. A producer serve spawned takes no box seat (:mod:`lab_commons.dev.verify`).

SEVERAL LOCAL PARTS AT ONCE, ONE THREAD EACH, and why that shape: ``produce`` already owns one child --
its stream, its beats, its renewals, its release -- and is blocking, so N admitted parts are N calls of
it side by side. A second, multi-child producer loop would restate all of that; detached children
advanced per tick (the cluster's shape) would need a state file per child and a tick that adopts them.
Threads share two things, each behind a lock: the git fetch of the serving checkout (two fetches into
one repository race on its refs, and the tick fetches too) and the host card, published with EVERY live
part's progress. Each part is judged in its own sha's tree: a sha being produced here is passed to the
tick as busy, so no round claims a second part of it.

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
other waits. After it, a run whose ref moved on is SUPERSEDED (cancelled and released), a candidate
waiting past its class's bound raises a ``starved`` alarm, and this host's CARD is published on the forge
(:mod:`lab_commons.dev.forgehosts`):
who it is, what it serves, its supply, what it holds with progress, and the queue as it saw it.

THE FORGE PROMPTS THE INTEGRATOR: on the host declared to own integration (``[tool.lab_commons.integrator]
host``, matched against this host's card name and its forge login), the tick derives the integration
queue and raises an ``integration`` alarm per new row that asks for action
(:func:`lab_commons.dev.integrator.observe`). Every other host derives nothing.

NOTHING FAILS SILENTLY ON AN UNATTENDED HOST (:mod:`lab_commons.dev.forgealarm`): the forge refusing
the credential, a lease that cannot be renewed, a run that cannot advance, and an account IDLE while
work it could serve is pending each raise an alarm.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from lab_commons.compute import ledger
from lab_commons.compute import probe as supply_probe
from lab_commons.compute.learned import learned_demand
from lab_commons.compute.ledger import own_reserve, reserve_table
from lab_commons.compute.model import Resources, Supply
from lab_commons.config import section
from lab_commons.dev import forgerun, forgeship
from lab_commons.dev.branchprune import serve_prune
from lab_commons.dev.cpuseat import CpuSeat
from lab_commons.dev.forge import NoCredential, Transport, fetch_origin, https_transport
from lab_commons.dev.forgealarm import AUTH, IDLE, RUN, Alarm, sound
from lab_commons.dev.forgeclaim import DEFAULT_LEASE, Claim, forge_now, this_machine, this_seat
from lab_commons.dev.forgehosts import card_host, recording
from lab_commons.dev.forgeoutbox import PostFailed, flush, unprompted_client
from lab_commons.dev.forgeproduce import Produced, produce
from lab_commons.dev.forgeprovides import provided
from lab_commons.dev.forgerounds import Rounds, locked_fetch, supply_now
from lab_commons.dev.forgeschedule import host_weights, load_schedule, starved_alarms
from lab_commons.dev.forgeslurm import slurm_cluster, standing_of
from lab_commons.dev.forgestatus import status_list
from lab_commons.dev.forgework import Client, ForgeCallFailed, client_for
from lab_commons.dev.integrator import observe
from lab_commons.dev.platformparts import origin_url
from lab_commons.dev.producer import ProducerExit
from lab_commons.hpc.account import ClusterAccount
from lab_commons.hpc.retired import refuse_retired_keys
from lab_commons.log import emit
from lab_commons.proc import system_memory
from lab_commons.resources import Holder

__all__ = ['ServeReport', 'box_reserve', 'main', 'serve']

_GB = 1024.0**3


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
    box_room: Callable[..., Supply] = supply_probe.box,
    table: Mapping[str, Any] | None = None,
    reserve: Callable[[], Resources] | None = None,
    holders: Callable[[], Sequence[Holder]] = CpuSeat.holders,
    read_ledger: Callable[[Client], ledger.Ledger] = ledger.read,
) -> ServeReport:
    """The module docstring's sequence. *table* is the machine file's ``[schedule]`` (weights, tick_minutes).

    *reserve* is this box's own reserve (default: :func:`box_reserve`), *holders* who holds the box seat
    now, *read_ledger* the reservations' reader -- each a seam a test fakes.
    """
    repo = origin_url(root)
    table = section('schedule') if table is None else table
    raised: list[Alarm] = []  # every alarm this tick, for its host card
    alarm = recording(alarm, raised)
    runs = list(forgerun.live(repo)) if seat is not None else []
    refuse_retired_keys('serve', section('serve'))
    provides = provided(section('capabilities'))
    slurm, standing, why = standing_of(cluster) if seat is not None else (None, None, '')
    name = card_host(machine, seat)
    cores = os.cpu_count() or 1
    book = read_ledger(client(root))
    every = lease.total_seconds() / 3 if renew_s is None else renew_s
    beat_s = float(table.get('tick_minutes', 5)) * 60
    fetched = locked_fetch(fetch)  # the tick and every producer fetch into one repository
    host_rounds = Rounds(
        root, repo, alarm, runs, slurm=slurm, say=say, cores=cores,
        sized=learned_demand(repo, cluster=seat is not None, cores=cores),
        supplied=functools.partial(
            supply_now, name=name, standing=standing, box_room=box_room, provides=provides,
            reserve=reserve or box_reserve,
        ),
        seated=(lambda: ()) if seat is not None else lambda: tuple(holders()),
        ticking={
            'client': client, 'machine': machine, 'seat': seat, 'lease': lease, 'fetch': fetched, 'host': host,
            'reservations': tuple(one.reservation for one in book.entries if not one.refused),
            'usage': standing.usage if standing else None, 'weights': host_weights(table),
            'owners': {host_: (owner.login, *owner.delegates) for host_, owner in book.owners.items()},
        },
        carding={
            'client': client, 'machine': machine, 'seat': seat, 'host': host, 'standing': standing, 'table': table,
            'say': say, 'alarms': raised, 'provides': provides,
            'delegates': reserve_table(section('reserve')).delegates,
        },
        leased=lambda now: [one.row() for one in book.live(now) if one.reservation.scope == name],
        produce=functools.partial(
            produce, root, client=client, spawn=spawn, clock=clock, say=say, lease=lease, renew_s=every,
            fetch=fetched, beat_s=beat_s,
        ),
    )  # fmt: skip
    rounds, produced = host_rounds.serve(beat_s)
    runs, card = host_rounds.runs, host_rounds.card
    ticked = rounds[-1]
    claimed = [item for one in rounds for item in one.claimed]
    left = _advance(
        root, runs, client=client, machine=machine, seat=seat, lease=lease, slurm=slurm, why=why, say=say, alarm=alarm
    )
    _tidy(root, client, repo, seat=seat, say=say, alarm=alarm)
    serve_prune(root, client(root), host=name, now=clock(), say=say, alarm=alarm)
    if ticked.pending and not claimed and not left:
        refused = '; '.join(ticked.refused) or 'nothing was claimed'
        named = ', '.join(f'{item.ref} {item.sha[:12]} {item.platform}' for item in ticked.pending)
        alarm(Alarm(IDLE, repo, f'{machine or "this host"} is idle with work pending', f'{named}: {refused}'))
    for one in starved_alarms(ticked.queue, load_schedule(root), repo):
        alarm(one)
    card(claimed)
    _prompt(root, repo, client(root), hosts={name}, say=say, alarm=alarm)
    broken = tuple(
        f'{p.platform} {p.sha[:12]}: the producer refused its argv: {" ".join(p.argv)}'
        for p in produced
        if p.returncode == ProducerExit.USAGE
    )
    published = tuple(flush(root, client=client))
    lines = tuple(line for one in rounds for line in one.lines)
    return ServeReport(lines, tuple(produced), tuple(left), published, broken)


def _prompt(
    root: Path,
    repo: str,
    built: Client,
    *,
    hosts: set[str],
    say: Callable[[str], None],
    alarm: Callable[[Alarm], object],
) -> None:
    """Raise the integrator's prompts when this host owns integration; a forge failure is said, not raised."""
    try:
        for one in observe(root, repo, hosts={*hosts, built.whoami()}, statuses=lambda sha: status_list(built, sha)):
            alarm(one)
    except ForgeCallFailed as failed:
        say(f'[serve] the integration queue was not derived: {failed}')


def box_reserve(table: Mapping[str, Any] | None = None) -> Resources:
    """The own reserve of this box: the machine file's ``[reserve]`` margins over its cores and memory.

    What the box's user is using now is not added: the probe's supply already reads it as busy.
    """
    memory = system_memory()
    total = Resources(cpu=os.cpu_count() or 1, mem_gb=memory.total_bytes / _GB if memory else 0.0)
    return own_reserve(total, {}, reserve_table(section('reserve') if table is None else table))


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
