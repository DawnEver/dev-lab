"""WHO IS SERVING, READ FROM THE FORGE -- one host card per serving host, edited in place every tick.

Many machines have no ssh to a cluster and still need to know whether anyone is serving linux right
now. So every ``forge serve`` tick publishes this host's CARD as ONE comment on the repository's
``forge hosts`` issue (:data:`HOSTS_TITLE`, opened by the first host that needs it), found by its hidden
marker and edited in place (:func:`lab_commons.dev.forgepulls.comment_upsert`) -- the same shape on gitea
and GitHub.

ONE ISSUE, FOUND OR REFUSED, NEVER GUESSED. The issue is the OLDEST one carrying :data:`HOSTS_MARKER`
(or, for an issue opened before the marker, titled :data:`HOSTS_TITLE`), read off EVERY page of the
listing in EVERY state -- a closed home is still the home. A lookup that fails raises; it is never read
as "none exists", because that reading opened a fresh issue on every tick of every host (128 on three
repos, 2026-10-12). Two hosts racing to open the first one re-read after the create and both write to
the oldest; the loser is closed by ``forge tidy`` (:mod:`lab_commons.dev.forgetidy`).

The card says who the host is (:func:`card_host`: ``<cluster>/<account>`` or the machine), the
platform it serves, what else it PROVIDES (its machine file's ``[capabilities]``,
:mod:`lab_commons.dev.forgeprovides`), its SUPPLY as the tick admitted against it and the cluster facts
it read locally (partitions, quota), when it last ticked (the forge's clock), what it holds with live
progress, what else RUNS on it (an interactive run holding the box seat, a cluster run in flight), the
live RESERVATIONS on it (:mod:`lab_commons.compute.ledger`), why each candidate it saw waits, why it cannot write the
large artefact store when it cannot, and EVERY ALARM the tick raised (:mod:`lab_commons.dev.forgealarm`): an
alarm on an unattended host is read here, from any machine, not from a cron log nobody opens.

A CARD IS READ BY ITS FIELDS: a key this version does not declare is not read, so a card published
before a field was renamed reads as that field empty -- never as a crash of every reader.

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

from lab_commons.compute.model import Ranked, Supply
from lab_commons.dev import forgerun
from lab_commons.dev.forgealarm import Alarm
from lab_commons.dev.forgeclaim import Claim, Work, forge_now, serving
from lab_commons.dev.forgepulls import ListingIncomplete, comment_list, comment_upsert, issues, marker
from lab_commons.dev.forgework import Client, Comment, ForgeCallFailed
from lab_commons.dev.platformparts import origin_url, this_platform
from lab_commons.hpc.account import ClusterAccount

__all__ = [
    'HOSTS_MARKER',
    'HOSTS_ORIGIN',
    'HOSTS_TITLE',
    'STALE_TICKS',
    'HostCard',
    'HostsIssueLost',
    'card_host',
    'card_of',
    'hosts_issue',
    'hosts_issues',
    'is_hosts',
    'publish',
    'publish_card',
    'read_cards',
    'recording',
]

#: The title of the issue every host card hangs on.
HOSTS_TITLE: Final = 'forge hosts'

#: The hidden line in the hosts issue's body it is found by.
HOSTS_MARKER: Final = marker('forge-hosts')

#: The text every hosts issue this module opened carries, marker or not: how a machine-made one is told apart.
HOSTS_ORIGIN: Final = '(lab_commons.dev.forgehosts)'

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
    supply: Mapping[str, Any] = field(default_factory=dict)  # what the tick admitted against
    facts: Mapping[str, Any] = field(default_factory=dict)
    holds: tuple[str, ...] = ()
    running: tuple[str, ...] = ()  # what else runs here: a seat holder, a cluster run in flight
    reservations: tuple[Mapping[str, Any], ...] = ()  # the live leases on this host (ledger rows)
    waiting: Mapping[str, str] = field(default_factory=dict)
    alarms: tuple[Mapping[str, str], ...] = ()  # this tick's: {kind, subject, body}
    artefacts: str = ''  # why this host cannot write the large artefact store; '' when it can
    provides: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)  # machine-file [capabilities]
    delegates: tuple[str, ...] = ()  # the logins this host's user lets reserve it (machine-file [reserve])
    preempted: tuple[str, ...] = ()  # this tick's: each loan a reservation holder displaced, and the lease

    def stale(self, now: datetime) -> bool:
        """Older than :data:`STALE_TICKS` of its own period on the forge's clock."""
        return now - datetime.fromisoformat(self.ticked) > timedelta(minutes=STALE_TICKS * self.tick_minutes)

    def text(self) -> str:
        """The comment body: one line a human reads, then the card as JSON."""
        holds = ', '.join(self.holds) or 'nothing'
        engines = ''.join(f' + `{name}`' for name in sorted(self.provides))
        head = f'**{self.host}** serves `{self.platform}`{engines} as {self.login}; ticked {self.ticked}; holds {holds}'
        head += f'\n\nartefacts: {self.artefacts}' if self.artefacts else ''
        head += f'\n\nrunning: {", ".join(self.running)}' if self.running else ''
        head += f'\n\npreempted: {", ".join(self.preempted)}' if self.preempted else ''
        loud = ''.join(f'\n- ALARM {a["kind"]}: {a["subject"]}' for a in self.alarms)
        raw = {
            **asdict(self),
            'holds': list(self.holds),
            'alarms': [dict(a) for a in self.alarms],
            'delegates': list(self.delegates),
            'running': list(self.running),
            'preempted': list(self.preempted),
            'reservations': [dict(r) for r in self.reservations],
        }
        return f'{head}{loud}\n\n```json\n{json.dumps(raw, indent=1)}\n```'


