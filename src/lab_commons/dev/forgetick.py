"""REQUESTS AND CLAIMS through the forge -- ``python -m lab_commons.dev.forge tick``, the call any harness tick makes.

ORIGIN IS THE TRIGGER (forge plan, user rulings 2026-10-09). There is no request object: a pushed ref
whose tip lacks a ``tests/<platform>`` part IS the request for that part. Which refs a checkout serves
is its MODE: ``integrate`` serves the integration branch, ``develop`` the lanes (both named by the
repo's ``[tool.lab_commons.integrator]``), ``quiet`` serves nothing.

A PENDING STATUS IS THE CLAIM, AND ITS LEASE. Claiming posts ``pending`` in the part's own context with
a description naming who and until when (:class:`Claim`)::

    claim machine=G login=alice until=2026-10-10T18:00:00Z hpc=alice:acct42

``machine`` is ``$HARNESS_MACHINE`` (``-`` when absent: a teammate without the harness), ``login`` the
forge account the person's own credential authenticates as -- no machine accounts. ``hpc`` names the
cluster grant (``user:slurm_account``) when the part runs on a cluster, ``-`` otherwise.

THE RACE IS DECIDED BY THE FORGE'S ORDER. After posting, the claimant re-reads every post on the
commit: among the live claims since the context's last settled status, the EARLIEST (lowest id)
holds it. Two machines claiming at once both read the same order, so exactly one proceeds.

A STALE CLAIM IS RECLAIMABLE, BY WHOEVER CAN FINISH IT. A claim whose ``until`` has passed is stale:
the claimant died or is slow. A local part may be retaken by anyone serving that platform; a cluster
part only by a machine holding the SAME grant, because the jobs keep running under that account and
only its holder can gather them (forge plan section 5) -- otherwise the request waits.

WHAT A TICK DOES, in order: flush the status outbox (:mod:`lab_commons.dev.forgeoutbox`), stop if
``quiet``, fetch ``origin``, list every request this machine could serve with its state, claim at most
one per platform (newest ref first), and give each claimed part the argv producing it
(:func:`lab_commons.dev.platformparts.part_argv`, scope full). A platform whose producer the repo does
not declare is not claimed; its refusal names the pyproject key to add. It runs nothing itself and
notifies nobody: running is the repo's runner, notification is the harness's.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import shlex
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

from lab_commons.dev.forge import (
    _GIT,
    _GIT_TIMEOUT_S,
    NoCredential,
    Transport,
    UnreadableRemote,
    fetch_origin,
    https_transport,
)
from lab_commons.dev.forgeoutbox import PostFailed, flush, unprompted_client
from lab_commons.dev.forgestatus import Status, status_history, status_post
from lab_commons.dev.forgework import Client, ForgeCallFailed, client_for
from lab_commons.dev.integrator import Policy, load_policy
from lab_commons.dev.platformparts import UndeclaredPart, part_argv, part_context, this_platform
from lab_commons.dev.venvpath import current_os_name
from lab_commons.hpc.grants import Grant, load_grants, workstation
from lab_commons.hpc.platforms import LINUX
from lab_commons.hpc.shell import FULL
from lab_commons.log import emit

__all__ = [
    'CLAIMED',
    'DEFAULT_LEASE',
    'DONE',
    'HELD',
    'MINE',
    'MODES',
    'OPEN',
    'STALE',
    'Claim',
    'Serving',
    'Work',
    'assess',
    'claim',
    'main',
    'requests',
    'serving',
    'tick',
]

MODES: Final = ('integrate', 'develop', 'quiet')

#: How long a claim holds before it is stale and may be retaken.
DEFAULT_LEASE: Final = timedelta(hours=6)

#: Work states. OPEN and STALE are claimable; HELD is stale but needs a grant this machine lacks.
OPEN: Final = 'open'
STALE: Final = 'stale'
CLAIMED: Final = 'claimed'
MINE: Final = 'mine'
HELD: Final = 'held'
DONE: Final = 'done'
_CLAIMABLE: Final = frozenset({OPEN, STALE})

_NOBODY: Final = '-'
_CLAIM: Final = re.compile(
    r'^claim machine=(?P<machine>\S+) login=(?P<login>\S+) until=(?P<until>\S+) hpc=(?P<hpc>\S+)$'
)
_TRACKING: Final = 'refs/remotes/origin/'


@dataclass(frozen=True)
class Claim:
    """Who serves a part and until when; ``machine``/``hpc`` are ``''`` when absent."""

    machine: str
    login: str
    until: datetime
    hpc: str = ''

    def description(self) -> str:
        """The pending status's description (module docstring)."""
        until = self.until.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')
        return f'claim machine={self.machine or _NOBODY} login={self.login} until={until} hpc={self.hpc or _NOBODY}'

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
        return cls(machine, found['login'], until, hpc)

    def same_claimant(self, other: Claim) -> bool:
        """The same person on the same machine -- one account may claim from two machines."""
        return (self.machine, self.login) == (other.machine, other.login)


