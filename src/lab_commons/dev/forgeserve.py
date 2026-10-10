"""THE HARNESS ENTRY -- ``python -m lab_commons.dev.forge serve --mode M``, one call that serves a checkout.

ONE SOURCE FOR THE PROTOCOL. A harness used to restate the forge protocol step by step -- tick, run the
claimed argv, watch, publish, route -- and with it this family's venv layout and output tree, so every
protocol change needed a matching harness commit (audit 2026-10-10, item 4). This module owns the
sequence; a harness keeps only scheduling, locking, mode storage and notification, and calls this.

THE SEQUENCE, in order: :func:`lab_commons.dev.forgetick.tick` (flush the outbox, fetch, claim at most
one part per platform with the argv producing it); run each claimed argv in the checkout -- a cluster
part's argv submits, waits and posts by itself, a local part's runner posts its own part; flush the
outbox again; route every run record a cluster part wrote (:mod:`lab_commons.dev.forgeroute`).

A CONTRACT BREAK FAILS LOUDLY. A produced argv exiting 2 -- argparse's usage error, which is what a
renamed flag or verb looks like -- is a FAILURE of this call (exit 2) with the argv shown, never a
quiet skip. A part that ran and is red is not a failure of the harness: it is a posted FAIL part.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

from lab_commons.dev.forge import Transport, fetch_origin, https_transport
from lab_commons.dev.forgeoutbox import PostFailed, flush, unprompted_client
from lab_commons.dev.forgeroute import pyproject_at, route
from lab_commons.dev.forgetick import DEFAULT_LEASE, MODES, Work, tick
from lab_commons.dev.forgework import Client, ForgeCallFailed, client_for
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
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> ServeReport:
    """Tick, produce every claimed part, publish, route -- the module docstring's order."""
    ticked = tick(root, mode, client=client, now=now, machine=machine, grants=grants, lease=lease, fetch=fetch)
    produced: list[Produced] = []
    broken: list[str] = []
    for item in ticked.claimed:
        produced.append(_produce(root, item, client=client, run=run))
        if produced[-1].returncode == USAGE_ERROR:
            broken.append(f'{item.platform} {item.sha[:12]}: the producer refused its argv: {" ".join(item.argv)}')
    published = tuple(flush(root, client=client))
    return ServeReport(tuple(ticked.lines), tuple(produced), published, tuple(broken))


def _produce(
    root: Path, item: Work, *, client: Callable[[Path], Client], run: Callable[..., subprocess.CompletedProcess[str]]
) -> Produced:
    done = run(list(item.argv), cwd=root, check=False, timeout=PRODUCE_WALL_S)
    routed: list[str] = []
    for path in _records(item.argv, item.sha):
        record = read_record(path)
        found = route(client(root), record, pyproject_at(root, record['sha']))
        routed.extend(f'{one.area} {one.action}' + (f' #{one.number}' if one.number else '') for one in found)
    return Produced(item.ref, item.sha, item.platform, item.argv, done.returncode, tuple(routed))


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
        )
    except (ForgeCallFailed, PostFailed, OSError) as failed:
        emit(f'[serve] {failed}', err=True)
        return 1
    if args.json:
        emit(json.dumps(asdict(report), indent=2))
    else:
        for line in (
            *report.tick,
            *(f'produced {p.platform} {p.sha[:12]} exit={p.returncode}' for p in report.produced),
        ):
            emit(line)
        for line in (*report.published, *(f'routed {r}' for p in report.produced for r in p.routed)):
            emit(line)
    for line in report.broken:
        emit(f'[serve] CONTRACT BROKEN -- {line}', err=True)
    return USAGE_ERROR if report.broken else 0
