"""CLAIMS AND LEASES through the forge -- who serves a part, until when, and who wins a race.

A PENDING STATUS IS THE CLAIM, AND ITS LEASE. Claiming posts ``pending`` in the part's own context with
a description naming who and until when (:class:`Claim`)::

    claim machine=G login=alice until=2026-10-10T18:00:00Z hpc=ada/alice -- running 40/93 done 12/93

``machine`` is ``$HARNESS_MACHINE``, else on a cluster the login host's name, else ``-`` (a teammate
without the harness); ``login`` the forge account the person's own credential authenticates as -- no
machine accounts. ``hpc`` names ``<cluster>/<account>`` when the part runs on a cluster -- read from
Slurm and the login (:mod:`lab_commons.hpc.account`), never typed -- ``-`` otherwise. The OWNER of a
claim is all three: two login hosts of one account are two claimants, so one account cannot win a
race against itself. What follows `` -- `` is the run's PROGRESS, readable from any machine; it never
identifies the owner.

A BOX SERVES ITS OWN PLATFORM, AND NOTHING THROUGH ``ssh`` (:func:`serving`). A linux box on a cluster
serves the linux part as a cluster run advanced by ``forge serve`` (:mod:`lab_commons.dev.forgerun`);
any other box runs its platform's declared producer here. The cluster pulls its own work (design
2026-10-11, the cluster is one more forge serve host).

THE RACE IS DECIDED BY THE FORGE'S ORDER. After posting, the claimant re-reads every post on the
commit: among the live claims since the context's last settled status, the EARLIEST (lowest id)
holds it. Two machines claiming at once both read the same order, so exactly one proceeds and every
other claimant stands down without producing. A status post is not compare-and-swap; this is.

A LEASE IS JUDGED ON THE FORGE'S CLOCK. ``until`` is the forge's time (the ``Date`` of its answer,
:func:`forge_now`) plus the lease, and expiry is judged against that same clock -- a host whose clock
runs fast never retakes a live claim, nor a slow one holds a dead one. A claim whose ``until`` has
passed is stale and may be retaken by anyone serving that platform; only its owner renews it, so a
lapsed lease means the owner is gone.
"""

from __future__ import annotations

import dataclasses
import re
import socket
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Final

from lab_commons.compute.probe import OS_NAMES
from lab_commons.dev.forgestatus import Status, status_history, status_post
from lab_commons.dev.forgework import Client
from lab_commons.dev.platformparts import ClusterPart, part_context
from lab_commons.dev.producer import REQUEUED
from lab_commons.hpc.account import ClusterAccount, cluster_account
from lab_commons.hpc.cluster import local_runner
from lab_commons.hpc.grants import workstation

__all__ = [
    'CLAIMABLE',
    'CLAIMED',
    'DEFAULT_LEASE',
    'DESCRIPTION_LIMIT',
    'DONE',
    'MINE',
    'OPEN',
    'STALE',
    'Claim',
    'Serving',
    'Work',
    'assess',
    'claim',
    'forge_now',
    'serving',
    'this_machine',
    'this_seat',
]

#: How long a claim holds before it is stale and may be retaken.
DEFAULT_LEASE: Final = timedelta(hours=6)

#: Work states; :data:`CLAIMABLE` are the ones a claimer may take.
OPEN: Final = 'open'
STALE: Final = 'stale'
CLAIMED: Final = 'claimed'
MINE: Final = 'mine'
DONE: Final = 'done'
CLAIMABLE: Final = frozenset({OPEN, STALE})

_NOBODY: Final = '-'
_CLAIM: Final = re.compile(
    r'^claim machine=(?P<machine>\S+) login=(?P<login>\S+) until=(?P<until>\S+) hpc=(?P<hpc>\S+)'
    r'(?: on_loan=(?P<on_loan>\d+))?(?: -- (?P<progress>.+))?$'
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
    on_loan: int = 0  # the reservation this claim borrows from (0: none); a holder of it may preempt the claim

    def description(self) -> str:
        """The pending status's description (module docstring), progress cut to :data:`DESCRIPTION_LIMIT`."""
        until = self.until.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')
        head = f'claim machine={self.machine or _NOBODY} login={self.login} until={until} hpc={self.hpc or _NOBODY}'
        head += f' on_loan={self.on_loan}' if self.on_loan else ''
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
        return cls(machine, found['login'], until, hpc, found['progress'] or '', int(found['on_loan'] or 0))

    def same_owner(self, other: Claim) -> bool:
        """The same person, on the same machine, under the same cluster account (module docstring)."""
        return (self.machine, self.login, self.hpc) == (other.machine, other.login, other.hpc)


@dataclass(frozen=True)
class Serving:
    """Where this box produces: its OS, and the cluster account it runs under (``''`` = here)."""

    platform: str
    hpc: str = ''


@dataclass(frozen=True)
class Work:
    """One request and where it stands: a ref's tip lacking (or holding) one part; *platform* is the part's name.

    A claimed part carries what produces it: a local *argv* -- as the sha declares it, run by the interpreter
    of the producer's tree at the sha -- or a *cluster* part advanced by serve.
    """

    ref: str
    sha: str
    platform: str
    state: str
    holder: Claim | None = None
    argv: tuple[str, ...] = ()
    cluster: ClusterPart | None = None


def serving(host: str, seat: ClusterAccount | None) -> Serving:
    """How this box serves: its OS, producing as a cluster run when it is a linux box on a cluster."""
    return Serving(host, str(seat) if seat is not None and host == OS_NAMES['linux'] else '')


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
        return (OPEN if posts[-1].description.startswith(REQUEUED) else DONE), None
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