@dataclass(frozen=True)
class Serving:
    """A part this machine can produce: its platform, and the cluster grant it runs under (``''`` = here)."""

    platform: str
    hpc: str = ''


@dataclass(frozen=True)
class Work:
    """One request and where it stands: a ref's tip lacking (or holding) one platform's part."""

    ref: str
    sha: str
    platform: str
    state: str
    holder: Claim | None = None
    argv: tuple[str, ...] = ()


def _hpc_id(grant: Grant) -> str:
    return f'{grant.user}:{grant.slurm_account}'


def serving(host: str, grants: Sequence[Grant]) -> tuple[Serving, ...]:
    """The box's own platform, plus ``linux`` through its first cluster grant when it holds one."""
    found = [Serving(host)]
    if host != LINUX and grants:
        found.append(Serving(LINUX, _hpc_id(grants[0])))
    return tuple(found)


def requests(root: Path, mode: str, policy: Policy) -> tuple[tuple[str, str], ...]:
    """``(ref, tip sha)`` of every ``origin`` ref *mode* serves, newest commit first. Fetches nothing."""
    if mode == 'quiet':
        return ()
    listed = subprocess.run(
        [
            _GIT,
            '-C',
            str(root),
            'for-each-ref',
            '--sort=-committerdate',
            '--format=%(refname) %(objectname)',
            _TRACKING,
        ],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=True,
        timeout=_GIT_TIMEOUT_S,
    ).stdout
    found = []
    for line in listed.splitlines():
        ref, sha = line.split(' ')
        branch = ref.removeprefix(_TRACKING)
        wanted = branch == policy.integration if mode == 'integrate' else branch.startswith(policy.lane_prefixes)
        if wanted:
            found.append((branch, sha))
    return tuple(found)


def assess(
    history: Sequence[Status], serve: Serving, *, me: Claim, now: datetime, hpc_ids: frozenset[str]
) -> tuple[str, Claim | None]:
    """Where *serve*'s part stands on a commit whose every post is *history* (oldest first).

    Returns the state and the claim holding it (``None`` when nobody holds it).
    """
    context = part_context(serve.platform)
    posts = [status for status in history if status.context == context]
    if posts and posts[-1].state != 'pending':
        return DONE, None
    settled = max((index for index, status in enumerate(posts) if status.state != 'pending'), default=-1)
    claims = [found for status in posts[settled + 1 :] if (found := Claim.parse(status.description)) is not None]
    if not claims:
        return OPEN, None
    live = [found for found in claims if found.until > now]
    if live:
        return (MINE if live[0].same_claimant(me) else CLAIMED), live[0]
    last = claims[-1]
    return (STALE if not last.hpc or last.hpc in hpc_ids else HELD), last


def claim(client: Client, work: Work, me: Claim, *, now: datetime, hpc_ids: frozenset[str]) -> Work:
    """Post *me* as the claim on *work*, then re-read the forge's order; the work as it now stands.

    Its state is :data:`MINE` when this claim holds, else whoever's earlier claim won the race.
    """
    status_post(client, work.sha, context=part_context(work.platform), state='pending', description=me.description())
    serve = Serving(work.platform, me.hpc)
    state, holder = assess(status_history(client, work.sha), serve, me=me, now=now, hpc_ids=hpc_ids)
    return dataclasses.replace(work, state=state, holder=holder)


@dataclass(frozen=True)
class TickReport:
    """What a tick saw and did: every request with its state, the ones it claimed, and its lines."""

    work: tuple[Work, ...]
    claimed: tuple[Work, ...]
    lines: tuple[str, ...]
    refused: tuple[str, ...] = ()


