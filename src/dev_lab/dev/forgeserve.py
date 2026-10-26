"""THE HARNESS ENTRY -- ``python -m dev_lab.dev.forge serve``, one call that serves a checkout.

ONE SOURCE FOR THE PROTOCOL. A harness used to restate the forge protocol step by step -- tick, run the
claimed argv, watch, publish, route -- and with it this family's venv layout and output tree, so every
protocol change needed a matching harness commit (audit 2026-10-10, item 4). This module owns the
sequence; a harness (a workstation's Scheduled Task, or a cluster account's crontab line under ``flock``)
keeps only scheduling, and calls this. ``forge serve --lock [PATH]`` first takes an exclusive lock
(:func:`dev_lab.dev.servelock.locked`): a second serve on the same lock exits 0 having done nothing.

THE SEQUENCE, in order: read the cluster runs in flight here (:func:`dev_lab.dev.forgerunstate.live`,
a run of another state schema refused); then ROUNDS while any local producer lives -- read what this
host can admit against (below), :func:`dev_lab.dev.forgetick.tick` (flush the outbox, fetch, claim
in rank order while jobs admit), start each claimed cluster part as a run and each claimed LOCAL part
as a producer of its own, and wait one tick period or until a producer ends; then advance every
cluster run one step
(:func:`dev_lab.dev.forgerun.advance`: submit, gather, store declared outputs, publish, route,
release -- whatever is due); on a cluster, clean the artefact stores (:func:`dev_lab.dev.forgeship.tidy`);
run the storage retention pass, every tick (:mod:`dev_lab.dev.retention`; still over quota raises a
``storage`` alarm); publish this host's card; then, ONLY ON THE REPO'S POLLER -- the host holding the poller
lease (:func:`polls`, :mod:`dev_lab.dev.forgepoller`; measured 2026-10-24, every host polling every repo
pegged the forge) -- close open PRs whose head is on their base (:func:`dev_lab.dev.prlanded.serve_close_landed`),
prune merged idle origin branches (idempotent) (:func:`dev_lab.dev.branchprune.serve_prune`),
prune the records home -- dead shas' records, unit results over budget -- once per interval
(:func:`dev_lab.dev.forgerecords.serve_prune`)
tidy the repo's issues (``forge tidy``, :func:`dev_lab.dev.forgetidy.tidy`), raise the starved parts, prompt
the integrator and relock (below); flush the outbox again.

SERVE IS THE ONE DOOR TO A FULL SUITE (``VERDICTS-FROM-THE-FORGE``): the producer it spawns carries the
claimed part in its environment (:func:`dev_lab.dev.producer.producing`), and a full tier refuses to
run in any process without it.

WHAT THE TICK ADMITS AGAINST (:func:`lab_commons.compute.admission.admit`), read here before it:

* SUPPLY -- a cluster account's standing (:mod:`dev_lab.dev.forgeslurm`); on a box, what its ONE
  ledger can still admit (:func:`dev_lab.dev.forgerounds.supply_now`): the box's capacity after the
  machine file's ``[reserve]`` margins less every claim on it -- each producer this serve runs (it runs in
  the box at its declared demand, :mod:`dev_lab.dev.forgeproduce`) and each interactive ``verify``
  (:mod:`dev_lab.dev.verify`) alike. Named as the card is (:func:`~dev_lab.dev.forgehosts.card_host`).
  The tick TAKES a local part's box claim before it claims the part, and the producer adopts it: the one
  admission is the tick's, so a started part is never box-refused and a refused one posts nothing.
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
(:mod:`dev_lab.dev.stoprun`) ends the claiming: no round starts after it, the live producers are
waited for, and serve exits -- what a stop means. However a round fails, every producer thread is joined
before serve returns or raises, so no claim is left held by a thread nobody waits for.

A LOCAL PRODUCER HOLDS ITS CLAIM: its output streams prefixed ``[platform@sha8]``, its
claim is renewed (the same claim, ``until`` = the forge's time plus the lease) every third of the
lease while it lives, its host card is published every tick period while it lives (``holds <sha>
<part> producing <minutes>m``, so a busy host never reads STALE), and when it ends with its context
still pending the claim is RELEASED as ``error`` with the reason its exit code names, so nobody
waits out a lease for a dead producer. A CLUSTER part is never a blocking process: each call
advances it and returns (:mod:`dev_lab.dev.forgerun`).

EXIT CODES ARE READ BY ONE CONTRACT, :mod:`dev_lab.dev.producer`: 0/1 a posted PASS/FAIL part,
2 the argv refused, 3 INCONCLUSIVE (released, a human decides), 4 UNREACHABLE infrastructure
(released retryable -- the next tick claims it again; an outage is never a red part), else a crash.
A CONTRACT BREAK FAILS LOUDLY: a produced argv exiting 2 -- what a renamed flag or verb looks like --
is a FAILURE of this call (exit 2) with the argv shown, never a quiet skip.

THE QUEUE DECIDES WHAT IS CLAIMED (:mod:`dev_lab.dev.forgeschedule`). Before the tick a cluster host
reads its standing locally -- its supply, the last day's core-hours, partitions -- and a box probes its own
(:mod:`lab_commons.compute.probe`); the tick claims the best feasible candidate and names why every
other waits. After it, a run whose ref moved on is SUPERSEDED (pending withdrawn, started drained -- and a drained
task is judged by the same stall watch as any other, below); on the poller,
a part no host admits waiting past its class's bound keeps one ``starved`` forge issue (:func:`raise_once`),
read across every host card; and this host's CARD is published on the forge
(:mod:`dev_lab.dev.forgehosts`):
who it is, what it serves, its supply, what it holds with progress, and the queue as it saw it.

THE FORGE PROMPTS THE INTEGRATOR: the repo's poller derives the integration queue
(:func:`dev_lab.dev.integrator.observe`) and keeps ONE ``integration`` forge issue per row that asks
for action (:func:`raise_once`): two hosts racing for the lease still write one issue, and only the host
that creates or changes it pages. No host OWNS integration: whoever holds the lease derives it. The same
tick runs the behind/conflict report on every child branch (:func:`dev_lab.dev.forgeintegration.tick`),
and a child conflicting with integration or past the lane policy's ``behind_max`` joins those rows as one
more ``integration`` issue.

RUNNING IS NOT HEALTHY: every tick on a cluster seat cancels this account's forge tasks whose stream stopped
past their bound, whatever their run (:meth:`dev_lab.dev.forgeslurm.SlurmCluster.stalled`; Ada 2026-10-24..26,
eight tasks held a core 34-41 h each on one hung test), and one alarm names each task's sha and last test.

NOTHING FAILS SILENTLY ON AN UNATTENDED HOST (:mod:`dev_lab.dev.forgealarm`): the forge refusing
the credential, a lease that cannot be renewed, a run that cannot advance, and an account IDLE while
work it could serve is pending each raise an alarm.

On EVERY serving host, poller or not, the PR review (:func:`dev_lab.dev.forgereview.step`): the repo's
declared review command, once per open PR head across hosts (its claim), on a host whose capabilities can run it.

Beside it, the SECURITY step (:func:`dev_lab.dev.forgesecurity.step`): ``tests/security`` once per open PR head
and per integration head, a condition every forge merge waits on.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import lab_commons.launch as _door
from lab_commons.box import Holding, holdings
from lab_commons.box.machine import provided
from lab_commons.box.providers import inventory
from lab_commons.compute.learned import cluster_demand
from lab_commons.compute.model import Supply
from lab_commons.compute.presence import Presence, declared_versions, refresh
from lab_commons.compute.priority import PRIORITY_TABLE, Priority
from lab_commons.compute.serves import SERVE_TABLE, Serves
from lab_commons.config import section
from lab_commons.hpc.account import ClusterAccount
from lab_commons.hpc.retired import refuse_retired_keys
from lab_commons.log import emit

from dev_lab.dev import forgerun, forgerunstate, metrics, retention
from dev_lab.dev.branchprune import serve_prune
from dev_lab.dev.forge import NoCredential, Transport, fetch_origin, https_transport
from dev_lab.dev.forgealarm import (
    AUTH,
    IDLE,
    RUN,
    UNTAGGED,
    Alarm,
    sound,
)
from dev_lab.dev.forgeclaim import DEFAULT_LEASE, Claim, forge_now, this_machine, this_seat
from dev_lab.dev.forgehosts import HostCard, HostsIssueLost, card_host, card_owners, read_cards, recording
from dev_lab.dev.forgeintent import reattach
from dev_lab.dev.forgeoutbox import PostFailed, flush, unprompted_client
from dev_lab.dev.forgepoller import elect
from dev_lab.dev.forgeproduce import Produced, demote_unreachable, produce
from dev_lab.dev.forgepulls import ListingIncomplete
from dev_lab.dev.forgerecords import serve_prune as serve_records_prune
from dev_lab.dev.forgerounds import Rounds, box_now, locked_fetch, reserve, supply_now
from dev_lab.dev.forgeschedule import host_weights
from dev_lab.dev.forgeservesteps import hygiene, prompt, relock, retain_storage, review, starved, tidy_runs
from dev_lab.dev.forgeslurm import slurm_cluster, standing_of
from dev_lab.dev.forgewait import Box
from dev_lab.dev.forgework import Client, ForgeCallFailed, client_for
from dev_lab.dev.platformparts import origin_url, run_tag
from dev_lab.dev.prlanded import serve_close_landed
from dev_lab.dev.producer import ProducerExit
from dev_lab.dev.worktreeplace import WORKTREES_REL

__all__ = ['POLL_LEASE_TICKS', 'ServeReport', 'main', 'polls', 'serve', 'work_root']


@dataclass(frozen=True)
class ServeReport:
    """The tick's lines, every local part produced, the cluster runs still in flight, the flush, broken contracts."""

    tick: tuple[str, ...]
    produced: tuple[Produced, ...]
    in_flight: tuple[str, ...]
    published: tuple[str, ...]
    broken: tuple[str, ...]


