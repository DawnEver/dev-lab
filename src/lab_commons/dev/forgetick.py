"""REQUESTS through the forge -- ``python -m lab_commons.dev.forge tick``, the call any harness tick makes.

ORIGIN IS THE TRIGGER (forge plan, user rulings 2026-10-09). There is no request object: a pushed ref
whose tip lacks a ``tests/<platform>`` part IS the request for that part. Which refs a checkout serves
is its MODE: ``integrate`` serves the integration branch, its PRs, opted-in branches and requests,
``develop`` the lanes (named by the repo's ``[tool.lab_commons.integrator]``), ``quiet`` serves nothing.
A part is claimed as a pending status with a lease (:mod:`lab_commons.dev.forgeclaim`).

WHAT A TICK DOES, in order: flush the status outbox (:mod:`lab_commons.dev.forgeoutbox`), stop if
``quiet``, fetch ``origin``, rank every candidate this box could serve (:mod:`lab_commons.dev.forgeschedule`:
value per cost, each waiting one naming why), claim the best feasible one unless a run is already in
flight here, and give the claimed part what produces it: a local argv as the claimed commit declares it
(:func:`lab_commons.dev.platformparts.part_argv`; the producer runs it in a tree at that commit) or a cluster part
(:func:`lab_commons.dev.platformparts.cluster_part`). A part whose producer the repo does not declare is
not claimed; its refusal names the pyproject key to add. A cluster host whose rclone
remote is unusable (:func:`lab_commons.dev.artefacts.remote_problem`) claims no part with declared outputs
-- they could exceed ``threshold_mb`` -- and says why; a part with none is still claimed. It runs nothing itself.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import shlex
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final

from lab_commons.compute.learned import learned
from lab_commons.compute.model import (
    REQUEST,
    Candidate,
    Demand,
    Job,
    Ranked,
    Resources,
    Schedule,
    Supply,
    admit,
    expected_cost,
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
from lab_commons.dev.forgeprovides import declared_parts, lacking, needs, served_parts
from lab_commons.dev.forgeschedule import (
    NO_HEADROOM,
    NO_HOST,
    OUTRANKED,
    OVER_BUDGET,
    candidates,
    load_schedule,
    ref_usage,
    repo_name,
)
from lab_commons.dev.forgestatus import status_history
from lab_commons.dev.forgework import Client, ForgeCallFailed, client_for
from lab_commons.dev.lanepolicy import load_policy
from lab_commons.dev.platformparts import (
    UndeclaredPart,
    cluster_part,
    origin_url,
    part_argv,
    part_context,
    this_platform,
)
from lab_commons.hpc.account import ClusterAccount
from lab_commons.hpc.platforms import Table, declared_at
from lab_commons.hpc.shell import FULL
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
    in_flight: bool = False,
    supply: Supply | None = None,
    usage: Mapping[str, float] | None = None,
    weights: Mapping[str, float] | None = None,
    measured: Mapping[str, Any] | None = None,
    probe: Callable[[Path], str] = remote_problem,
    provides: Mapping[str, Any] | None = None,
) -> TickReport:
    """One tick, in the order the module docstring gives; with a run *in_flight* here it claims nothing.

    *supply* is what this host or account has now (:mod:`lab_commons.compute.probe`; default: a box's
    cores); *usage* the core-hours each run sha12 used
    in the last day (a cluster's ``sacct``; ``None`` meters nothing, so no budget binds);
    *weights* this host's per-repo multipliers; *measured* the repository's last run measurements
    (default: :func:`lab_commons.compute.learned.learned`). *probe* says why a cluster host cannot write the
    repo's large artefact store (default: :func:`lab_commons.dev.artefacts.remote_problem`). *provides* is
    this host's machine-file ``[capabilities]`` (:mod:`lab_commons.dev.forgeprovides`; none by default): it
    adds the engine parts it serves and blocks a part needing what it lacks.
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
    found = candidates(
        root,
        mode,
        built,
        repo=repo,
        platforms=served_parts(serve.platform, provides or {}, declared_parts(root), cluster=bool(serve.hpc)),
        schedule=schedule,
        policy=load_policy(root),
        now=now,
        say=lines.append,
    )
    cores = 1 if serve.hpc else os.cpu_count() or 1
    learned_now = learned(origin_url(root)) if measured is None else measured
    cost = expected_cost(learned_now, schedule.prior_cost_h, cores=cores)
    ranked = rank(found, {repo: schedule}, now, cost_h={repo: cost}, weights=weights)
    taken = _Taking(
        root, built, serve, me, now, schedule, usage, dry_run,
        room=_room(repo, supply or Supply(machine or 'this host', Resources(cpu=cores)), now),
        winner='a run in flight here' if in_flight else '',
        store_why=probe(root) if serve.hpc else '', provides=provides or {},
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
    """The claim pass over the ranked queue: the first unblocked candidate is claimed, the rest say why not."""

    root: Path
    client: Client
    serve: Serving
    me: Claim
    now: datetime
    schedule: Schedule
    usage: Mapping[str, float] | None
    dry_run: bool
    room: str = ''
    winner: str = ''
    store_why: str = ''  # why the large artefact store is unusable here; '' when it is usable
    provides: Mapping[str, Any] = dataclasses.field(default_factory=dict)
    tables: dict[str, tuple[Table, str]] = dataclasses.field(default_factory=dict)
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
        state, holder = assess(status_history(self.client, wanted.sha), wanted.platform, me=self.me, now=self.now)
        one = Work(wanted.ref, wanted.sha, wanted.platform, state, holder)
        blocked = self._blocked(wanted) if state in CLAIMABLE else ''
        if state in CLAIMABLE and not blocked and not self.dry_run:
            one, blocked = self._take(one, wanted)
        self.work.append(one)
        if one.state in CLAIMABLE:
            self.queue.append(dataclasses.replace(item, blocked=blocked))

    def _blocked(self, wanted: Candidate) -> str:
        table, refused = self.tables.setdefault(wanted.sha, declared_at(self.root, wanted.sha))
        outranked = f'{OUTRANKED} by {self.winner}' if self.winner else ''
        return (
            refused
            or lacking(needs(table, wanted.platform), self.provides)
            or outranked
            or self.room
            or _over_budget(self.root, wanted, self.schedule, self.usage)
        )

    def _take(self, one: Work, wanted: Candidate) -> tuple[Work, str]:
        try:  # what produces it BEFORE the claim: a part nobody can produce is never claimed
            one = _producer(self.root, one, self.serve)
        except (UndeclaredPart, FileNotFoundError) as why:
            self.refused.append(f'{part_context(one.platform)}: not claimed -- {why}')
            self.room = f'{NO_HOST} can produce it: {why}'
            return one, self.room
        if one.cluster is not None and one.cluster.outputs and self.store_why:
            why = f'its declared outputs could exceed threshold_mb and {self.store_why}'
            self.refused.append(f'{part_context(one.platform)}: not claimed -- {why}')
            return one, why
        one = claim(self.client, one, self.me)
        if one.state == MINE:
            self.claimed.append(one)
            self.winner = wanted.key
        return one, ''


def _room(repo: str, supply: Supply, now: datetime) -> str:
    """``''`` when one run fits *supply* (a core, and a submission where those are counted), else what lacks."""
    floor = Demand(cpu=1, submits=1 if 'submits' in supply.present else 0)
    admission = admit(Job(repo, '', 'forge tick'), floor, supply, now=now)
    return '' if admission else f'{NO_HEADROOM}: {admission.why}'


def _over_budget(root: Path, wanted: Candidate, schedule: Schedule, usage: Mapping[str, float] | None) -> str:
    cap = schedule.daily_budget_core_h.get(wanted.kind)
    if cap is None or usage is None:
        return ''
    used = ref_usage(root, wanted.ref, usage)
    return f'{OVER_BUDGET}: {wanted.ref} used {used:.1f} of {cap:g} core-h in 24 h' if used >= cap else ''


def _producer(root: Path, work: Work, serve: Serving) -> Work:
    if serve.hpc:
        return dataclasses.replace(work, cluster=cluster_part(root, work.sha))
    return dataclasses.replace(work, argv=tuple(part_argv(root, work.platform, scope=FULL, sha=work.sha)))


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