def tick(
    root: Path,
    mode: str,
    *,
    client: Callable[[Path], Client],
    now: datetime,
    machine: str,
    grants: Sequence[Grant],
    lease: timedelta = DEFAULT_LEASE,
    dry_run: bool = False,
    fetch: Callable[[Path], None] = fetch_origin,
    host: str | None = None,
    os_name: str | None = None,
) -> TickReport:
    """One tick, in the order the module docstring gives."""
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
    hpc_ids = frozenset(_hpc_id(grant) for grant in grants)
    work: list[Work] = []
    claimed: list[Work] = []
    refused: list[str] = []
    for serve in serving(host or this_platform(), grants):
        me = Claim(machine, login, now + lease, serve.hpc)
        taken = False
        for ref, sha in requests(root, mode, load_policy(root)):
            state, holder = assess(status_history(built, sha), serve, me=me, now=now, hpc_ids=hpc_ids)
            found = Work(ref, sha, serve.platform, state, holder)
            if state in _CLAIMABLE and not taken and not dry_run:
                try:  # the argv BEFORE the claim: a part nobody can produce is never claimed
                    argv = part_argv(root, serve.platform, sha, scope=FULL, os_name=os_name or current_os_name())
                except (UndeclaredPart, FileNotFoundError) as why:
                    refused.append(f'{part_context(serve.platform)}: not claimed -- {why}')
                    taken = True
                else:
                    found = dataclasses.replace(claim(built, found, me, now=now, hpc_ids=hpc_ids), argv=tuple(argv))
                    taken = found.state == MINE
                    claimed += [found] if taken else []
            work.append(found)
    for item in work:
        who = f' by {item.holder.login}@{item.holder.machine or _NOBODY}' if item.holder else ''
        lines.append(f'{item.state:<7} {part_context(item.platform):<14} {item.ref}  {item.sha[:12]}{who}')
    lines += [f'produce {part_context(item.platform)}: {shlex.join(item.argv)}' for item in claimed]
    lines += [f'refused {reason}' for reason in refused]
    return TickReport(tuple(work), tuple(claimed), tuple(lines), tuple(refused))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='lab_commons.dev.forge tick', description=__doc__.splitlines()[0])
    parser.add_argument('--mode', required=True, choices=MODES, help='which refs this checkout serves')
    parser.add_argument('--dry-run', action='store_true', help='list the requests and their state; claim nothing')
    parser.add_argument(
        '--lease-hours', type=float, default=DEFAULT_LEASE.total_seconds() / 3600, help='how long a claim holds'
    )
    parser.add_argument('--json', action='store_true', help='print every request and what was claimed as JSON')
    return parser


def _grants() -> tuple[Grant, ...]:
    try:
        return load_grants().grants
    except ValueError:
        return ()


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    transport: Transport = https_transport,
    fetch: Callable[[Path], None] = fetch_origin,
    now: datetime | None = None,
    grants: Sequence[Grant] | None = None,
    host: str | None = None,
    os_name: str | None = None,
) -> int:
    """``tick --mode integrate|develop|quiet [--dry-run] [--lease-hours H] [--json]``; exit 1 when the forge fails."""
    args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd() if cwd is None else cwd

    def build(here: Path) -> Client:
        return client_for(here, env=env, transport=transport) if env is not None else unprompted_client(here)

    try:
        report = tick(
            root,
            args.mode,
            client=build,
            now=now or datetime.now(UTC),
            machine=workstation() or '',
            grants=_grants() if grants is None else grants,
            lease=timedelta(hours=args.lease_hours),
            dry_run=args.dry_run,
            fetch=fetch,
            host=host,
            os_name=os_name,
        )
    except ForgeCallFailed as failed:
        emit(f'[tick] {failed.report.remedy}', err=True)
        return 1
    except (NoCredential, UnreadableRemote, OSError) as failed:
        emit(f'[tick] {failed}', err=True)
        return 1
    if args.json:
        payload = {
            'work': [
                {'ref': item.ref, 'sha': item.sha, 'platform': item.platform, 'state': item.state}
                | {'holder': _holder(item)}
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


def _holder(item: Work) -> str | None:
    return item.holder.description() if item.holder else None
