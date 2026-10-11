"""WHO IS SERVING, READ FROM THE FORGE -- one host card per serving host, edited in place every tick.

Many machines have no ssh to a cluster and still need to know whether anyone is serving linux right
now. So every ``forge serve`` tick publishes this host's CARD as ONE comment on the repository's
``forge hosts`` issue (:data:`HOSTS_TITLE`, opened by the first host that needs it), found by its hidden
marker and edited in place (:func:`lab_commons.dev.forgepulls.comment_upsert`) -- the same shape on gitea
and GitHub. The card says who the host is (``<cluster>/<account>`` or the machine), the platform it
serves, its headroom and the cluster facts it read locally (partitions, quota), when it last ticked (the
forge's clock), what it holds with live progress, and why each candidate it saw waits.

A CARD OLDER THAN :data:`STALE_TICKS` OF ITS OWN TICK PERIOD IS STALE: the host is gone or wedged, and
``forge queue`` shows it so rather than counting it as serving.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final

from lab_commons.dev.forgepulls import comment_list, comment_upsert
from lab_commons.dev.forgework import Client

__all__ = ['HOSTS_TITLE', 'STALE_TICKS', 'HostCard', 'hosts_issue', 'publish', 'read_cards']

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

    def stale(self, now: datetime) -> bool:
        """Older than :data:`STALE_TICKS` of its own period on the forge's clock."""
        return now - datetime.fromisoformat(self.ticked) > timedelta(minutes=STALE_TICKS * self.tick_minutes)

    def text(self) -> str:
        """The comment body: one line a human reads, then the card as JSON."""
        holds = ', '.join(self.holds) or 'nothing'
        head = f'**{self.host}** serves `{self.platform}` as {self.login}; ticked {self.ticked}; holds {holds}'
        return f'{head}\n\n```json\n{json.dumps({**asdict(self), "holds": list(self.holds)}, indent=1)}\n```'


def hosts_issue(client: Client, *, create: bool) -> int | None:
    """The number of the open :data:`HOSTS_TITLE` issue; opened when *create* and absent, else ``None``."""
    found = next((issue.number for issue in client.issue_list(limit=50) if issue.title == HOSTS_TITLE), None)
    if found is None and create:
        body = 'One comment per serving host, edited in place each tick (lab_commons.dev.forgehosts).'
        return client.issue_create(HOSTS_TITLE, body).number
    return found


def publish(client: Client, card: HostCard) -> str:
    """Write *card* in place on the hosts issue: ``created``, ``updated`` or ``unchanged``."""
    number = hosts_issue(client, create=True)
    assert number is not None  # noqa: S101 -- create=True always yields one
    action, _ = comment_upsert(client, number, subject=f'{_SUBJECT}{card.host}', text=card.text())
    return action


def read_cards(client: Client) -> tuple[HostCard, ...]:
    """Every host card on the hosts issue; none when no host ever published."""
    number = hosts_issue(client, create=False)
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
