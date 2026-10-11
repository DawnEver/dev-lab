"""THE HARNESS ENTRY -- ``python -m lab_commons.dev.forge serve --mode M``, one call that serves a checkout.

ONE SOURCE FOR THE PROTOCOL. A harness used to restate the forge protocol step by step -- tick, run the
claimed argv, watch, publish, route -- and with it this family's venv layout and output tree, so every
protocol change needed a matching harness commit (audit 2026-10-10, item 4). This module owns the
sequence; a harness keeps only scheduling, locking, mode storage and notification, and calls this.

THE SEQUENCE, in order: :func:`lab_commons.dev.forgetick.tick` (flush the outbox, fetch, claim at most
one part per platform with the argv producing it); run each claimed argv in the checkout -- a cluster
part's argv submits, waits and posts by itself, a local part's runner posts its own part; flush the
outbox again; route every run record a cluster part wrote (:mod:`lab_commons.dev.forgeroute`).

PARTS ON DIFFERENT SEATS RUN AT ONCE (live finding 2026-10-11: a windows full part ran for hours while
the linux cluster part, using no local CPU, sat unsubmitted and its claim aged). A part's seat is its
cluster grant or this box's CPU; seats run concurrently, parts on one seat in turn. Every producer's
output streams as it comes, prefixed ``[platform]``, so a long part never looks dead. WHILE A PRODUCER
LIVES ITS CLAIM IS RENEWED -- the same pending claim re-posted with a new ``until`` every third of the
lease -- and when it ends with its context still pending (it crashed before posting) the claim is
RELEASED as ``error`` naming the exit code, so nobody waits out a lease for a dead producer.

A CONTRACT BREAK FAILS LOUDLY. A produced argv exiting 2 -- argparse's usage error, which is what a
renamed flag or verb looks like -- is a FAILURE of this call (exit 2) with the argv shown, never a
quiet skip. A part that ran and is red is not a failure of the harness: it is a posted FAIL part.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import subprocess
import sys
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from lab_commons.dev.forge import Transport, fetch_origin, https_transport
from lab_commons.dev.forgeoutbox import PostFailed, flush, unprompted_client
from lab_commons.dev.forgeroute import pyproject_at, route
from lab_commons.dev.forgestatus import status_history, status_post
from lab_commons.dev.forgetick import DEFAULT_LEASE, MODES, Work, tick
from lab_commons.dev.forgework import Client, ForgeCallFailed, client_for
from lab_commons.dev.platformparts import part_context
from lab_commons.hpc.grants import Grant, load_grants, workstation
from lab_commons.hpc.records import read_record
from lab_commons.log import emit

__all__ = ['USAGE_ERROR', 'Produced', 'ServeReport', 'main', 'serve']

#: argparse's exit code for a usage error: a produced argv the producer no longer understands.
USAGE_ERROR: Final = 2

#: How long a produced part may run before it is called hung, in seconds: a cluster part waits for its jobs.
PRODUCE_WALL_S: Final = 24 * 3600


@dataclass(frozen=True)
class Produced:
    """One claimed part and what producing it did."""

    ref: str
    sha: str
    platform: str
    argv: tuple[str, ...]
    returncode: int
    routed: tuple[str, ...] = ()


@dataclass(frozen=True)
class ServeReport:
    """The tick's lines, every part produced, the outbox flush and whether a contract broke."""

    tick: tuple[str, ...]
    produced: tuple[Produced, ...]
    published: tuple[str, ...]
    broken: tuple[str, ...]


def _records(argv: Sequence[str], sha: str) -> tuple[Path, ...]:
    """The run records a cluster part's argv wrote: ``run-<sha>-*`` under its ``-o`` directory."""
    if '-o' not in argv:
        return ()
    directory = Path(argv[list(argv).index('-o') + 1])
    return tuple(sorted(directory.glob(f'run-{sha}-*.json.gz'))) if directory.is_dir() else ()


