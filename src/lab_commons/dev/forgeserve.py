"""THE HARNESS ENTRY -- ``python -m lab_commons.dev.forge serve --mode M``, one call that serves a checkout.

ONE SOURCE FOR THE PROTOCOL. A harness used to restate the forge protocol step by step -- tick, run the
claimed argv, watch, publish, route -- and with it this family's venv layout and output tree, so every
protocol change needed a matching harness commit (audit 2026-10-10, item 4). This module owns the
sequence; a harness (a workstation's, or a cluster account's crontab line under ``flock``) keeps only
scheduling and locking, and calls this.

THE SEQUENCE, in order: read the cluster runs in flight here (:func:`lab_commons.dev.forgerun.live`,
a run of another state schema refused); :func:`lab_commons.dev.forgetick.tick` (flush the outbox,
fetch, claim at most one part -- none while a run is in flight); start a claimed cluster part as a run,
or produce a claimed LOCAL part inline; advance every cluster run one step
(:func:`lab_commons.dev.forgerun.advance`: submit, gather, publish, route, release -- whatever is due);
flush the outbox again.

SERVE IS THE ONE DOOR TO A FULL SUITE (``VERDICTS-FROM-THE-FORGE``): the producer it spawns carries the
claimed part in its environment (:func:`lab_commons.dev.producer.producing`), and a full tier refuses to
run in any process without it.

A LOCAL PRODUCER RUNS INLINE AND HOLDS ITS CLAIM: its output streams prefixed ``[platform]``, its
claim is renewed (the same claim, ``until`` = the forge's time plus the lease) every third of the
lease while it lives, and when it ends with its context still pending the claim is RELEASED as
``error`` with the reason its exit code names, so nobody waits out a lease for a dead producer. A
CLUSTER part is never a blocking process: each call advances it and returns (:mod:`lab_commons.dev.forgerun`).

EXIT CODES ARE READ BY ONE CONTRACT, :mod:`lab_commons.dev.producer`: 0/1 a posted PASS/FAIL part,
2 the argv refused, 3 INCONCLUSIVE (released, a human decides), 4 UNREACHABLE infrastructure
(released retryable -- the next tick claims it again; an outage is never a red part), else a crash.
A CONTRACT BREAK FAILS LOUDLY: a produced argv exiting 2 -- what a renamed flag or verb looks like --
is a FAILURE of this call (exit 2) with the argv shown, never a quiet skip.

THE QUEUE DECIDES WHAT IS CLAIMED (:mod:`lab_commons.dev.forgeschedule`). Before the tick a cluster host
reads its standing locally -- headroom, the last day's core-hours, partitions -- and a box its CPU seat;
the tick claims the best feasible candidate and names why every other waits. After it, a run whose ref
moved on is SUPERSEDED (cancelled and released), a candidate waiting past its class's bound raises a
``starved`` alarm, and this host's CARD is published on the forge (:mod:`lab_commons.dev.forgehosts`):
who it is, what it serves, its headroom, what it holds with progress, and the queue as it saw it.

NOTHING FAILS SILENTLY ON AN UNATTENDED HOST (:mod:`lab_commons.dev.forgealarm`): the forge refusing
the credential, a lease that cannot be renewed, a run that cannot advance, and an account IDLE while
work it could serve is pending each raise an alarm.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import subprocess
import sys
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from lab_commons.config import section
from lab_commons.dev import forge as _forge
from lab_commons.dev import forgerun
from lab_commons.dev.forge import NoCredential, Transport, fetch_origin, https_transport
from lab_commons.dev.forgealarm import AUTH, IDLE, RUN, Alarm, sound
from lab_commons.dev.forgeclaim import DEFAULT_LEASE, OPEN, STALE, Claim, Work, forge_now, this_machine, this_seat
from lab_commons.dev.forgehosts import publish_card
from lab_commons.dev.forgeoutbox import PostFailed, flush, unprompted_client
from lab_commons.dev.forgeschedule import Headroom, box_headroom, host_weights, load_schedule, starved_alarms, tip_of
from lab_commons.dev.forgeslurm import slurm_cluster, standing_of
from lab_commons.dev.forgestatus import status_history, status_post
from lab_commons.dev.forgetick import MODES, tick
from lab_commons.dev.forgework import Client, ForgeCallFailed, client_for
from lab_commons.dev.platformparts import origin_url, part_context
from lab_commons.dev.producer import ProducerExit, producing, release_reason
from lab_commons.hpc.account import ClusterAccount
from lab_commons.log import emit

__all__ = ['Produced', 'ServeReport', 'main', 'serve']

#: How long a produced part may run before it is called hung, in seconds.
PRODUCE_WALL_S: Final = 24 * 3600


@dataclass(frozen=True)
class Produced:
    """One claimed local part and what producing it did."""

    ref: str
    sha: str
    platform: str
    argv: tuple[str, ...]
    returncode: int


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
    mode: str,
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
    box_room: Callable[[], Headroom] = box_headroom,
    table: Mapping[str, Any] | None = None,
) -> ServeReport:
    """The module docstring's sequence. *table* is the machine file's ``[schedule]`` (weights, tick_minutes)."""
    repo = origin_url(root)
    table = section('schedule') if table is None else table
    runs = list(forgerun.live(repo)) if seat is not None else []
    slurm, standing, why = standing_of(cluster) if seat is not None else (None, None, '')
    try:
        ticked = tick(
            root, mode, client=client, machine=machine, seat=seat, lease=lease, fetch=fetch, host=host,
            in_flight=bool(runs), headroom=standing.headroom if standing else box_room(),
            usage=standing.usage if standing else None, weights=host_weights(table),
        )  # fmt: skip
    except ForgeCallFailed as failed:
        if failed.report.attempts and failed.report.attempts[-1].returncode in _forge.AUTH_REFUSED:
            alarm(
                Alarm(AUTH, repo, f'the forge refused the stored credential on {machine or "this host"}', str(failed))
            )
        raise
    for line in ticked.lines:
        say(line)
    if slurm is not None:
        runs = forgerun.supersede_moved(root, runs, client=client(root), cluster=slurm, say=say)
    every = lease.total_seconds() / 3 if renew_s is None else renew_s
    produced: list[Produced] = []
    for item in ticked.claimed:
        if item.cluster is not None and item.holder is not None:
            runs.append(forgerun.start(item, item.holder))
        else:
            produced.append(
                _produce(
                    root,
                    item,
                    client=client,
                    spawn=spawn,
                    clock=clock,
                    say=say,
                    lease=lease,
                    renew_s=every,
                    fetch=fetch,
                )
            )
    left = _advance(
        root, runs, client=client, machine=machine, seat=seat, lease=lease, slurm=slurm, why=why, say=say, alarm=alarm
    )
    pending = [item for item in ticked.work if item.state in {OPEN, STALE}]
    if mode != 'quiet' and pending and not ticked.claimed and not left:
        refused = '; '.join(ticked.refused) or 'nothing was claimed'
        named = ', '.join(f'{item.ref} {item.sha[:12]}' for item in pending)
        alarm(Alarm(IDLE, repo, f'{machine or "this host"} is idle with work pending', f'{named}: {refused}'))
    for one in starved_alarms(ticked.queue, load_schedule(root), repo):
        alarm(one)
    if mode != 'quiet':
        publish_card(root, ticked.queue, ticked.claimed, client=client, machine=machine, seat=seat, host=host,
                     standing=standing, table=table, say=say)  # fmt: skip
    broken = tuple(
        f'{p.platform} {p.sha[:12]}: the producer refused its argv: {" ".join(p.argv)}'
        for p in produced
        if p.returncode == ProducerExit.USAGE
    )
    published = tuple(flush(root, client=client))
    return ServeReport(tuple(ticked.lines), tuple(produced), tuple(left), published, broken)


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


def _pump(stream: Iterable[str], platform: str, say: Callable[[str], None]) -> None:
    for line in stream:
        say(f'[{platform}] {line.rstrip()}')


def _produce(
    root: Path,
    item: Work,
    *,
    client: Callable[[Path], Client],
    spawn: Callable[..., Any],
    clock: Callable[[], datetime],
    say: Callable[[str], None],
    lease: timedelta,
    renew_s: float,
    fetch: Callable[[Path], None] = fetch_origin,
) -> Produced:
    """Run one local part's argv, streaming it and holding its claim alive; release a claim it left pending.

    At each heartbeat the ref is re-read from ``origin``: a ref that moved on stops the producer, and its
    claim is released ``superseded by <sha>``.
    """
    context = part_context(item.platform)
    say(f'[{item.platform}] start: {" ".join(item.argv)}')
    proc = spawn(
        list(item.argv),
        cwd=root,
        env=os.environ | producing(context, item.sha),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        errors='replace',
    )
    pump = threading.Thread(target=_pump, args=(proc.stdout, item.platform, say), daemon=True)
    pump.start()
    started = clock()
    superseded = ''
    while True:
        try:
            returncode = proc.wait(timeout=renew_s)
            break
        except subprocess.TimeoutExpired:
            if (clock() - started).total_seconds() > PRODUCE_WALL_S:
                proc.kill()
                returncode = proc.wait()
                say(f'[{item.platform}] killed: past the {PRODUCE_WALL_S} s wall')
                break
            fetch(root)
            tip = tip_of(root, item.ref)
            if tip and tip != item.sha:
                proc.kill()
                returncode = proc.wait()
                superseded = tip
                say(f'[{item.platform}] stopped: {item.ref} moved on to {tip[:12]}')
                break
            if item.holder is not None:  # the heartbeat: the same claim, until the FORGE's time plus the lease
                built = client(root)
                try:
                    renewed = dataclasses.replace(item.holder, until=forge_now(built) + lease)
                except (ForgeCallFailed, OSError) as failed:
                    say(f'[{item.platform}] could not read the forge clock to renew: {failed}')
                    continue
                _post(built, item, 'pending', renewed.description(), say)
    pump.join(timeout=5)
    say(f'[{item.platform}] exit={returncode}')
    posts = [status for status in status_history(client(root), item.sha) if status.context == context]
    if superseded or (posts and posts[-1].state == 'pending'):
        reason = f'superseded by {superseded[:12]}' if superseded else release_reason(returncode)
        _post(client(root), item, 'error', reason, say)
    return Produced(item.ref, item.sha, item.platform, item.argv, returncode)


def _post(client: Client, item: Work, state: str, description: str, say: Callable[[str], None]) -> None:
    try:
        status_post(client, item.sha, context=part_context(item.platform), state=state, description=description)
    except ForgeCallFailed as failed:  # a missed heartbeat is not a dead producer; say so and keep going
        say(f'[{item.platform}] could not post {state}: {failed}')
    else:
        say(f'[{item.platform}] {state}: {description}')


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    transport: Transport = https_transport,
    seat_of: Callable[[], ClusterAccount | None] = this_seat,
) -> int:
    """``serve --mode integrate|develop|quiet [--json]``: 0 served, 1 forge or run state failed, 2 contract broke."""
    parser = argparse.ArgumentParser(prog='lab_commons.dev.forge serve', description=__doc__.splitlines()[0])
    parser.add_argument('--mode', required=True, choices=MODES, help='which refs this checkout serves')
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
            args.mode,
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
