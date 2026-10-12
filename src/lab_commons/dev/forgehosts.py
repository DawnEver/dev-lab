"""WHO IS SERVING, READ FROM THE FORGE -- one host card per serving host, edited in place every tick.

Many machines have no ssh to a cluster and still need to know whether anyone is serving linux right
now. So every ``forge serve`` tick publishes this host's CARD as ONE comment on the repository's
``forge hosts`` issue (:data:`HOSTS_TITLE`, opened by the first host that needs it), found by its hidden
marker and edited in place (:func:`lab_commons.dev.forgepulls.comment_upsert`) -- the same shape on gitea
and GitHub. The card says who the host is (``<cluster>/<account>`` or the machine), the platform it
serves, its headroom and the cluster facts it read locally (partitions, quota), when it last ticked (the
forge's clock), what it holds with live progress, why each candidate it saw waits, and EVERY ALARM the tick
raised (:mod:`lab_commons.dev.forgealarm`): an alarm on an unattended host is read here, from any machine,
not from a cron log nobody opens.

A CARD OLDER THAN :data:`STALE_TICKS` OF ITS OWN TICK PERIOD IS STALE: the host is gone or wedged, and
``forge queue`` shows it so rather than counting it as serving. It is also how a REFUSED CREDENTIAL shows:
a host whose token the forge refuses cannot publish anything, so its card simply stops moving.
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
from lab_commons.dev.forgealarm import Alarm
from lab_commons.dev.forgeclaim import Work, forge_now, serving
from lab_commons.dev.forgepulls import comment_list, comment_upsert
from lab_commons.dev.forgeschedule import Ranked
from lab_commons.dev.forgework import Client, ForgeCallFailed
from lab_commons.dev.platformparts import origin_url, this_platform
from lab_commons.hpc.account import ClusterAccount

__all__ = [
    'HOSTS_TITLE',
    'STALE_TICKS',
    'HostCard',
    'hosts_issue',
    'publish',
    'publish_card',
    'read_cards',
    'recording',
]

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
    alarms: tuple[Mapping[str, str], ...] = ()  # this tick's: {kind, subject, body}

    def stale(self, now: datetime) -> bool:
        """Older than :data:`STALE_TICKS` of its own period on the forge's clock."""
        return now - datetime.fromisoformat(self.ticked) > timedelta(minutes=STALE_TICKS * self.tick_minutes)

    def text(self) -> str:
        """The comment body: one line a human reads, then the card as JSON."""
        holds = ', '.join(self.holds) or 'nothing'
        head = f'**{self.host}** serves `{self.platform}` as {self.login}; ticked {self.ticked}; holds {holds}'
        loud = ''.join(f'\n- ALARM {a["kind"]}: {a["subject"]}' for a in self.alarms)
        raw = {**asdict(self), 'holds': list(self.holds), 'alarms': [dict(a) for a in self.alarms]}
        return f'{head}{loud}\n\n```json\n{json.dumps(raw, indent=1)}\n```'


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
        cards.append(HostCard(**{**raw, 'holds': tuple(raw.get('holds', ())), 'alarms': tuple(raw.get('alarms', ()))}))
    return tuple(cards)


def recording(alarm: Callable[[Alarm], object], raised: list[Alarm]) -> Callable[[Alarm], object]:
    """*alarm*, also keeping each alarm in *raised* so the tick's card carries it."""

    def sounded(one: Alarm) -> object:
        raised.append(one)
        return alarm(one)

    return sounded


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
    alarms: Sequence[Alarm] = (),
) -> None:
    """Publish this serving host's card after a tick, with the *alarms* it raised; a refusal is said, never fatal."""
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
            alarms=tuple({'kind': a.kind, 'subject': a.subject, 'body': a.body} for a in alarms),
        )
        say(f'[serve] host card {publish(built, card)}')
    except (ForgeCallFailed, OSError) as failed:
        say(f'[serve] could not publish the host card: {failed}')