def _cancel_strays(
    slurm: forgerunstate.Cluster, repo: str, seat: ClusterAccount | None, alarm: Callable[[Alarm], object]
) -> None:
    """Cancel this account's forge jobs no run file holds, every tick, runs in flight or not: one alarm, counted."""
    if stray := slurm.strays(forgerunstate.held_names):
        body = f'jobs {" ".join(stray)} carried a forge job name no run file here holds; cancelled'
        alarm(Alarm(RUN, repo, f'{len(stray)} orphaned forge job(s) cancelled on {seat}', body, about='strays'))


def _cancel_stalled(
    slurm: forgerunstate.Cluster, repo: str, seat: ClusterAccount | None, alarm: Callable[[Alarm], object]
) -> None:
    """Cancel this account's forge tasks past their stall bound, every tick: one alarm naming each sha and test."""
    if stalled := slurm.stalled():
        body = '\n'.join(one.text() for one in stalled)
        alarm(Alarm(RUN, repo, f'{len(stalled)} stalled forge task(s) cancelled on {seat}', body, about='stalled'))


def serve(
    root: Path,
    *,
    client: Callable[[Path], Client],
    machine: str,
    seat: ClusterAccount | None,
    cluster: Callable[[], forgerunstate.Cluster],
    lease: timedelta = DEFAULT_LEASE,
    fetch: Callable[[Path], None] = fetch_origin,
    spawn: Callable[..., Any] = _door.popen,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    say: Callable[[str], None] = emit,
    alarm: Callable[[Alarm], object] = sound,
    renew_s: float | None = None,
    host: str | None = None,
    table: Mapping[str, Any] | None = None,
    supplied: Callable[..., Supply] = supply_now,
    present: Callable[[Path], Mapping[str, Presence]] = lambda here: refresh(declared_versions(here)),
    holding: Callable[[], Sequence[Holding]] = holdings,
    retain: Callable[..., retention.Freed | None] = retention.serve_pass,
    reserving: Callable[..., int | str] = reserve,
    boxed: Callable[[Sequence[Holding]], Box | None] = box_now,
) -> ServeReport:
    """The module docstring's sequence. *table* is the machine file's ``[schedule]`` (weights, tick_minutes).

    *present* re-probes this host's tools where due (:func:`lab_commons.compute.presence.refresh`), before
    anything reads them; *supplied* is what a round admits against
    (:func:`~dev_lab.dev.forgerounds.supply_now`), *holding* the box ledger's claims now, *retain* the
    retention pass, *reserving* what takes a local part's box claim before the tick claims it
    (:func:`~dev_lab.dev.forgerounds.reserve`; none on a cluster seat), *boxed* this box as a round's pass sees
    it (:func:`~dev_lab.dev.forgerounds.box_now`; none on a cluster seat) -- each a seam a test fakes.
    """
    repo = origin_url(root)
    table = section('schedule') if table is None else table
    raised: list[Alarm] = []  # every alarm this tick, for its host card
    alarm = recording(alarm, raised)

    def refused(why: str) -> None:  # one unreadable run file is skipped and named; the other runs advance
        alarm(Alarm(RUN, repo, 'a live cluster run this tool cannot read', why, about=why.split(maxsplit=1)[0]))

    runs = list(forgerunstate.live(repo, refused=refused)) if seat is not None else []
    refuse_retired_keys('serve', section('serve'))
    refuse_retired_keys('capabilities', section('capabilities'))
    tools = {name: one.row() for name, one in inventory(provided(section('capabilities')), present(root)).items()}
    priority = Priority.of(section(PRIORITY_TABLE))
    serves = Serves.of(section(SERVE_TABLE))
    slurm, standing, why = standing_of(cluster) if seat is not None else (None, None, '')
    if slurm is not None:
        _cancel_strays(slurm, repo, seat, alarm)
        _cancel_stalled(slurm, repo, seat, alarm)
    if standing is not None and (untagged := standing.facts.get('untagged')):
        body = 'set $LC_HPC_SESSION for every submitter: an untagged job holds a share no session can be throttled by'
        alarm(Alarm(UNTAGGED, repo, f'{untagged} untagged job task(s) on {seat}', body, about=str(seat)))
    name = card_host(machine, seat)
    cards = read_cards(client(root))
    every = lease.total_seconds() / 3 if renew_s is None else renew_s
    beat_s = float(table.get('tick_minutes', 5)) * 60
    fetched = locked_fetch(fetch)  # the tick and every producer fetch into one repository
    for line in reattach(root, client(root), lease=lease, say=say):  # runs a dead serve left journaled
        say(line)
    host_rounds = Rounds(
        root, repo, alarm, runs, slurm=slurm, say=say, sized=cluster_demand(repo),
        supplied=functools.partial(supplied, name=name, standing=standing),
        holding=(lambda: ()) if seat is not None else holding,
        ticking={
            'client': client, 'machine': machine, 'seat': seat, 'lease': lease, 'fetch': fetched, 'host': host,
            'usage': standing.usage if standing else None, 'weights': host_weights(table),
            'owners': card_owners(cards), 'priority': priority, 'serves': serves,
            'reserve': None if seat is not None else functools.partial(reserving, root=root),
        },
        carding={
            'client': client, 'machine': machine, 'seat': seat, 'host': host, 'standing': standing, 'table': table,
            'say': say, 'alarms': raised, 'tools': tools, 'priority': priority.row(),
            'serves': serves.parts, 'withholds': sorted(serves.withholds),
        },
        produce=functools.partial(
            produce, root, client=client, spawn=spawn, clock=clock, say=say, lease=lease, renew_s=every,
            fetch=fetched, beat_s=beat_s,
        ),
        room=(lambda _held: None) if seat is not None else boxed, cards=cards,
    )  # fmt: skip
    rounds, produced = host_rounds.serve(beat_s)
    demote_unreachable(produced)
    runs, card = host_rounds.runs, host_rounds.card
    ticked = rounds[-1]
    claimed = [item for one in rounds for item in one.claimed]
    runs_from = clock()  # the runs get a period of their own: rounds that ran long never starve them to one
    left = _advance(
        root, runs, client=client, machine=machine, seat=seat, lease=lease, slurm=slurm, why=why, say=say, alarm=alarm,
        beat=lambda: card(claimed), spent=lambda: clock() >= runs_from + timedelta(seconds=beat_s),
    )  # fmt: skip
    tidy_runs(root, client, repo, seat=seat, say=say, alarm=alarm)
    retain_storage(root, repo, retain, cluster=seat is not None, who=name, say=say, alarm=alarm)
    if ticked.pending and not claimed and not left:
        refused = '; '.join(ticked.refused) or 'nothing was claimed'
        named = ', '.join(f'{item.ref} {item.sha[:12]} {item.platform}' for item in ticked.pending)
        alarm(Alarm(IDLE, repo, f'{name} is idle with work pending', f'{named}: {refused}'))
    card(claimed)
    if polls(client(root), name, timedelta(seconds=POLL_LEASE_TICKS * beat_s), say):
        _repo_wide(root, repo, client, name, cards, clock=clock, say=say, alarm=alarm)
    review(root, client(root), say=say, host=name)  # wherever the command can run, never only on the poller
    broken = tuple(
        f'{p.platform} {p.sha[:12]}: the producer refused its argv: {" ".join(p.argv)}'
        for p in produced
        if p.returncode == ProducerExit.USAGE
    )
    published = tuple(flush(root, client=client))
    lines = tuple(line for one in rounds for line in one.lines)
    return ServeReport(lines, tuple(produced), tuple(left), published, broken)


