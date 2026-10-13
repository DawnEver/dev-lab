"""REQUESTS through the forge -- ``python -m lab_commons.dev.forge tick``, the call any harness tick makes.

ORIGIN IS THE TRIGGER (forge plan, user rulings 2026-10-09). There is no request object: a pushed ref
whose tip lacks a ``tests/<part>`` part IS the request for that part; which parts a tip needs is
DERIVED (:func:`lab_commons.dev.platformparts.derived`): ``base``, and every part a posted part hands to.
EVERY HOST SERVES EVERY CANDIDATE CLASS from one queue -- the integration branch, its PRs, every child
branch the schedule's rule classes, and requests (:mod:`lab_commons.dev.forgeschedule`); the rank orders
it, the admission fits it, and a host that takes no foreign work is reserved whole by its owner.
A part is claimed as a pending status with a lease (:mod:`lab_commons.dev.forgeclaim`).

WHAT A TICK DOES, in order: flush the status outbox (:mod:`lab_commons.dev.forgeoutbox`), fetch
``origin``, rank every candidate this box could serve (:mod:`lab_commons.dev.forgeschedule`:
value per cost, each waiting one naming why), CLAIM IN RANK ORDER WHILE JOBS ADMIT
(:func:`lab_commons.compute.model.admit`: the part's need-set present here, its demand within the supply),
and give each claimed part what produces it: the ONE producer the claimed commit declares
(:func:`lab_commons.dev.platformparts.producer_argv`, ``{part}`` filled; the producer runs it in a tree at
that commit) or a cluster part (:func:`lab_commons.dev.platformparts.cluster_part`). A part
whose producer the repo does not declare is not claimed; its refusal names the pyproject key to add. A
cluster host whose rclone remote is unusable (:func:`lab_commons.dev.artefacts.remote_problem`) claims
no part with declared outputs -- they could exceed ``threshold_mb`` -- and says why; a part with none is
still claimed. It runs nothing itself.

ADMISSION, NOT ONE CLAIM A TICK. Each candidate is a :class:`~lab_commons.compute.model.Job` whose
demand is what its last run of ``(producer, need-set)`` measured
(:func:`~lab_commons.compute.learned.learned_demand`); it is admitted when it fits
this host's supply less others' reservations and less everything already RUNNING -- the runs in flight
here, an interactive run holding the box seat, and every part this tick claimed before it. A job that
does not fit is skipped and a smaller lower-ranked one is still claimed; the skipped one waits naming
the resources it lacks (``not admitted: lacking cpu``). Several parts may therefore run on one host at
once. Two parts of ONE sha are never claimed by one box in one tick: a local part is judged in its
sha's tree (:mod:`lab_commons.dev.shatree`), and one tree serves one producer.

A JOB'S DEMAND IS WHAT IT MEASURED. A box run's cpu is the cpu-seconds its process tree used over its
wall (:class:`lab_commons.proccpu.TreeCpu`), never capped to the box: a job that kept eight cores busy does
not fit in four. Unmeasured, it takes every core free now, so it is admitted alone.
Where the supply counts ``submits`` (a cluster account), a claim takes one.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import os
import shlex
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from lab_commons.compute.learned import learned, learned_demand
from lab_commons.compute.model import (
    REQUEST,
    Candidate,
    Job,
    Ranked,
    Reservation,
    Resources,
    Schedule,
    Supply,
    admit,
    expected_cost,
    rank,
    submitted,
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
    CLAIMABLE,
    DEFAULT_LEASE,
    MINE,
    Claim,
    Serving,
    Work,
    assess,
    claim,
    forge_now,
    serving,
    this_machine,
    this_seat,
)
from lab_commons.dev.forgeoutbox import PostFailed, flush, unprompted_client
from lab_commons.dev.forgeschedule import (
    NO_HOST,
    NOT_ADMITTED,
    candidates,
    load_schedule,
    over_budget,
    repo_name,
)
from lab_commons.dev.forgestatus import Status, status_history
from lab_commons.dev.forgework import Client, ForgeCallFailed, client_for
from lab_commons.dev.lanepolicy import load_policy
from lab_commons.dev.platformparts import (
    UndeclaredPart,
    cluster_part,
    derived,
    origin_url,
    part_context,
    producer_argv,
    this_platform,
)
from lab_commons.hpc.account import ClusterAccount
from lab_commons.hpc.needsets import Vocabulary, declared_at, needs_of
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
    reservations: Sequence[Reservation] = (),
    running: Sequence[Mapping[str, float]] = (),
    demand: Callable[[Candidate, frozenset[str]], Mapping[str, float]] | None = None,
    usage: Mapping[str, float] | None = None,
    weights: Mapping[str, float] | None = None,
    measured: Mapping[str, Any] | None = None,
    probe: Callable[[Path], str] = remote_problem,
    busy: Iterable[str] = (),
) -> TickReport:
    """One tick, in the order the module docstring gives: claim in rank order while jobs admit.

    *supply* is what this host or account has now (:mod:`lab_commons.compute.probe`; default: a box's
    cores); *reservations* the ledger's leases (:mod:`lab_commons.compute.ledger`; one on another scope,
    expired, or for the job itself withholds nothing); *running* the demands already running here;
    *demand* a candidate's size (default: what it measured); *usage* the core-hours each run sha12 used
    in the last day (a cluster's ``sacct``; ``None`` meters nothing, so no budget binds);
    *weights* this host's per-repo multipliers; *measured* the repository's last run measurements
    (default: :func:`lab_commons.compute.learned.learned`). *probe* says why a cluster host cannot write the
    repo's large artefact store (default: :func:`lab_commons.dev.artefacts.remote_problem`). Which resources
    this host has is *supply*'s ``present`` (:mod:`lab_commons.compute.probe`): a part whose need-set is not
    all present waits ``not admitted: lacking <resource>``. *busy* are the shas a producer
    here is judging now: their trees are taken, so no part of them is claimed.
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
    found = candidates(
        root,
        built,
        repo=repo,
        parts=lambda sha: derived(history(sha)),
        schedule=schedule,
        policy=load_policy(root),
        now=now,
        say=lines.append,
    )
    cores = 1 if serve.hpc else os.cpu_count() or 1
    learned_now = learned(origin_url(root)) if measured is None else measured
    cost = expected_cost(learned_now, schedule.prior_cost_h, cores=cores)
    ranked = rank(found, {repo: schedule}, now, cost_h={repo: cost}, weights=weights)
    room = supply or Supply(machine or 'this host', Resources(cpu=cores))
    free = max(1, math.floor(room.resources['cpu']))  # an unmeasured box run takes every core free now
    by_part = learned_demand(origin_url(root), cluster=bool(serve.hpc), cores=free)
    sized = demand or (lambda _wanted, needed: by_part(needed))
    taken = _Taking(
        root, built, serve, me, now, schedule, usage, dry_run, repo=repo, supply=room,
        size=lambda wanted, needed: submitted(sized(wanted, needed), room),
        reservations=tuple(reservations), taken=list(running), trees=set(busy),
        store_why=probe(root) if serve.hpc else '', history=history,
    )  # fmt: skip
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


@dataclass
class _Taking:
    """The claim pass over the ranked queue: each candidate that admits is claimed, the rest say why not."""

    root: Path
    client: Client
    serve: Serving
    me: Claim
    now: datetime
    schedule: Schedule
    usage: Mapping[str, float] | None
    dry_run: bool
    repo: str
    supply: Supply
    size: Callable[[Candidate, frozenset[str]], Mapping[str, float]]
    reservations: tuple[Reservation, ...] = ()
    taken: list[Mapping[str, float]] = dataclasses.field(default_factory=list)  # what runs, then each claim
    trees: set[str] = dataclasses.field(default_factory=set)  # the shas a local claim of this tick holds
    unproducible: str = ''  # why the repo's producer cannot be built here; blocks every later candidate
    store_why: str = ''  # why the large artefact store is unusable here; '' when it is usable
    tables: dict[str, tuple[Vocabulary, str]] = dataclasses.field(default_factory=dict)
    history: Callable[[str], Sequence[Status]] = lambda _sha: ()  # every status of a sha, read once a tick
    work: list[Work] = dataclasses.field(default_factory=list)
    claimed: list[Work] = dataclasses.field(default_factory=list)
    refused: list[str] = dataclasses.field(default_factory=list)
    queue: list[Ranked] = dataclasses.field(default_factory=list)

    def consider(self, item: Ranked) -> None:
        """Assess *item*, claim it when nothing blocks it, and keep it in the queue while it waits."""
        wanted = item.candidate
        if wanted.kind == REQUEST:  # requests are ranked and shown; no producer claims one yet
            self.queue.append(dataclasses.replace(item, blocked=f'{NO_HOST} claims requests yet'))
            return
        state, holder = assess(self.history(wanted.sha), wanted.platform, me=self.me, now=self.now)
        one = Work(wanted.ref, wanted.sha, wanted.platform, state, holder)
        blocked, needed = self._blocked(wanted) if state in CLAIMABLE else ('', frozenset[str]())
        if state in CLAIMABLE and not blocked and not self.dry_run:
            one, blocked = self._take(one, wanted, needed)
        self.work.append(one)
        if one.state in CLAIMABLE:
            self.queue.append(dataclasses.replace(item, blocked=blocked))

    def _blocked(self, wanted: Candidate) -> tuple[str, frozenset[str]]:
        """Why *wanted* is not claimed (``''``: it admits), and the resource names it needs."""
        _, refused = self.tables.setdefault(wanted.sha, declared_at(self.root, wanted.sha))
        needed = needs_of(wanted.platform)
        busy = not self.serve.hpc and wanted.sha in self.trees
        why = (
            refused
            or self.unproducible
            or (f'the tree of {wanted.sha[:12]} is producing another part here' if busy else '')
            or over_budget(self.root, wanted, self.schedule, self.usage)
            or self._admission(wanted, needed)
        )
        return why, needed

    def _admission(self, wanted: Candidate, needed: frozenset[str]) -> str:
        job = Job(self.repo, wanted.sha, wanted.platform, needed, wanted.origin)
        verdict = admit(
            job, self.size(wanted, needed), self.supply,
            reservations=self.reservations, running=self.taken, now=self.now,
        )  # fmt: skip
        return '' if verdict else f'{NOT_ADMITTED}: {verdict.why}'

    def _take(self, one: Work, wanted: Candidate, needed: frozenset[str]) -> tuple[Work, str]:
        try:  # what produces it BEFORE the claim: a part nobody can produce is never claimed
            one = _producer(self.root, one, self.serve)
        except (UndeclaredPart, FileNotFoundError) as why:
            self.refused.append(f'{part_context(one.platform)}: not claimed -- {why}')
            self.unproducible = f'{NO_HOST} can produce it: {why}'
            return one, self.unproducible
        if one.cluster is not None and one.cluster.outputs and self.store_why:
            why = f'its declared outputs could exceed threshold_mb and {self.store_why}'
            self.refused.append(f'{part_context(one.platform)}: not claimed -- {why}')
            return one, why
        one = claim(self.client, one, self.me)
        if one.state == MINE:
            self.claimed.append(one)
            self.taken.append(self.size(wanted, needed))
            self.trees.add(wanted.sha)
        return one, ''


def _producer(root: Path, work: Work, serve: Serving) -> Work:
    if serve.hpc:
        return dataclasses.replace(work, cluster=cluster_part(root, work.sha))
    return dataclasses.replace(work, argv=tuple(producer_argv(root, work.platform, sha=work.sha)))


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
