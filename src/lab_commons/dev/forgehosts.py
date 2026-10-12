"""WHO IS SERVING, READ FROM THE FORGE -- one host card per serving host, edited in place every tick.

Many machines have no ssh to a cluster and still need to know whether anyone is serving linux right
now. So every ``forge serve`` tick publishes this host's CARD as ONE comment on the repository's
``forge hosts`` issue (:data:`HOSTS_TITLE`, opened by the first host that needs it), found by its hidden
marker and edited in place (:func:`lab_commons.dev.forgepulls.comment_upsert`) -- the same shape on gitea
and GitHub. The card says who the host is (``<cluster>/<account>`` or the machine), the platform it
serves, its headroom and the cluster facts it read locally (partitions, quota), when it last ticked (the
forge's clock), what it holds with live progress, why each candidate it saw waits, and why it cannot
write the large artefact store when it cannot.

A CARD OLDER THAN :data:`STALE_TICKS` OF ITS OWN TICK PERIOD IS STALE: the host is gone or wedged, and
``forge queue`` shows it so rather than counting it as serving.
"""

from __future__ import annotations

import json
import re
import socket
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final

from lab_commons.dev import forgerun
from lab_commons.dev.forgeclaim import Work, forge_now, serving
from lab_commons.dev.forgepulls import comment_list, comment_upsert
from lab_commons.dev.forgeschedule import Ranked
from lab_commons.dev.forgework import Client, ForgeCallFailed
from lab_commons.dev.platformparts import origin_url, this_platform
from lab_commons.hpc.account import ClusterAccount

__all__ = ['HOSTS_TITLE', 'STALE_TICKS', 'HostCard', 'hosts_issue', 'publish', 'publish_card', 'read_cards']

#: The title of the issue every host card hangs on.
HOSTS_TITLE: Final = 'forge hosts'

#: How many of its own tick periods a card may age before it is stale.
STALE_TICKS: Final = 3

_SUBJECT: Final = 'host:'
_BLOCK: Final = re.compile(r'```json\n(?P<json>.*?)\n```', re.DOTALL)


@dataclass(frozen=True)
class HostCard:
    """One serving host as it last described itself."""

    host: str
    login: str
    platform: str
    ticked: str  # the forge's clock, ISO 8601
    tick_minutes: float = 5.0
    headroom: Mapping[str, Any] = field(default_factory=dict)
    facts: Mapping[str, Any] = field(default_factory=dict)
    holds: tuple[str, ...] = ()
    waiting: Mapping[str, str] = field(default_factory=dict)
    artefacts: str = ''  # why this host cannot write the large artefact store; '' when it can

    def stale(self, now: datetime) -> bool:
        """Older than :data:`STALE_TICKS` of its own period on the forge's clock."""
        return now - datetime.fromisoformat(self.ticked) > timedelta(minutes=STALE_TICKS * self.tick_minutes)

    def text(self) -> str:
        """The comment body: one line a human reads, then the card as JSON."""
        holds = ', '.join(self.holds) or 'nothing'
        head = f'**{self.host}** serves `{self.platform}` as {self.login}; ticked {self.ticked}; holds {holds}'
        head += f'\n\nartefacts: {self.artefacts}' if self.artefacts else ''
        return f'{head}\n\n```json\n{json.dumps({**asdict(self), "holds": list(self.holds)}, indent=1)}\n```'


def hosts_issue(client: Client) -> int | None:
    """The number of the open :data:`HOSTS_TITLE` issue, ``None`` when there is none."""
    return next((issue.number for issue in client.issue_list(limit=50) if issue.title == HOSTS_TITLE), None)


def _open_hosts_issue(client: Client) -> int:
    body = 'One comment per serving host, edited in place each tick (lab_commons.dev.forgehosts).'
    return client.issue_create(HOSTS_TITLE, body).number


def publish(client: Client, card: HostCard) -> str:
    """Write *card* in place on the hosts issue: ``created``, ``updated`` or ``unchanged``."""
    number = hosts_issue(client) or _open_hosts_issue(client)
    action, _ = comment_upsert(client, number, subject=f'{_SUBJECT}{card.host}', text=card.text())
    return action


def read_cards(client: Client) -> tuple[HostCard, ...]:
    """Every host card on the hosts issue; none when no host ever published."""
    number = hosts_issue(client)
    if number is None:
        return ()
    cards = []
    for comment in comment_list(client, number):
        found = _BLOCK.search(comment.body) if f'lab-commons:{_SUBJECT}' in comment.body else None
        if found is None:
            continue
        raw = json.loads(found['json'])
        cards.append(HostCard(**{**raw, 'holds': tuple(raw.get('holds', ()))}))
    return tuple(cards)


def publish_card(
    root: Path,
    queue: Sequence[Ranked],
    claimed: Sequence[Work],
    *,
    client: Callable[[Path], Client],
    machine: str,
    seat: ClusterAccount | None,
    host: str | None,
    standing: forgerun.Standing | None,
    table: Mapping[str, Any],
    say: Callable[[str], None],
    artefacts: str = '',
) -> None:
    """Publish this serving host's card after a tick; a forge that refuses it is said, never a failed tick."""
    built = client(root)
    try:
        runs = tuple(f'{run.sha[:12]} {run.progress or run.phase}' for run in forgerun.live(origin_url(root)))
        card = HostCard(
            host=str(seat) if seat is not None else machine or socket.gethostname().split('.')[0],
            login=built.whoami(),
            platform=serving(host or this_platform(), seat).platform,
            ticked=forge_now(built).isoformat(),
            tick_minutes=float(table.get('tick_minutes', 5)),
            headroom=asdict(standing.headroom) if standing else {},
            facts=standing.facts if standing else {},
            holds=runs if seat is not None else tuple(f'{one.sha[:12]} {one.platform}' for one in claimed),
            waiting={item.candidate.key: item.blocked for item in queue if item.blocked},
            artefacts=artefacts,
        )
        say(f'[serve] host card {publish(built, card)}')
    except (ForgeCallFailed, OSError) as failed:
        say(f'[serve] could not publish the host card: {failed}')
