"""REQUESTS AND CLAIMS through the forge -- ``python -m lab_commons.dev.forge tick``, the call any harness tick makes.

ORIGIN IS THE TRIGGER (forge plan, user rulings 2026-10-09). There is no request object: a pushed ref
whose tip lacks a ``tests/<platform>`` part IS the request for that part. Which refs a checkout serves
is its MODE: ``integrate`` serves the integration branch, ``develop`` the lanes (both named by the
repo's ``[tool.lab_commons.integrator]``), ``quiet`` serves nothing.

A PENDING STATUS IS THE CLAIM, AND ITS LEASE. Claiming posts ``pending`` in the part's own context with
a description naming who and until when (:class:`Claim`)::

    claim machine=G login=alice until=2026-10-10T18:00:00Z hpc=ada/alice

``machine`` is ``$HARNESS_MACHINE``, else on a cluster the login host's name, else ``-`` (a teammate
without the harness); ``login`` the forge account the person's own credential authenticates as -- no
machine accounts. ``hpc`` names ``<cluster>/<account>`` when the part runs on a cluster -- read from
Slurm and the login (:mod:`lab_commons.hpc.account`), never typed -- ``-`` otherwise. The OWNER of a
claim is all three: two login hosts of one account are two claimants, so one account cannot win a
race against itself.

A BOX SERVES ITS OWN PLATFORM, AND NOTHING THROUGH ``ssh``. A linux box on a cluster serves the linux
part as a cluster run advanced by ``forge serve`` (:mod:`lab_commons.dev.forgerun`); any other box
runs its platform's declared producer here. No box claims a part for a cluster it reaches over ``ssh``:
the cluster pulls its own work (design 2026-10-11, the cluster is one more forge serve host).

THE RACE IS DECIDED BY THE FORGE'S ORDER. After posting, the claimant re-reads every post on the
commit: among the live claims since the context's last settled status, the EARLIEST (lowest id)
holds it. Two machines claiming at once both read the same order, so exactly one proceeds and every
other claimant stands down without producing. A status post is not compare-and-swap; this is.

A LEASE IS JUDGED ON THE FORGE'S CLOCK. ``until`` is the forge's time (the ``Date`` of its answer,
:func:`forge_now`) plus the lease, and expiry is judged against that
same clock -- a host whose clock runs fast never retakes a live claim, nor a slow one holds a dead one.
A claim whose ``until`` has passed is stale and may be retaken by anyone serving that platform; only
its owner renews it, so a lapsed lease means the owner is gone.

WHAT A TICK DOES, in order: flush the status outbox (:mod:`lab_commons.dev.forgeoutbox`), stop if
``quiet``, fetch ``origin``, rank every candidate this box could serve (:mod:`lab_commons.dev.forgeschedule`:
value per cost, each waiting one naming why), claim the best feasible one unless a run is already in
flight here, and give the claimed part what produces it: a local argv
(:func:`lab_commons.dev.platformparts.part_argv`) or a cluster
part (:func:`lab_commons.dev.platformparts.cluster_part`). A part whose producer the repo does not
declare is not claimed; its refusal names the pyproject key to add. It runs nothing itself.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import shlex
import socket
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Final

from lab_commons.dev.forge import (
    NoCredential,
    Transport,
    UnreadableRemote,
    fetch_origin,
    https_transport,
)
from lab_commons.dev.forgeoutbox import PostFailed, flush, unprompted_client
from lab_commons.dev.forgeschedule import (
    NO_HOST,
    OUTRANKED,
    OVER_BUDGET,
    REQUEST,
    Candidate,
    Headroom,
    Ranked,
    Schedule,
    candidates,
    expected_cost,
    load_schedule,
    rank,
    ref_usage,
    repo_name,
)
from lab_commons.dev.forgestatus import Status, status_history, status_post
from lab_commons.dev.forgework import Client, ForgeCallFailed, client_for
from lab_commons.dev.lanepolicy import load_policy
from lab_commons.dev.platformparts import (
    ClusterPart,
    UndeclaredPart,
    cluster_part,
    origin_url,
    part_argv,
    part_context,
    this_platform,
)
from lab_commons.dev.producer import RETRYABLE
from lab_commons.dev.venvpath import current_os_name
from lab_commons.hpc.account import ClusterAccount, cluster_account
from lab_commons.hpc.cluster import local_runner
from lab_commons.hpc.grants import workstation
from lab_commons.hpc.learned import learned
from lab_commons.hpc.platforms import LINUX
from lab_commons.hpc.shell import FULL
from lab_commons.log import emit

__all__ = [
    'CLAIMED',
    'DEFAULT_LEASE',
    'DONE',
    'MINE',
    'MODES',
    'OPEN',
    'STALE',
    'Claim',
    'Serving',
    'TickReport',
    'Work',
    'assess',
    'claim',
    'forge_now',
    'main',
    'serving',
    'this_machine',
    'this_seat',
    'tick',
]

MODES: Final = ('integrate', 'develop', 'quiet')

#: How long a claim holds before it is stale and may be retaken.
DEFAULT_LEASE: Final = timedelta(hours=6)

#: Work states. OPEN and STALE are claimable.
OPEN: Final = 'open'
STALE: Final = 'stale'
CLAIMED: Final = 'claimed'
MINE: Final = 'mine'
DONE: Final = 'done'
_CLAIMABLE: Final = frozenset({OPEN, STALE})

_NOBODY: Final = '-'
_CLAIM: Final = re.compile(
    r'^claim machine=(?P<machine>\S+) login=(?P<login>\S+) until=(?P<until>\S+) hpc=(?P<hpc>\S+)'
    r'(?: -- (?P<progress>.+))?$'
)
#: The longest status description every forge stores whole (GitHub's limit); progress is cut to fit.
DESCRIPTION_LIMIT: Final = 140


@dataclass(frozen=True)
class Claim:
    """Who serves a part and until when; ``machine``/``hpc`` are ``''`` when absent.

    *progress* is where the run stands (``queued 0/93``, ``running 40/93``), carried after `` -- `` so any
    machine with a forge credential reads it; it never identifies the owner.
    """

    machine: str
    login: str
    until: datetime
    hpc: str = ''
    progress: str = ''

    def description(self) -> str:
        """The pending status's description (module docstring), progress cut to :data:`DESCRIPTION_LIMIT`."""
        until = self.until.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')
        head = f'claim machine={self.machine or _NOBODY} login={self.login} until={until} hpc={self.hpc or _NOBODY}'
        if not self.progress:
            return head
        return f'{head} -- {self.progress}'[:DESCRIPTION_LIMIT]

    @classmethod
    def parse(cls, description: str) -> Claim | None:
        """The claim a description states, or ``None`` when it is not one this module wrote."""
        found = _CLAIM.match(description)
        if found is None:
            return None
        try:
            until = datetime.strptime(found['until'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=UTC)
        except ValueError:
            return None
        machine, hpc = (found[key] if found[key] != _NOBODY else '' for key in ('machine', 'hpc'))
        return cls(machine, found['login'], until, hpc, found['progress'] or '')

    def same_owner(self, other: Claim) -> bool:
        """The same person, on the same machine, under the same cluster account (module docstring)."""
        return (self.machine, self.login, self.hpc) == (other.machine, other.login, other.hpc)


@dataclass(frozen=True)
class Serving:
    """The part this box can produce: its platform, and the cluster account it runs under (``''`` = here)."""

    platform: str
    hpc: str = ''


@dataclass(frozen=True)
class Work:
    """One request and where it stands: a ref's tip lacking (or holding) one platform's part.

    A claimed part carries what produces it: a local *argv*, or a *cluster* part advanced by serve.
    """

    ref: str
    sha: str
    platform: str
    state: str
    holder: Claim | None = None
    argv: tuple[str, ...] = ()
    cluster: ClusterPart | None = None


def serving(host: str, seat: ClusterAccount | None) -> Serving:
    """The one part this box serves: its own platform, as a cluster run when it is a linux box on a cluster."""
    return Serving(host, str(seat) if seat is not None and host == LINUX else '')


def this_seat() -> ClusterAccount | None:
    """The cluster account this process submits under, or ``None`` off a cluster (:mod:`lab_commons.hpc.account`)."""
    return cluster_account(local_runner)


def this_machine(seat: ClusterAccount | None) -> str:
    """``$HARNESS_MACHINE``; else on a cluster the login host (one account, two hosts: two owners); else ``''``."""
    return workstation() or (socket.gethostname().split('.')[0] if seat is not None else '')


def assess(history: Sequence[Status], platform: str, *, me: Claim, now: datetime) -> tuple[str, Claim | None]:
    """Where *platform*'s part stands on a commit whose every post is *history* (oldest first).

    *now* is the FORGE's time. Returns the state and the claim holding it (``None`` when nobody holds it).
    """
    context = part_context(platform)
    posts = [status for status in history if status.context == context]
    if posts and posts[-1].state != 'pending':  # a claim released by an outage is open again
        return (OPEN if posts[-1].description.startswith(RETRYABLE) else DONE), None
    settled = max((index for index, status in enumerate(posts) if status.state != 'pending'), default=-1)
    claims = [found for status in posts[settled + 1 :] if (found := Claim.parse(status.description)) is not None]
    if not claims:
        return OPEN, None
    live = [found for found in claims if found.until > now]
    if live and live[0].same_owner(me):  # mine: my latest renewal says how long it still holds
        return MINE, max((found for found in live if found.same_owner(me)), key=lambda found: found.until)
    if live:
        return CLAIMED, live[0]
    return STALE, claims[-1]


def forge_now(client: Client) -> datetime:
    """The FORGE's time: the ``Date`` of its latest answer, asking it once when none came yet (module docstring)."""
    if not client.answered:
        client.whoami()
    if not client.answered:
        msg = f'{client.forge.host} answered without a Date header, so no lease can be judged against its clock'
        raise OSError(msg)
    return parsedate_to_datetime(client.answered).astimezone(UTC)


def claim(client: Client, work: Work, me: Claim) -> Work:
    """Post *me* as the claim on *work*, then re-read the forge's order; the work as it now stands.

    Its state is :data:`MINE` when this claim holds, else whoever's earlier claim won the race. The
    same call RENEWS an owner's lease: a renewal is a claim like any other, and it holds only while no
    earlier live claim of another owner stands.
    """
    status_post(client, work.sha, context=part_context(work.platform), state='pending', description=me.description())
    state, holder = assess(status_history(client, work.sha), work.platform, me=me, now=forge_now(client))
    return dataclasses.replace(work, state=state, holder=holder)


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
    os_name: str | None = None,
    in_flight: bool = False,
    headroom: Headroom | None = None,
    usage: Mapping[str, float] | None = None,
    weights: Mapping[str, float] | None = None,
    measured: Mapping[str, Any] | None = None,
) -> TickReport:
    """One tick, in the order the module docstring gives; with a run *in_flight* here it claims nothing.

    *headroom* is what this host can take now (default: a box's cores); *usage* the core-hours each run
    sha12 used in the last day (a cluster's ``sacct``; ``None`` meters nothing, so no budget binds);
    *weights* this host's per-repo multipliers; *measured* the repository's last run measurements
    (default: :func:`lab_commons.hpc.learned.learned`).
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
        root, mode, built, repo=repo, platforms=(serve.platform,), schedule=schedule, policy=load_policy(root), now=now
    )
    cores = 1 if serve.hpc else os.cpu_count() or 1
    learned_now = learned(origin_url(root)) if measured is None else measured
    cost = expected_cost(learned_now, schedule.prior_cost_h, cores=cores)
    ranked = rank(found, {repo: schedule}, now, cost_h={repo: cost}, weights=weights)
    taken = _Taking(
        root, built, serve, me, now, schedule, usage, dry_run, os_name or current_os_name(),
        room=(headroom or Headroom(cores=cores)).why_not(), winner='a run in flight here' if in_flight else '',
    )  # fmt: skip
    for item in ranked:
        taken.consider(item)
    work, claimed, refused, queue = taken.work, taken.claimed, taken.refused, taken.queue
    for item in work:
        who = f' by {item.holder.login}@{item.holder.machine or _NOBODY}' if item.holder else ''
        lines.append(f'{item.state:<7} {part_context(item.platform):<14} {item.ref}  {item.sha[:12]}{who}')
    for item in claimed:
        how = f'a cluster run as {serve.hpc}' if item.cluster else shlex.join(item.argv)
        lines.append(f'produce {part_context(item.platform)}: {how}')
    lines += [f'refused {reason}' for reason in refused]
    lines += [f'waiting {item.candidate.key}: {item.blocked}' for item in queue if item.blocked]
    return TickReport(tuple(work), tuple(claimed), tuple(lines), tuple(refused), tuple(queue))


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
    os_name: str
    room: str = ''
    winner: str = ''
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
        state, holder = assess(status_history(self.client, wanted.sha), self.serve.platform, me=self.me, now=self.now)
        one = Work(wanted.ref, wanted.sha, self.serve.platform, state, holder)
        blocked = self._blocked(wanted) if state in _CLAIMABLE else ''
        if state in _CLAIMABLE and not blocked and not self.dry_run:
            one, blocked = self._take(one, wanted)
        self.work.append(one)
        if one.state in _CLAIMABLE:
            self.queue.append(dataclasses.replace(item, blocked=blocked))

    def _blocked(self, wanted: Candidate) -> str:
        outranked = f'{OUTRANKED} by {self.winner}' if self.winner else ''
        return outranked or self.room or _over_budget(self.root, wanted, self.schedule, self.usage)

    def _take(self, one: Work, wanted: Candidate) -> tuple[Work, str]:
        try:  # what produces it BEFORE the claim: a part nobody can produce is never claimed
            one = _producer(self.root, one, self.serve, self.os_name)
        except (UndeclaredPart, FileNotFoundError) as why:
            self.refused.append(f'{part_context(self.serve.platform)}: not claimed -- {why}')
            self.room = f'{NO_HOST} can produce it: {why}'
            return one, self.room
        one = claim(self.client, one, self.me)
        if one.state == MINE:
            self.claimed.append(one)
            self.winner = wanted.key
        return one, ''


def _over_budget(root: Path, wanted: Candidate, schedule: Schedule, usage: Mapping[str, float] | None) -> str:
    cap = schedule.daily_budget_core_h.get(wanted.kind)
    if cap is None or usage is None:
        return ''
    used = ref_usage(root, wanted.ref, usage)
    return f'{OVER_BUDGET}: {wanted.ref} used {used:.1f} of {cap:g} core-h in 24 h' if used >= cap else ''


def _producer(root: Path, work: Work, serve: Serving, os_name: str) -> Work:
    if serve.hpc:
        return dataclasses.replace(work, cluster=cluster_part(root, work.sha))
    return dataclasses.replace(work, argv=tuple(part_argv(root, serve.platform, scope=FULL, os_name=os_name)))


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
    os_name: str | None = None,
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
            os_name=os_name,
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