def _repo_wide(
    root: Path,
    repo: str,
    client: Callable[[Path], Client],
    name: str,
    cards: Sequence[HostCard],
    *,
    clock: Callable[[], datetime],
    say: Callable[[str], None],
    alarm: Callable[[Alarm], object],
) -> None:
    """The repo-wide passes only the elected poller runs (:func:`polls`): close, prune, starve, prompt, relock."""
    serve_close_landed(root, client(root), say=say, alarm=alarm)
    serve_prune(root, client(root), now=clock(), say=say, alarm=alarm)
    serve_records_prune(root, client(root), now=clock(), say=say, alarm=alarm)
    hygiene(root, client(root), say=say)
    starved(root, repo, client(root), cards, say=say, alarm=alarm)
    prompt(root, repo, client(root), say=say, alarm=alarm, host=name)
    relock(root, repo, client(root), say=say, alarm=alarm)


#: How many tick periods a poller lease outlives its last renewal (:mod:`dev_lab.dev.forgepoller`).
POLL_LEASE_TICKS = 3


def polls(built: Client, host: str, ttl: timedelta, say: Callable[[str], None]) -> bool:
    """Whether *host* runs the repo-wide poll this tick (:func:`dev_lab.dev.forgepoller.elect`); never if unreadable."""
    try:
        here, holder = elect(built, host=host, ttl=ttl)
    except (OSError, ListingIncomplete, HostsIssueLost) as failed:
        say(f'[serve] no repo-wide poll this tick: the poller lease could not be read: {failed}')
        return False
    say(f'[serve] poller: {holder}' + ('' if here else '; this host claims and produces only'))
    return here


