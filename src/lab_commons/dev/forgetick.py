"""REQUESTS through the forge -- ``python -m lab_commons.dev.forge tick``, the call any harness tick makes.

ORIGIN IS THE TRIGGER (forge plan, user rulings 2026-10-09). There is no request object: a pushed ref
whose tip lacks a ``tests/<part>`` part IS the request for that part; which parts a tip needs is
DERIVED (:func:`lab_commons.dev.platformparts.derived`): ``base``, and every part a posted part hands to.
EVERY HOST SERVES EVERY CANDIDATE CLASS from one queue -- the integration branch, its PRs, every child
branch the schedule's rule classes, and requests (:mod:`lab_commons.dev.forgeschedule`); the rank orders
it and the admission fits it.
A part is claimed as a pending status with a lease (:mod:`lab_commons.dev.forgeclaim`).

WHAT A TICK DOES, in order: flush the status outbox (:mod:`lab_commons.dev.forgeoutbox`), fetch
``origin``, rank every candidate this box could serve (:mod:`lab_commons.dev.forgeschedule`:
value per cost, each waiting one naming why), CLAIM IN RANK ORDER WHILE JOBS ADMIT
(:func:`lab_commons.compute.admission.admit`: the part's need-set present here, its demand within the supply),
and give each claimed part what produces it: the ONE producer the claimed commit declares
(:func:`lab_commons.dev.platformparts.producer_argv`, ``{part}`` filled; the producer runs it in a tree at
that commit) or a cluster part (:func:`lab_commons.dev.platformparts.cluster_part`). A part
whose producer the repo does not declare is not claimed; its refusal names the pyproject key to add. A
cluster host whose rclone remote is unusable (:func:`lab_commons.dev.artefacts.remote_problem`) claims
no part with declared outputs -- they could exceed ``threshold_mb`` -- and says why; a part with none is
still claimed. It runs nothing itself.

ADMISSION, NOT ONE CLAIM A TICK. Each candidate is a :class:`~lab_commons.compute.model.Job` whose
demand is what its last run of ``(producer, need-set)`` measured; it is admitted when it fits this host's
supply less everything already RUNNING -- on a box, the supply IS what the box ledger can still admit
(:func:`lab_commons.compute.probe.box`), so every claim on it is already subtracted -- and less every part
this tick claimed before it. A job that
does not fit is skipped and a smaller lower-ranked one is still claimed; the skipped one waits naming
the resources it lacks (``not admitted: lacking cpu``). Several parts may therefore run on one host at
once. Two parts of ONE sha are never claimed by one box in one tick: a local part is judged in its
sha's tree (:mod:`lab_commons.dev.shatree`), and one tree serves one producer.

PRIORITY IS ORDERING (:mod:`lab_commons.compute.priority`): a job this host's ``[priority]`` names is
considered before every other; it takes no supply and preempts nothing.

A JOB'S DEMAND IS WHAT IT MEASURED. A BOX part is admitted at exactly what it will declare to the box
(:func:`~lab_commons.compute.learned.box_demand`: the cores it kept busy and its peak with headroom, else
the whole box), so the admission and the box's enforced claim are one number. A CLUSTER part asks what its
last Slurm run measured (:func:`~lab_commons.compute.learned.cluster_demand`).
Where the supply counts ``submits`` (a cluster account), a claim takes one.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from lab_commons.box import GB, Capacity
from lab_commons.compute import probe
from lab_commons.compute.learned import box_demand, cluster_demand, learned, request_demand
from lab_commons.compute.model import (
    REQUEST,
    Candidate,
    Ranked,
    Resources,
    Supply,
    expected_cost,
    rank,
    submitted,
)
from lab_commons.compute.priority import PRIORITY_TABLE, Priority
from lab_commons.config import section
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
from lab_commons.dev.forgerequest import declared_request
from lab_commons.dev.forgeschedule import candidates, load_schedule, repo_name, vouched
from lab_commons.dev.forgestatus import Status, status_history
from lab_commons.dev.forgetake import ClaimPass
from lab_commons.dev.forgework import Client, ForgeCallFailed, client_for
from lab_commons.dev.lanepolicy import load_policy
from lab_commons.dev.platformparts import derived, origin_url, this_platform
from lab_commons.hpc.account import ClusterAccount
from lab_commons.hpc.config import Cost
from lab_commons.log import emit

__all__ = ['TickReport', 'main', 'tick']


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
    #: The open parts this host could serve -- its needs all present here -- and did not claim: what makes it idle.
    pending: tuple[Work, ...] = ()


def tick(
    root: Path,
    *,
    client: Callable[[Path], Client],
    machine: str,
    seat: ClusterAccount | None,
    lease: timedelta = DEFAULT_LEASE,
    dry_run: bool = False,
    fetch: Callable[[Path], None] = fetch_origin,
    host: str | None = None,
    supply: Supply | None = None,
    running: Sequence[Mapping[str, float]] = (),
    demand: Callable[[Candidate, frozenset[str]], Mapping[str, float]] | None = None,
    usage: Mapping[str, float] | None = None,
    weights: Mapping[str, float] | None = None,
    measured: Mapping[str, Any] | None = None,
    probe: Callable[[Path], str] = remote_problem,
    busy: Iterable[str] = (),
    owners: Mapping[str, Collection[str]] | None = None,
    priority: Priority | None = None,
) -> TickReport:
    """One tick, in the order the module docstring gives: claim in rank order while jobs admit.

    *supply* is what this host or account has now (:mod:`lab_commons.compute.probe`; default: a box's
    whole capacity); *running* what already runs here and is not in *supply* (a cluster run in flight);
    *demand* a candidate's size (default: what it measured); *usage* the core-hours each run sha12 used
    in the last day (a cluster's ``sacct``; ``None`` meters nothing, so no budget binds);
    *weights* this host's per-repo multipliers; *measured* the repository's last run measurements
    (default: :func:`lab_commons.compute.learned.learned`). *probe* says why a cluster host cannot write the
    repo's large artefact store (default: :func:`lab_commons.dev.artefacts.remote_problem`). Which resources
    this host has is *supply*'s ``present`` (:mod:`lab_commons.compute.probe`): a part whose need-set is not
    all present waits ``not admitted: lacking <resource>``. *busy* are the shas a producer
    here is judging now: their trees are taken, so no part of them is claimed. *owners* is who may vouch
    for each host card (host -> the login that publishes it): a job's ORIGIN host stands only where its
    forge-recorded login is one of them (:func:`lab_commons.dev.forgeschedule.vouched`). *priority* is this
    host's declared ordering (default: its machine file's ``[priority]``, :mod:`lab_commons.compute.priority`):
    a matching candidate is considered before every other, and nothing is set aside for it.
    """
    lines: list[str] = []
    try:
        lines += flush(root, client=client)
    except PostFailed as failed:
        lines += str(failed).splitlines()
    fetch(root)
    built = client(root)
    histories: dict[str, tuple[Status, ...]] = {}  # one read per sha: it derives the parts and assesses each

    def history(sha: str) -> tuple[Status, ...]:
        if sha not in histories:
            histories[sha] = status_history(built, sha)
        return histories[sha]

    login = built.whoami()
    now = forge_now(built)
    serve = serving(host or this_platform(), seat)
    me = Claim(machine, login, now + lease, serve.hpc)
    schedule, repo = load_schedule(root), repo_name(built)
    found = vouched(
        candidates(
            root,
            built,
            repo=repo,
            parts=lambda sha: derived(history(sha)),
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
    room = supply or _whole(machine or 'this host', cluster=bool(serve.hpc))
    sized = demand or _demand_of(root, cluster=bool(serve.hpc))
    taken = ClaimPass(
        root, built, serve, me, now, schedule, usage, dry_run, repo=repo, supply=room,
        size=lambda wanted, needed: submitted(sized(wanted, needed), room),
        taken=list(running), trees=set(busy), store_why=probe(root) if serve.hpc else '', history=history,
    )  # fmt: skip
    ranked = rank(found, {repo: schedule}, now, cost_h={repo: cost}, weights=weights,
        priority=(priority or Priority.of(section(PRIORITY_TABLE))).matches,
    )  # fmt: skip
    for item in ranked:
        taken.consider(item)
    work, claimed, refused, queue = taken.work, taken.claimed, taken.refused, taken.queue
    for item in work:
        who = f' by {item.holder.login}@{item.holder.machine or "-"}' if item.holder else ''
        lines.append(f'{item.state:<7} {item.context:<14} {item.ref}  {item.sha[:12]}{who}')
    for item in claimed:
        how = f'a cluster run as {serve.hpc}' if item.cluster else shlex.join(item.argv)
        lines.append(f'produce {item.context}: {how}')
    lines += [f'refused {reason}' for reason in refused]
    lines += [f'waiting {item.candidate.key}: {item.blocked}' for item in queue if item.blocked]
    lines += [f'artefacts {taken.store_why}'] if taken.store_why else []
    return TickReport(
        tuple(work),
        tuple(claimed),
        tuple(lines),
        tuple(refused),
        tuple(queue),
        taken.store_why,
        tuple(taken.pending),
    )


def _whole(scope: str, *, cluster: bool) -> Supply:
    """A tick given no supply: one default task of an account, else this box's whole capacity.

    The task is :class:`~lab_commons.hpc.config.Cost`'s defaults, the floor every cluster demand asks; the box's
    is :class:`~lab_commons.box.Capacity`.
    """
    one = Cost()
    task = Resources(cpu=one.cpus, mem_gb=one.mem_gb)
    return Supply(scope, task) if cluster else probe.box(scope, capacity=Capacity.read())


def _demand_of(root: Path, *, cluster: bool) -> Callable[[Candidate, frozenset[str]], Mapping[str, float]]:
    """A candidate's demand: a cluster part's measured ask, else what it will declare to this box.

    A box REQUEST is sized by its own row (:func:`~lab_commons.compute.learned.request_demand`), a box part
    by :func:`~lab_commons.compute.learned.box_demand`.
    """
    repo_url = origin_url(root)
    if cluster:
        asked = cluster_demand(repo_url)
        return lambda _wanted, needed: asked(needed)
    capacity = Capacity.read()

    def sized(wanted: Candidate, needed: frozenset[str]) -> Mapping[str, float]:
        if wanted.kind == REQUEST:
            row = declared_request(root, wanted.sha, wanted.producer)
            return request_demand(repo_url, row.name, needed, cpu=row.cpu, mem_gb=row.mem_gb)
        return box_demand(repo_url, needed, cpu=capacity.cpu, mem_gb=capacity.mem_bytes / GB)

    return sized


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='lab_commons.dev.forge tick', description=__doc__.splitlines()[0])
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
    """``tick [--dry-run] [--lease-hours H] [--json]``; exit 1 when the forge fails."""
    args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd() if cwd is None else cwd

    def build(here: Path) -> Client:
        return client_for(here, env=env, transport=transport) if env is not None else unprompted_client(here)

    seat = seat_of()
    try:
        report = tick(
            root,
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
