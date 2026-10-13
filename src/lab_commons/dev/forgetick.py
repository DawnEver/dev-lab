"""REQUESTS through the forge -- ``python -m lab_commons.dev.forge tick``, the call any harness tick makes.

ORIGIN IS THE TRIGGER (forge plan, user rulings 2026-10-09). There is no request object: a pushed ref
whose tip lacks a ``tests/<platform>`` part IS the request for that part. Which refs a checkout serves
is its MODE: ``integrate`` serves the integration branch, its PRs, opted-in branches and requests,
``develop`` the lanes (named by the repo's ``[tool.lab_commons.integrator]``), ``quiet`` serves nothing.
A part is claimed as a pending status with a lease (:mod:`lab_commons.dev.forgeclaim`).

WHAT A TICK DOES, in order: flush the status outbox (:mod:`lab_commons.dev.forgeoutbox`), stop if
``quiet``, fetch ``origin``, rank every candidate this box could serve (:mod:`lab_commons.dev.forgeschedule`:
value per cost, each waiting one naming why), CLAIM IN RANK ORDER WHILE JOBS ADMIT
(:func:`lab_commons.compute.model.admit`), and give each claimed part what produces it: a local argv as
the claimed commit declares it (:func:`lab_commons.dev.platformparts.part_argv`; the producer runs it in
a tree at that commit) or a cluster part (:func:`lab_commons.dev.platformparts.cluster_part`). A part
whose producer the repo does not declare is not claimed; its refusal names the pyproject key to add. A
cluster host whose rclone remote is unusable (:func:`lab_commons.dev.artefacts.remote_problem`) claims
no part with declared outputs -- they could exceed ``threshold_mb`` -- and says why; a part with none is
still claimed. It runs nothing itself.

ADMISSION, NOT ONE CLAIM A TICK. Each candidate is a :class:`~lab_commons.compute.model.Job` whose
demand is what its last run measured (:func:`~lab_commons.compute.learned.learned_demand`); it is admitted when it fits
this host's supply less others' reservations and less everything already RUNNING -- the runs in flight
here, an interactive run holding the box seat, and every part this tick claimed before it. A job that
does not fit is skipped and a smaller lower-ranked one is still claimed; the skipped one waits naming
the resources it lacks (``not admitted: lacking cpu``). Several parts may therefore run on one host at
once. Two parts of ONE sha are never claimed by one box in one tick: a local part is judged in its
sha's tree (:mod:`lab_commons.dev.shatree`), and one tree serves one producer.

A BOX JOB'S WIDTH FOLLOWS ITS BOX. A box run spreads over the cores it is given
(:func:`lab_commons.dev.bounded.worker_width`), so its cpu demand is capped at the box's supply: a job
that measured the whole box is admitted alone, and never starved by a core the own reserve keeps back.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Final

from lab_commons.compute.learned import learned, learned_demand
from lab_commons.compute.model import (
    Candidate,
    Ranked,
    Reservation,
    Resources,
    Supply,
    expected_cost,
    fitted,
    rank,
)
from lab_commons.dev.artefacts import remote_problem
from lab_commons.dev.forge import (
    NoCredential,
    Transport,
    UnreadableRemote,
    fetch_origin,
    https_transport,
)
from lab_commons.dev.forgeclaim import (
    DEFAULT_LEASE,
    Claim,
    Work,
    forge_now,
    serving,
    this_machine,
    this_seat,
)
from lab_commons.dev.forgeoutbox import PostFailed, flush, unprompted_client
from lab_commons.dev.forgeprovides import declared_parts, served_parts
from lab_commons.dev.forgeschedule import (
    candidates,
    load_schedule,
    repo_name,
    vouched,
)
from lab_commons.dev.forgetake import ClaimPass
from lab_commons.dev.forgework import Client, ForgeCallFailed, client_for
from lab_commons.dev.lanepolicy import load_policy
from lab_commons.dev.platformparts import (
    origin_url,
    part_context,
    this_platform,
)
from lab_commons.hpc.account import ClusterAccount
from lab_commons.log import emit

__all__ = ['MODES', 'TickReport', 'main', 'tick']

MODES: Final = ('integrate', 'develop', 'quiet')


@dataclass(frozen=True)
class TickReport:
    """What a tick saw and did: every request with its state, the ones it claimed, its lines, and the queue.

    *queue* is every candidate still waiting, ranked, each naming what blocks it (:mod:`forgeschedule`).
    """

    work: tuple[Work, ...]
    claimed: tuple[Work, ...]
    lines: tuple[str, ...]
    refused: tuple[str, ...] = ()
    queue: tuple[Ranked, ...] = ()
    #: Why this host cannot write the large artefact store, ``''`` when it can (stated on its host card).
    artefacts: str = ''


def tick(
    root: Path,
    mode: str,
    *,
    client: Callable[[Path], Client],
    machine: str,
    seat: ClusterAccount | None,
    lease: timedelta = DEFAULT_LEASE,
    dry_run: bool = False,
    fetch: Callable[[Path], None] = fetch_origin,
    host: str | None = None,
    supply: Supply | None = None,
    reservations: Sequence[Reservation] = (),
    running: Sequence[Mapping[str, float]] = (),
    demand: Callable[[Candidate, frozenset[str]], Mapping[str, float]] | None = None,
    usage: Mapping[str, float] | None = None,
    weights: Mapping[str, float] | None = None,
    measured: Mapping[str, Any] | None = None,
    probe: Callable[[Path], str] = remote_problem,
    provides: Mapping[str, Any] | None = None,
    owners: Mapping[str, Collection[str]] | None = None,
) -> TickReport:
    """One tick, in the order the module docstring gives: claim in rank order while jobs admit.

    *supply* is what this host or account has now (:mod:`lab_commons.compute.probe`; default: a box's
    cores); *reservations* the ledger's leases (:mod:`lab_commons.compute.ledger`; one on another scope,
    expired, or for the job itself withholds nothing); *running* the demands already running here;
    *demand* a candidate's size (default: what it measured); *usage* the core-hours each run sha12 used
    in the last day (a cluster's ``sacct``; ``None`` meters nothing, so no budget binds);
    *weights* this host's per-repo multipliers; *measured* the repository's last run measurements
    (default: :func:`lab_commons.compute.learned.learned`). *probe* says why a cluster host cannot write the
    repo's large artefact store (default: :func:`lab_commons.dev.artefacts.remote_problem`). *provides* is
    this host's machine-file ``[capabilities]`` (:mod:`lab_commons.dev.forgeprovides`; none by default): it
    adds the engine parts it serves and blocks a part needing what it lacks. *owners* is who may vouch for
    each host card (host -> its login and delegates; :class:`lab_commons.compute.ledger.Ledger`): a job's
    ORIGIN host stands only where its forge-recorded login is one of them, and a job a live lease on this
    host is for ranks FIRST here.
    """
    if mode not in MODES:
        msg = f'a mode is one of {MODES}, not {mode!r}'
        raise ValueError(msg)
    lines: list[str] = []
    try:
        lines += flush(root, client=client)
    except PostFailed as failed:
        lines += str(failed).splitlines()
    if mode == 'quiet':
        lines.append('tick: quiet -- this checkout serves nothing')
        return TickReport((), (), tuple(lines))
    fetch(root)
    built = client(root)
    login = built.whoami()
    now = forge_now(built)
    serve = serving(host or this_platform(), seat)
    me = Claim(machine, login, now + lease, serve.hpc)
    schedule, repo = load_schedule(root), repo_name(built)
    found = vouched(
        candidates(
            root,
            mode,
            built,
            repo=repo,
            platforms=served_parts(serve.platform, provides or {}, declared_parts(root), cluster=bool(serve.hpc)),
            schedule=schedule,
            policy=load_policy(root),
            now=now,
            say=lines.append,
        ),
        owners or {},
    )
    cores = 1 if serve.hpc else os.cpu_count() or 1
    learned_now = learned(origin_url(root)) if measured is None else measured
    cost = expected_cost(learned_now, schedule.prior_cost_h, cores=cores)
    room = supply or Supply(machine or 'this host', Resources(cpu=cores))
    by_part = learned_demand(origin_url(root), cluster=bool(serve.hpc), cores=cores)
    sized = demand or (lambda wanted, needed: by_part(wanted.platform, needed))
    taken = ClaimPass(
        root, built, serve, me, now, schedule, usage, dry_run, repo=repo, supply=room,
        size=lambda wanted, needed: fitted(sized(wanted, needed), room, cluster=bool(serve.hpc)),
        reservations=tuple(reservations), taken=list(running),
        store_why=probe(root) if serve.hpc else '', provides=provides or {},
    )  # fmt: skip
    ranked = rank(found, {repo: schedule}, now, cost_h={repo: cost}, weights=weights, reserved=taken.reserved)
    for item in ranked:
        taken.consider(item)
    work, claimed, refused, queue = taken.work, taken.claimed, taken.refused, taken.queue
    for item in work:
        who = f' by {item.holder.login}@{item.holder.machine or "-"}' if item.holder else ''
        lines.append(f'{item.state:<7} {part_context(item.platform):<14} {item.ref}  {item.sha[:12]}{who}')
    for item in claimed:
        how = f'a cluster run as {serve.hpc}' if item.cluster else shlex.join(item.argv)
        lines.append(f'produce {part_context(item.platform)}: {how}')
    lines += [f'refused {reason}' for reason in refused]
    lines += [f'waiting {item.candidate.key}: {item.blocked}' for item in queue if item.blocked]
    lines += [f'artefacts {taken.store_why}'] if taken.store_why else []
    return TickReport(tuple(work), tuple(claimed), tuple(lines), tuple(refused), tuple(queue), taken.store_why)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='lab_commons.dev.forge tick', description=__doc__.splitlines()[0])
    parser.add_argument('--mode', required=True, choices=MODES, help='which refs this checkout serves')
    parser.add_argument('--dry-run', action='store_true', help='list the requests and their state; claim nothing')
    parser.add_argument(
        '--lease-hours', type=float, default=DEFAULT_LEASE.total_seconds() / 3600, help='how long a claim holds'
    )
    parser.add_argument('--json', action='store_true', help='print every request and what was claimed as JSON')
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    transport: Transport = https_transport,
    fetch: Callable[[Path], None] = fetch_origin,
    seat_of: Callable[[], ClusterAccount | None] = this_seat,
    host: str | None = None,
) -> int:
    """``tick --mode integrate|develop|quiet [--dry-run] [--lease-hours H] [--json]``; exit 1 when the forge fails."""
    args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd() if cwd is None else cwd

    def build(here: Path) -> Client:
        return client_for(here, env=env, transport=transport) if env is not None else unprompted_client(here)

    seat = seat_of()
    try:
        report = tick(
            root,
            args.mode,
            client=build,
            machine=this_machine(seat),
            seat=seat,
            lease=timedelta(hours=args.lease_hours),
            dry_run=args.dry_run,
            fetch=fetch,
            host=host,
        )
    except (ForgeCallFailed, NoCredential, UnreadableRemote, OSError) as failed:
        emit(f'[tick] {failed}', err=True)
        return 1
    if args.json:
        payload = {
            'work': [
                {'ref': item.ref, 'sha': item.sha, 'platform': item.platform, 'state': item.state}
                | {'holder': item.holder.description() if item.holder else None}
                for item in report.work
            ],
            'claimed': [
                {'ref': item.ref, 'sha': item.sha, 'platform': item.platform, 'argv': list(item.argv)}
                for item in report.claimed
            ],
            'refused': list(report.refused),
        }
        emit(json.dumps(payload, indent=2))
    else:
        for line in report.lines:
            emit(line)
    return 0
