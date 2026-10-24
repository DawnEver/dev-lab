"""``forge try <paths>`` -- run named test files on a forge host NOW, or be told at once there is no room.

User ruling 2026-10-21: a try NEVER BLOCKS. It runs the repository's test producer over *paths* at ``HEAD`` as a
request (:data:`dev_lab.dev.forgerequest.TESTS`), PLACED by the markers its files carry
(:func:`dev_lab.dev.forgerequest.placement`): on Linux for anything Linux can run, on a Windows host only for a
selection holding a ``jmag`` test.

ROOM IS READ, NOT WAITED FOR. The hosts' cards (:mod:`dev_lab.dev.forgehosts`) say what each host admitted against
on its last tick; a try is published only when some fresh card that RUNS requests -- a cluster seat runs none
(:meth:`dev_lab.dev.forgetake.ClaimPass._not_here`) -- admits its need-set and size now
(:func:`lab_commons.compute.admission.admit`, the claim pass's own rule). None does: it prints ``no room``,
publishes nothing and exits 3. A published try carries a ``deadline`` (``--deadline``, default 15 min): a host
that has not claimed it by then refuses it on ``request/<n>`` as ``no room`` (:data:`dev_lab.dev.forgeschedule.
NO_ROOM`), so the session keeps working and reads the answer later (``forge status list <sha>``).
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from lab_commons.compute.admission import admit
from lab_commons.compute.model import Job, Resources, Supply
from lab_commons.log import emit

from dev_lab.dev.forge import _GIT, NoCredential, Transport, UnreadableRemote, fetch_origin, https_transport
from dev_lab.dev.forgehosts import HostCard, read_cards
from dev_lab.dev.forgenotice import duration
from dev_lab.dev.forgepublish import RequestRefused, publish
from dev_lab.dev.forgerequest import TESTS, Declared, UndeclaredRequest, declared_request
from dev_lab.dev.forgeschedule import load_schedule
from dev_lab.dev.forgework import ForgeCallFailed, client_for

__all__ = ['NO_ROOM_EXIT', 'main', 'room']

#: The exit code of a try no host has room for: nothing was published.
NO_ROOM_EXIT: Final = 3
_DEFAULT_DEADLINE: Final = '15 min'


def _supply(card: HostCard) -> Supply:
    resources = Resources({k: float(v) for k, v in card.supply.items() if isinstance(v, (int, float)) and v > 0})
    return Supply(card.host, resources, frozenset(resources) | card.tools_present() | {card.platform})


def room(cards: Sequence[HostCard], declared: Declared, now: datetime) -> tuple[list[str], list[str]]:
    """``(hosts with room, why each other card has none)`` for *declared* on *cards* as of *now*."""
    job = Job('', '', declared.name, declared.needs)
    demand = {'cpu': declared.cpu, 'mem_gb': declared.mem_gb}
    fits, why = [], []
    for card in cards:
        if card.stale(now):
            why.append(f'{card.host}: card stale (ticked {card.ticked})')
        elif '/' in card.host:  # card_host spells a cluster seat <cluster>/<account>: it runs no request
            why.append(f'{card.host}: a cluster seat runs no request')
        elif verdict := admit(job, demand, _supply(card)):
            fits.append(card.host)
        else:
            why.append(f'{card.host}: {verdict.why}')
    return fits, why


def _head(root: Path) -> str:
    shown = _door.run([_GIT, '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True)
    return shown.stdout.strip()


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    transport: Transport = https_transport,
    fetch: Callable[[Path], None] = fetch_origin,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    """``forge try <paths>``: 0 published, 3 no room (nothing published), 2 refused, 1 the forge failed."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge try', description=__doc__.splitlines()[0])
    parser.add_argument('paths', nargs='+', help='the test files to run, at HEAD (which origin must serve)')
    parser.add_argument('--deadline', default=_DEFAULT_DEADLINE, help='how long a host may take to claim it')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd() if cwd is None else cwd
    try:
        wait = duration('--deadline', args.deadline)
        fetch(root)
        sha = _head(root)
        declared = declared_request(root, sha, TESTS, tuple(args.paths))
        client = client_for(root, env=dict(os.environ) if env is None else env, transport=transport)
        now = clock()
        fits, why = room(read_cards(client), declared, now)
        if not fits:
            emit(f'[try] no room for {declared.part} ({declared.cpu:g} cpu, {declared.mem_gb:g} GB); nothing published')
            for line in why:
                emit(f'  {line}')
            return NO_ROOM_EXIT
        issue = publish(
            root, client, TESTS, sha, label=load_schedule(root).request_label, paths=tuple(args.paths),
            deadline=now + wait,
        )  # fmt: skip
    except (UndeclaredRequest, RequestRefused, ValueError) as refused:
        emit(f'[try] refused, nothing published: {refused}', err=True)
        return 2
    except (ForgeCallFailed, NoCredential, UnreadableRemote, OSError) as failed:
        emit(f'[try] {failed}', err=True)
        return 1
    emit(f'#{issue.number} {issue.url} -- {declared.part} at {sha[:12]}; room on {", ".join(fits)}')
    return 0