def serve(
    root: Path,
    mode: str,
    *,
    client: Callable[[Path], Client],
    now: datetime,
    machine: str,
    grants: Sequence[Grant],
    lease: timedelta = DEFAULT_LEASE,
    fetch: Callable[[Path], None] = fetch_origin,
    spawn: Callable[..., Any] = subprocess.Popen,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    say: Callable[[str], None] = emit,
    renew_s: float | None = None,
) -> ServeReport:
    """Tick, produce every claimed part, publish, route -- the module docstring's order.

    Parts on different seats (:func:`_seat`) run CONCURRENTLY, parts sharing one run in turn. Each
    producer's output streams through *say* prefixed ``[platform]``; its claim is renewed every
    *renew_s* (a third of the lease by default) while it lives, and released when it ends still pending.
    """
    ticked = tick(root, mode, client=client, now=now, machine=machine, grants=grants, lease=lease, fetch=fetch)
    for line in ticked.lines:
        say(line)
    every = lease.total_seconds() / 3 if renew_s is None else renew_s
    seats: dict[str, list[int]] = {}
    for index, item in enumerate(ticked.claimed):
        seats.setdefault(_seat(item), []).append(index)
    done: dict[int, Produced] = {}

    def one_seat(indices: list[int]) -> None:
        for index in indices:
            done[index] = _produce(
                root,
                ticked.claimed[index],
                client=client,
                spawn=spawn,
                clock=clock,
                say=say,
                lease=lease,
                renew_s=every,
            )

    threads = [threading.Thread(target=one_seat, args=(indices,), daemon=True) for indices in seats.values()]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    produced = tuple(done[index] for index in sorted(done))
    broken = tuple(
        f'{p.platform} {p.sha[:12]}: the producer refused its argv: {" ".join(p.argv)}'
        for p in produced
        if p.returncode == USAGE_ERROR
    )
    published = tuple(flush(root, client=client))
    return ServeReport(tuple(ticked.lines), produced, published, broken)


def _seat(item: Work) -> str:
    """The resource a part occupies: its cluster grant, or this box's CPU when it runs here."""
    return f'hpc:{item.holder.hpc}' if item.holder is not None and item.holder.hpc else 'local'


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
) -> Produced:
    """Run one part's argv, streaming it and holding its claim alive; release a claim it left pending."""
    context = part_context(item.platform)
    say(f'[{item.platform}] start: {" ".join(item.argv)}')
    proc = spawn(
        list(item.argv),
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        errors='replace',
    )
    pump = threading.Thread(target=_pump, args=(proc.stdout, item.platform, say), daemon=True)
    pump.start()
    started = clock()
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
            if item.holder is not None:  # the heartbeat: the same claim, a new until
                renewed = dataclasses.replace(item.holder, until=clock() + lease)
                _post(client(root), item, 'pending', renewed.description(), say)
    pump.join(timeout=5)
    say(f'[{item.platform}] exit={returncode}')
    posts = [status for status in status_history(client(root), item.sha) if status.context == context]
    if posts and posts[-1].state == 'pending':
        _post(client(root), item, 'error', f'released: producer exited {returncode}', say)
    routed: list[str] = []
    for path in _records(item.argv, item.sha):
        record = read_record(path)
        found = route(client(root), record, pyproject_at(root, record['sha']))
        routed.extend(f'{one.area} {one.action}' + (f' #{one.number}' if one.number else '') for one in found)
    return Produced(item.ref, item.sha, item.platform, item.argv, returncode, tuple(routed))


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
) -> int:
    """``serve --mode integrate|develop|quiet [--json]``: 0 served, 1 the forge failed, 2 a contract broke."""
    parser = argparse.ArgumentParser(prog='lab_commons.dev.forge serve', description=__doc__.splitlines()[0])
    parser.add_argument('--mode', required=True, choices=MODES, help='which refs this checkout serves')
    parser.add_argument('--lease-hours', type=float, default=DEFAULT_LEASE.total_seconds() / 3600)
    parser.add_argument('--json', action='store_true', help='print the whole report as JSON')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd() if cwd is None else cwd

    def build(here: Path) -> Client:
        return client_for(here, env=env, transport=transport) if env is not None else unprompted_client(here)

    try:
        grants = load_grants().grants
    except ValueError:
        grants = ()
    try:
        report = serve(
            root,
            args.mode,
            client=build,
            now=datetime.now(UTC),
            machine=workstation() or '',
            grants=grants,
            lease=timedelta(hours=args.lease_hours),
            say=lambda line: emit(line, err=args.json, flush=True),
        )
    except (ForgeCallFailed, PostFailed, OSError) as failed:
        emit(f'[serve] {failed}', err=True)
        return 1
    if args.json:
        emit(json.dumps(asdict(report), indent=2))
    else:
        for line in (*(f'produced {p.platform} {p.sha[:12]} exit={p.returncode}' for p in report.produced),):
            emit(line)
        for line in (*report.published, *(f'routed {r}' for p in report.produced for r in p.routed)):
            emit(line)
    for line in report.broken:
        emit(f'[serve] CONTRACT BROKEN -- {line}', err=True)
    return USAGE_ERROR if report.broken else 0