def _advance(
    root: Path,
    runs: Sequence[forgerunstate.Run],
    *,
    client: Callable[[Path], Client],
    machine: str,
    seat: ClusterAccount | None,
    lease: timedelta,
    slurm: forgerunstate.Cluster | None,
    why: str,
    say: Callable[[str], None],
    alarm: Callable[[Alarm], object],
    beat: Callable[[], None] = lambda: None,
    spent: Callable[[], bool] = lambda: False,
) -> list[str]:
    """Advance every run one tick; the shas still in flight. A run that cannot advance waits and alarms.

    A run's step can be slow (a gather, the routing and the post of a 55k-test record, a submit's prep), so
    the host card is published (*beat*) before each, and once the runs' own period is *spent* (counted from
    the first run, so the rounds before cannot spend it) the runs not yet reached wait for the next tick. A
    tick always advances at least one, and *runs* arrive least recently advanced first
    (:func:`forgerunstate.live`), so the runs one tick leaves are the first the next reaches: every run is
    reached within as many ticks as there are runs. The runs are bounded by one period plus one step, and
    ``forge queue``'s STALE keeps meaning down.
    """
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
    for at, run in enumerate(runs):
        if at and spent():
            waiting = [one.sha for one in runs[at:]]
            say(f'[serve] the tick ran past its period: {" ".join(sha[:12] for sha in waiting)} wait for the next')
            return left + waiting
        beat()
        try:
            after = forgerun.advance(
                root, run, client=built, me=me, lease=lease, cluster=slurm, say=say, alarm=alarm,
            )  # fmt: skip
        except (RuntimeError, OSError, ValueError) as stuck:  # Slurm or the build refused: the run waits
            alarm(Alarm(RUN, run.repo_url, f'the cluster run of {run.sha[:12]} cannot advance', str(stuck)))
            say(f'{run_tag(run.platform, run.sha)}: cannot advance: {stuck}')
            after = run
        if after is not None:
            forgerunstate.touch(after)
            left.append(after.sha)
    return left


