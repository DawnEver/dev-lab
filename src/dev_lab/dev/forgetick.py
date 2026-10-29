"""REQUESTS through the forge -- ``python -m dev_lab.dev.forge tick``, the call any harness tick makes.

ORIGIN IS THE TRIGGER (forge plan, user rulings 2026-10-09). There is no request object: a pushed ref
whose tip lacks a ``tests/<part>`` part IS the request for that part; which parts a tip needs is
DERIVED (:func:`dev_lab.dev.platformparts.derived`): ``base``, and every part a posted part hands to.
EVERY HOST SERVES EVERY CANDIDATE CLASS from one queue -- the integration branch, its PRs, every child
branch the schedule's rule classes, and requests (:mod:`dev_lab.dev.forgeschedule`); the rank orders
it and the admission fits it.
A part is claimed as a pending status with a lease (:mod:`dev_lab.dev.forgeclaim`).

WHAT A TICK DOES, in order: flush the status outbox (:mod:`dev_lab.dev.forgeoutbox`), fetch
``origin``, rank every candidate this box could serve (:mod:`dev_lab.dev.forgeschedule`:
value per cost, each waiting one naming why), CLAIM IN RANK ORDER WHILE JOBS ADMIT
(:func:`lab_commons.compute.admission.admit`: the part's need-set present here, its demand within the supply),
and give each claimed part what produces it: the ONE producer the claimed commit declares
(:func:`dev_lab.dev.platformparts.producer_argv`, ``{part}`` filled; the producer runs it in a tree at
that commit) or a cluster part (:func:`dev_lab.dev.platformparts.cluster_part`). A part
whose producer the repo does not declare is not claimed; its refusal names the pyproject key to add. A
cluster host whose rclone remote is unusable (:func:`dev_lab.dev.artefacts.remote_problem`) claims
no part with declared outputs -- they could exceed ``threshold_mb`` -- and says why; a part with none is
still claimed. It runs nothing itself.

ADMISSION, NOT ONE CLAIM A TICK. Each candidate is a :class:`~lab_commons.compute.model.Job` whose
demand is what its last run of ``(producer, need-set)`` measured; it is admitted when it fits this host's
supply less everything already RUNNING -- on a box, the supply IS what the box ledger can still admit
(:func:`lab_commons.box.providers.box_engine`), so every claim on it is already subtracted -- and less every part
this tick claimed before it. A job that
does not fit is skipped and a smaller lower-ranked one is still claimed; the skipped one waits naming
the resources it lacks (``not admitted: lacking cpu``). Several parts may therefore run on one host at
once, several jobs of one sha among them: each local job is judged in its OWN tree, keyed by sha and
context (:mod:`dev_lab.dev.shatree`).

PRIORITY IS ORDERING (:mod:`lab_commons.compute.priority`): a job this host's ``[priority]`` names is
considered before every other; it takes no supply and preempts nothing.

A JOB'S DEMAND IS WHAT IT MEASURED. A BOX part is admitted at exactly what it will declare to the box
(:func:`~lab_commons.compute.learned.box_demand`: the cores it kept busy and its peak with headroom, else
its selection, :func:`~lab_commons.compute.learned.selection_gb` at the ids it is handed), so the
admission and the box's enforced claim are one number -- and ONE CLAIM: given *reserve*, a local part's box
claim is taken before the part is claimed, and its producer adopts it (:mod:`dev_lab.dev.forgetake`).
A CLUSTER part asks what its
last Slurm run measured (:func:`~lab_commons.compute.learned.cluster_demand`).
Where the supply counts ``submits`` (a cluster account), a claim takes one.

A WAIT IS ANSWERED, BOUNDED AND SEEN (:mod:`dev_lab.dev.forgewait`). Given its *box*, a tick tells every part
it does not admit when it could start and protects that start from lower-ranked parts; a part larger than
this box that no live host in *cards* can take is refused on its commit at once, naming the remedy; and a
part waiting ``not admitted`` past the schedule's ``request_unadmitted_hours`` is told on ``waits/<part>``.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import shlex
import sys
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from lab_commons.box import Capacity
from lab_commons.box.providers import box_engine
from lab_commons.compute.learned import box_demand, cluster_demand, learned, request_demand
from lab_commons.compute.model import (
    REQUEST,
    Candidate,
    Ranked,
    Supply,
    expected_cost,
    rank,
)
from lab_commons.compute.presence import cached
from lab_commons.compute.priority import PRIORITY_TABLE, Priority
from lab_commons.compute.serves import SERVE_TABLE, Serves
from lab_commons.config import section
from lab_commons.hpc.account import ClusterAccount
from lab_commons.log import emit

from dev_lab.dev.artefacts import remote_problem
from dev_lab.dev.forge import (
    NoCredential,
    Transport,
    UnreadableRemote,
    fetch_origin,
    https_transport,
)
from dev_lab.dev.forgeclaim import (
    DEFAULT_LEASE,
    Claim,
    Work,
    forge_now,
    refuse,
    serving,
    this_machine,
    this_seat,
)
from dev_lab.dev.forgehosts import HostCard
from dev_lab.dev.forgeorigin import vouched
from dev_lab.dev.forgeoutbox import PostFailed, flush, unprompted_client
from dev_lab.dev.forgerequest import declared_request, remind, request_authors
from dev_lab.dev.forgescarce import unreached
from dev_lab.dev.forgeschedule import candidates, load_schedule, repo_name
from dev_lab.dev.forgesettled import SettledHistories
from dev_lab.dev.forgestatus import CommitStatus
from dev_lab.dev.forgetake import ClaimPass
from dev_lab.dev.forgewait import Box, nowhere, tell
from dev_lab.dev.forgework import Client, ForgeCallFailed, client_for
from dev_lab.dev.lanepolicy import load_policy
from dev_lab.dev.platformparts import derived, origin_url, parts_of, this_platform

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
    owners: Mapping[str, Collection[str]] | None = None,
    priority: Priority | None = None,
    authors: Collection[str] | None = None,
    serves: Serves | None = None,
    reserve: Callable[[Work], int | str] | None = None,
    box: Box | None = None,
    cards: Sequence[HostCard] = (),
) -> TickReport:
    """One tick, in the order the module docstring gives: claim in rank order while jobs admit.

    *supply* is what this host or account has now (:mod:`lab_commons.compute.probe`; default: a box's
    whole capacity); *running* what already runs here and is not in *supply* (a cluster run in flight);
    *demand* a candidate's size (default: what it measured); *usage* the core-hours each run sha12 used
    in the last day (a cluster's ``sacct``; ``None`` meters nothing, so no budget binds);
    *weights* this host's per-repo multipliers; *measured* the repository's last run measurements
    (default: :func:`lab_commons.compute.learned.learned`). *probe* says why a cluster host cannot write the
    repo's large artefact store (default: :func:`dev_lab.dev.artefacts.remote_problem`). Which resources
    this host has is *supply*'s ``present`` (:mod:`lab_commons.compute.probe`): a part whose need-set is not
    all present waits ``not admitted: lacking <resource>``. *owners* is who may vouch
    for each host card (host -> the login that publishes it): a job's ORIGIN host stands only where its
    forge-recorded login is one of them (:func:`dev_lab.dev.forgeorigin.vouched`). *priority* is this
    host's declared ordering (default: its machine file's ``[priority]``, :mod:`lab_commons.compute.priority`):
    a matching candidate is considered before every other, and nothing is set aside for it. *authors* are
    the logins whose requests run here at any served sha (default: the machine file's ``[requests] authors``);
    anyone else's runs only at a sha on the integration branch or the trunk. *serves* is which parts this host
    claims (default: the machine file's ``[serve] parts``, :mod:`lab_commons.compute.serves`): a part its rule
    skips waits, named, for another host. *reserve* takes a local part's box claim before it is claimed (its
    ledger row, or why the box refused it); ``None`` (a cluster seat, a dry run's caller) takes none.
    *box* is this box as the pass sees it (:class:`~dev_lab.dev.forgewait.Box`; ``None`` on a cluster seat) and
    *cards* every host card, read for whether a part too large for this box fits any live host.
    """
    lines: list[str] = []
    try:
        lines += flush(root, client=client)
    except PostFailed as failed:
        lines += str(failed).splitlines()
    fetch(root)
    built = client(root)
    history = SettledHistories(built)  # one read per sha a tick, none once settled (dev_lab.dev.forgesettled)

    login = built.whoami()
    now = forge_now(built)
    serve = serving(host or this_platform(), seat)
    me = Claim(machine, login, now + lease, serve.hpc)
    schedule, repo, policy = load_schedule(root), repo_name(built), load_policy(root)
    found = vouched(
        candidates(
            root,
            built,
            repo=repo,
            parts=lambda sha: derived(history(sha)),
            schedule=schedule,
            policy=policy,
            now=now,
            say=lines.append,
            waived=lambda sha: unreached(root, built, policy.integration, sha, history(sha)),
        ),
        owners or {},
    )
    cores = 1 if serve.hpc else os.cpu_count() or 1
    learned_now = learned(origin_url(root)) if measured is None else measured
    cost = expected_cost(learned_now, schedule.prior_cost_h, cores=cores)
    room = supply or _whole(machine or 'this host', cluster=bool(serve.hpc))
    sized = demand or _demand_of(root, cluster=bool(serve.hpc), history=history, room=room)
    taken = ClaimPass(
        root, built, serve, me, now, schedule, usage, dry_run, repo=repo, supply=room,
        size=sized,
        taken=list(running), trunks=(policy.integration, policy.trunk),
        authors=frozenset(request_authors() if authors is None else authors),
        store_why=probe(root) if serve.hpc else '', history=history,
        serves=serves or Serves.of(section(SERVE_TABLE)), reserve=reserve, box=box,
    )  # fmt: skip
    ranked = rank(found, {repo: schedule}, now, cost_h={repo: cost}, weights=weights,
        priority=(priority or Priority.of(section(PRIORITY_TABLE))).matches,
    )  # fmt: skip
    for item in ranked:
        taken.consider(item)
    answered = set()
    for key, (one, asked, seen) in taken.unfit.items():
        why = nowhere(asked, seen, cards, me=machine, now=now)
        if why and not dry_run:
            done = refuse(built, one, why)
            answered.add(key)
            taken.work = [done if item is one else item for item in taken.work]
            taken.pending = [item for item in taken.pending if item is not one]
            lines.append(f'refused {one.context} {one.ref}@{one.sha[:12]}: {why}')
    taken.queue = [item for item in taken.queue if item.candidate.key not in answered]
    if not dry_run:
        lines += remind(built, taken.queue, hours=schedule.request_unadmitted_hours, host=machine or login)
        lines += tell(built, taken.queue, taken.claimed, history=history, hours=schedule.request_unadmitted_hours,
                      host=machine or login)  # fmt: skip
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
    """A tick given no supply: this box as its providers measure it now; an account is never guessed.

    Raises:
        ValueError: on a cluster seat -- an account's supply is its measured standing, and an unmeasured one admits
            nothing rather than a default task.

    """
    if cluster:
        msg = f"{scope}: a cluster tick needs the account's measured supply (forgeslurm standing); none was given"
        raise ValueError(msg)
    return dataclasses.replace(_box_now(), scope=scope)


def _box_now() -> Supply:
    """What lies outside this box ledger's claims now (:func:`lab_commons.box.providers.box_engine`)."""
    return box_engine(capacity=Capacity.read(), presence=cached()).available('box')


def handed(statuses: Sequence[CommitStatus], part: str) -> int | None:
    """How many ids the commit's posted parts hand to *part* -- its selection's size; ``None`` when none says."""
    counts = [one.hands[part] for one in parts_of(statuses)[0].values() if part in one.hands]
    return sum(counts) if counts else None


def _demand_of(
    root: Path,
    *,
    cluster: bool,
    history: Callable[[str], Sequence[CommitStatus]] = lambda _sha: (),
    room: Supply | None = None,
) -> Callable[[Candidate, frozenset[str]], Mapping[str, float]]:
    """A candidate's demand: a cluster part's measured ask, else what it will declare to this box.

    A box REQUEST is sized by its own row (:func:`~lab_commons.compute.learned.request_demand`), a box part
    by :func:`~lab_commons.compute.learned.box_demand` at the ids its commit's parts hand it (:func:`handed`),
    narrowed to the box's FREE *room* (this tick's supply; measured now when not given).
    """
    repo_url = origin_url(root)
    if cluster:
        asked = cluster_demand(repo_url)
        return lambda _wanted, needed: asked(needed)
    free = (room or _box_now()).resources

    def sized(wanted: Candidate, needed: frozenset[str]) -> Mapping[str, float]:
        if wanted.kind == REQUEST:
            row = declared_request(root, wanted.sha, wanted.producer, wanted.paths)
            return request_demand(repo_url, row.name, needed, cpu=row.cpu, mem_gb=row.mem_gb)
        ids = handed(history(wanted.sha), wanted.platform)
        return box_demand(repo_url, needed, cpu=free['cpu'], mem_gb=free['mem_gb'], ids=ids)

    return sized


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge tick', description=__doc__.splitlines()[0])
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
            machine=this_machine(),
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