class HostsIssueLost(RuntimeError):
    """The hosts issue was just created and the listing still does not show it: refuse, never open another."""


def is_hosts(raw: Mapping[str, Any]) -> bool:
    """Whether a listed issue is a hosts issue: it carries the marker, or the title from before the marker."""
    return HOSTS_MARKER in (raw.get('body') or '') or raw.get('title') == HOSTS_TITLE


def hosts_issues(client: Client) -> tuple[Mapping[str, Any], ...]:
    """Every hosts issue in every state, oldest first; a failed or partial read raises."""
    return tuple(sorted((raw for raw in issues(client, state='all') if is_hosts(raw)), key=lambda raw: raw['number']))


def _seen_all_open(client: Client) -> None:
    """Refuse a listing that shows fewer open issues than the repository counts: it is blind, not empty.

    Gitea's repository carries ``open_issues_count`` (pulls excluded, counted beside as
    ``open_pr_counter``); GitHub's counts pulls in, so the check is gitea's only. The count is read
    BEFORE the listing, so an issue opened in between cannot make an honest listing look short.
    """
    repo = client.call('GET', client.repo)
    if 'open_pr_counter' not in repo:
        return
    listed = sum(raw['state'] == 'open' for raw in issues(client, state='open'))
    if listed < repo['open_issues_count']:
        seen = f'the listing shows {listed} open issues and the repository counts {repo["open_issues_count"]}'
        msg = f'{seen}; refusing to open a {HOSTS_TITLE!r} issue a blind lookup did not find'
        raise HostsIssueLost(msg)


def hosts_issue(client: Client) -> int | None:
    """The number of the hosts issue -- the oldest -- ``None`` only when the full listing holds none."""
    found = hosts_issues(client)
    return found[0]['number'] if found else None


def _open_hosts_issue(client: Client) -> int:
    _seen_all_open(client)
    body = f'{HOSTS_MARKER}\nOne comment per serving host, edited in place each tick {HOSTS_ORIGIN}.'
    client.issue_create(HOSTS_TITLE, body)
    number = hosts_issue(client)  # the oldest, so two hosts racing to open it agree on one
    if number is None:
        msg = f'the {HOSTS_TITLE!r} issue just created is not in the listing; refusing to open another'
        raise HostsIssueLost(msg)
    return number