def work_root(root: Path) -> Path:
    """Where a serve WORKS: its checkout's worktree root, beside the trees it produces in -- never the tree itself.

    A ``python -m`` process puts its cwd on ``sys.path``, so a serve whose cwd were the checkout would READ that
    tree for its whole life and lock it against every edit (TREE-HAS-A-LIVE-RUN, :mod:`dev_lab.dev.liverun`).
    """
    work = root / WORKTREES_REL
    work.mkdir(parents=True, exist_ok=True)
    return work


def _host_failure(root: Path, failure: BaseException) -> None:
    """A serve that failed before it posted anything reached nobody as a PR status: one ``host_failure`` line."""
    metrics.record(
        metrics.HOST_FAILURE, root=root, repo=metrics.repo_of(root), rule='serve', reason=type(failure).__name__
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    transport: Transport = https_transport,
    seat_of: Callable[[], ClusterAccount | None] = this_seat,
) -> int:
    """``serve [--json]``: 0 served, 1 forge or run state failed, 2 contract broke."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge serve', description=__doc__.splitlines()[0])
    parser.add_argument('--lease-hours', type=float, default=DEFAULT_LEASE.total_seconds() / 3600)
    parser.add_argument('--json', action='store_true', help='print the whole report as JSON')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd().resolve() if cwd is None else cwd
    if cwd is None:
        os.chdir(work_root(root))  # the serve reads its venv, never this tree (work_root)

    def build(here: Path) -> Client:
        return client_for(here, env=env, transport=transport) if env is not None else unprompted_client(here)

    seat = seat_of()
    machine = this_machine()
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
        sound(Alarm(AUTH, str(root), f'no stored forge credential on {card_host(machine, seat)}', str(missing)))
        emit(f'[serve] {missing}', err=True)
        return 1
    except (ForgeCallFailed, PostFailed, forgerunstate.ForeignSchema, OSError) as failed:
        _host_failure(root, failed)
        emit(f'[serve] {failed}', err=True)
        return 1
    except Exception as defect:
        _host_failure(root, defect)
        raise
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