def publish(client: Client, card: HostCard) -> str:
    """Write *card* in place on the hosts issue: ``created``, ``updated`` or ``unchanged``."""
    number = hosts_issue(client)
    if number is None:
        number = _open_hosts_issue(client)
    action, _ = comment_upsert(client, number, subject=f'{_SUBJECT}{card.host}', text=card.text())
    return action


def read_cards(client: Client) -> tuple[HostCard, ...]:
    """Every host card on the hosts issue; none when no host ever published."""
    number = hosts_issue(client)
    if number is None:
        return ()
    return tuple(card for comment in comment_list(client, number) if (card := card_of(comment)) is not None)


def card_of(comment: Comment) -> HostCard | None:
    """The host card *comment* carries, or ``None`` when it carries none."""
    found = _BLOCK.search(comment.body) if f'lab-commons:{_SUBJECT}' in comment.body else None
    if found is None:
        return None
    raw = json.loads(found['json'])
    known = {key: value for key, value in raw.items() if key in HostCard.__dataclass_fields__}
    tupled = {
        key: tuple(raw.get(key, ())) for key in ('holds', 'alarms', 'delegates', 'running', 'reservations', 'preempted')
    }
    return HostCard(**{**known, **tupled})


def _loan(holder: Claim | None) -> str:
    """`` on_loan=<lease id>`` for a hold borrowed from a reservation; ``''`` otherwise."""
    return f' on_loan={holder.on_loan}' if holder is not None and holder.on_loan else ''


def card_host(machine: str, seat: ClusterAccount | None) -> str:
    """The name a host's card, its supply and every reservation on it share: the seat, else the machine."""
    return str(seat) if seat is not None else machine or socket.gethostname().split('.')[0]


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
    artefacts: str = '',
    provides: Mapping[str, Mapping[str, Any]] | None = None,
    progress: Mapping[tuple[str, str], str] | None = None,
    delegates: Sequence[str] = (),
    supply: Supply | None = None,
    running: Sequence[str] = (),
    reservations: Sequence[Mapping[str, Any]] = (),
    preempted: Sequence[str] = (),
) -> None:
    """Publish this serving host's card, with the *alarms* it raised; a refusal is said, never fatal.

    *progress* is what each local part it holds has done so far, by ``(sha, platform)`` (``producing 42m``),
    published while they run. *delegates* are the logins this host's user lets reserve it
    (:mod:`lab_commons.compute.ledger`). *supply* is what the tick admitted against (default: the
    cluster standing's), *running* what else runs here, *reservations* the live leases on this host,
    *preempted* the loans this tick displaced. A hold on loan says ``on_loan=<lease id>``.
    """
    progress = progress or {}
    built = client(root)
    try:
        runs = tuple(
            f'{run.sha[:12]} {run.progress or run.phase}{_loan(Claim.parse(run.owner))}'
            for run in forgerun.live(origin_url(root))
        )
        card = HostCard(
            host=card_host(machine, seat),
            login=built.whoami(),
            platform=serving(host or this_platform(), seat).platform,
            ticked=forge_now(built).isoformat(),
            tick_minutes=float(table.get('tick_minutes', 5)),
            supply=dict((supply or standing.supply).resources) if supply or standing else {},
            facts=standing.facts if standing else {},
            holds=runs
            if seat is not None
            else tuple(
                f'{one.sha[:12]} {one.platform} {progress.get((one.sha, one.platform), "")}'.rstrip()
                + _loan(one.holder)
                for one in claimed
            ),
            running=tuple(running),
            reservations=tuple(reservations),
            waiting={item.candidate.key: item.blocked for item in queue if item.blocked},
            alarms=tuple({'kind': a.kind, 'subject': a.subject, 'body': a.body} for a in alarms),
            artefacts=artefacts,
            provides=dict(provides or {}),
            delegates=tuple(delegates),
            preempted=tuple(preempted),
        )
        say(f'[serve] host card {publish(built, card)}')
    except (ForgeCallFailed, ListingIncomplete, HostsIssueLost, OSError) as failed:
        say(f'[serve] ALARM could not publish the host card, and opened nothing: {failed}')
