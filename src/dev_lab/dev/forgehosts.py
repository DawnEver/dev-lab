"""WHO IS SERVING, READ FROM THE FORGE -- one host card per serving host, edited in place every tick.

Many machines have no ssh to a cluster and still need to know whether anyone is serving linux right
now. So every ``forge serve`` tick publishes this host's CARD as ONE comment on the repository's
``forge hosts`` issue (:data:`HOSTS_TITLE`, opened by the first host that needs it), found by its hidden
marker and edited in place (:func:`dev_lab.dev.forgepulls.comment_upsert`) -- the same shape on gitea
and GitHub.

ONE ISSUE, FOUND OR REFUSED, NEVER GUESSED. The issue is the OLDEST one carrying :data:`HOSTS_MARKER`
(or, for an issue opened before the marker, titled :data:`HOSTS_TITLE`), read off EVERY page of the
listing in EVERY state -- a closed home is still the home. A lookup that fails raises; it is never read
as "none exists", because that reading opened a fresh issue on every tick of every host (128 on three
repos, 2026-10-12). Two hosts racing to open the first one re-read after the create and both write to
the oldest; the loser is closed by ``forge tidy`` (:mod:`dev_lab.dev.forgetidy`).

The card says who the host is (:func:`card_host`: ``<cluster>/<account>`` or the machine), the
platform it serves, its TOOLS as probed -- each present or not with the evidence it rests on
(:func:`lab_commons.compute.probe.inventory`), never a declaration -- its SUPPLY as the tick admitted
against it and the cluster facts it read locally (partitions, quota), when it last ticked (the forge's
clock), what it holds with live progress, what else RUNS on it (every claim on its box ledger, a
cluster run in flight), why each candidate it saw waits, why it cannot write the large artefact store
when it cannot, and EVERY ALARM the tick raised (:mod:`dev_lab.dev.forgealarm`): an alarm on an
unattended host is read here, from any machine, not from a cron log nobody opens.

A CARD'S LOGIN IS ITS FORGE-RECORDED AUTHOR (:func:`card_of`): anyone with a credential can post a comment,
so the login a body states is never trusted -- it is what vouches for a job's origin host.

A CARD IS READ BY ITS FIELDS: a key this version does not declare is not read, so a card published
before a field was renamed reads as that field empty -- never as a crash of every reader.

A PUBLIC REPOSITORY CARRIES NO IDENTIFYING CARD (user ruling 2026-10-19). Read from the forge's ``private``
flag (:func:`is_private`, one field on both gitea and GitHub; an answer without it is read as PUBLIC), a
public repo gets :meth:`HostCard.redacted`: the host under an opaque stable id (:func:`host_id`, a short
hash -- never the raw ``<cluster>/<account>`` or machine), and only what scheduling reads -- platform,
supply, tools present, parts served, holds, waits, alarm kinds and the tick. Facts (storage paths,
partitions, quota), what else runs, alarm texts, the artefact-store reason, tool evidence and the
``[priority]`` subjects are dropped. A card published under the raw name before the repo turned public
is deleted on the first redacted tick. A ``Forge-Host`` trailer still names the raw host; a reader
vouches it against either spelling (:func:`dev_lab.dev.forgeorigin.vouched`).

A CARD OLDER THAN :data:`STALE_TICKS` OF ITS OWN TICK PERIOD IS STALE: the host is gone or wedged, and
``forge queue`` shows it so rather than counting it as serving. It is also how a REFUSED CREDENTIAL shows:
a host whose token the forge refuses cannot publish anything, so its card simply stops moving.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final

from lab_commons.compute.model import Candidate, Ranked, Supply
from lab_commons.compute.priority import Priority
from lab_commons.compute.serves import EVERY, Serves
from lab_commons.hpc.account import ClusterAccount
from lab_commons.log import emit

from dev_lab.dev import forgerunstate
from dev_lab.dev.forgealarm import Alarm
from dev_lab.dev.forgeclaim import Work, forge_now, serving, this_machine, this_seat
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgepulls import (
    ListingIncomplete,
    Marker,
    comment_list,
    comment_upsert,
    issues,
    marker,
    marker_kinds,
)
from dev_lab.dev.forgework import Client, Comment, client_for
from dev_lab.dev.partrows import this_platform
from dev_lab.dev.platformparts import origin_url

__all__ = [
    'HOSTS_MARKER',
    'HOSTS_ORIGIN',
    'HOSTS_TITLE',
    'STALE_TICKS',
    'HostCard',
    'HostsIssueLost',
    'card_host',
    'card_of',
    'card_owners',
    'host_id',
    'hosts_issue',
    'hosts_issues',
    'is_hosts',
    'is_private',
    'main',
    'publish',
    'publish_card',
    'read_cards',
    'recording',
    'retire',
    'this_host',
]

#: The title of the issue every host card hangs on.
HOSTS_TITLE: Final = 'forge hosts'

#: The hidden line in the hosts issue's body it is found by.
HOSTS_MARKER: Final = marker(Marker.HOSTS)

#: The text every hosts issue this module opened carries, marker or not: how a machine-made one is told apart.
HOSTS_ORIGIN: Final = '(dev_lab.dev.forgehosts)'

#: How many of its own tick periods a card may age before it is stale.
STALE_TICKS: Final = 3

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
    running: tuple[str, ...] = ()  # what else runs here: a box ledger claim, a cluster run in flight
    waiting: Mapping[str, str] = field(default_factory=dict)
    alarms: tuple[Mapping[str, str], ...] = ()  # this tick's: {kind, subject, body}
    artefacts: str = ''  # why this host cannot write the large artefact store; '' when it can
    tools: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)  # tool -> {present, evidence}, as probed
    priority: Mapping[str, Sequence[str]] = field(default_factory=dict)  # machine-file [priority]: ordered first
    serves: str = EVERY  # machine-file [serve] parts: which parts this host claims
    withholds: tuple[str, ...] = ()  # machine-file [serve] withhold: resources it keeps for its own work
    verify: tuple[str, ...] = ()  # [deploy] repos verify: the contexts it produces first (dev_lab.dev.forgeaffinity)
    size: Mapping[str, float] = field(default_factory=dict)  # a box's cpu and mem_gb after its reserve; {}: unstated

    def favours(self, candidate: Candidate) -> bool:
        """Whether this host's declared ``[priority]`` orders *candidate* first."""
        return Priority.of(self.priority).matches(candidate)

    def tools_present(self) -> frozenset[str]:
        """The tools this card's probe found present."""
        return frozenset(name for name, row in self.tools.items() if row.get('present'))

    def stale(self, now: datetime) -> bool:
        """Older than :data:`STALE_TICKS` of its own period on the forge's clock."""
        return now - datetime.fromisoformat(self.ticked) > timedelta(minutes=STALE_TICKS * self.tick_minutes)

    def redacted(self) -> HostCard:
        """The card as a PUBLIC repository may show it: an opaque host id and only what scheduling reads."""
        return dataclasses.replace(
            self,
            host=host_id(self.host),
            facts={},
            running=(),
            alarms=tuple({'kind': a['kind'], 'subject': '', 'body': ''} for a in self.alarms),
            artefacts='',
            tools={name: {'present': bool(row.get('present'))} for name, row in self.tools.items()},
            priority={},
        )

    def text(self) -> str:
        """The comment body: one line a human reads, then the card as JSON."""
        holds = ', '.join(self.holds) or 'nothing'
        engines = ''.join(f' + `{name}`' for name in sorted(self.tools_present()))
        head = f'**{self.host}** serves `{self.platform}`{engines} as {self.login}; ticked {self.ticked}; holds {holds}'
        head += f'\n\nartefacts: {self.artefacts}' if self.artefacts else ''
        head += f'\n\nstorage: {self.facts["storage"]}' if 'storage' in self.facts else ''
        head += f'\n\nrunning: {", ".join(self.running)}' if self.running else ''
        absent = [
            f'`{name}` ({row["evidence"][-1]["source"]}: {row["evidence"][-1]["value"]})'
            for name, row in sorted(self.tools.items())
            if not row.get('present') and row.get('evidence')
        ]
        head += f'\n\ntools absent: {"; ".join(absent)}' if absent else ''
        head += f'\n\npriority: {Priority.of(self.priority).text()}' if any(self.priority.values()) else ''
        rule = Serves(self.serves, frozenset(self.withholds))
        head += f'\n\nserves: {rule.text()}' if self.serves != EVERY or self.withholds else ''
        head += f'\n\nverify first: {", ".join(self.verify)}' if self.verify else ''
        loud = ''.join(f'\n- ALARM {a["kind"]}: {a["subject"]}' for a in self.alarms)
        raw = {
            **asdict(self),
            'holds': list(self.holds),
            'alarms': [dict(a) for a in self.alarms],
            'running': list(self.running),
            'withholds': list(self.withholds),
            'verify': list(self.verify),
        }
        return f'{head}{loud}\n\n```json\n{json.dumps(raw, indent=1)}\n```'


class HostsIssueLost(RuntimeError):
    """The hosts issue was just created and the listing still does not show it: refuse, never open another."""


def host_id(host: str) -> str:
    """The opaque, stable name a PUBLIC repository's card carries for *host*: a short hash, never the name."""
    return 'host-' + hashlib.sha256(host.encode()).hexdigest()[:12]


def is_private(client: Client) -> bool:
    """Whether the forge says this repository is private; an answer without the flag is read as public."""
    repo = client.call('GET', client.repo)
    return isinstance(repo, Mapping) and repo.get('private') is True


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
    """Write *card* in place on the hosts issue: ``created``, ``updated`` or ``unchanged``.

    On a public repository the card is :meth:`HostCard.redacted` and a card left under the raw name is deleted.
    """
    number = hosts_issue(client)
    if number is None:
        number = _open_hosts_issue(client)
    if not is_private(client):
        _delete_card(client, number, card.host)
        card = card.redacted()
    action, _ = comment_upsert(client, number, kind=Marker.HOST, key=card.host, text=card.text())
    return action


def retire(client: Client, host: str) -> str:
    """Delete *host*'s card from the hosts issue: ``retired``, or ``absent`` when it has none.

    *host* is the raw name; its opaque :func:`host_id` card (a public repo's) is retired too.
    A retired host is no longer listed; it rejoins by ticking again, which publishes a fresh card.
    """
    number = hosts_issue(client)
    if number is None:
        return 'absent'
    deleted = [_delete_card(client, number, name) for name in (host, host_id(host))]
    return 'retired' if any(deleted) else 'absent'


def _delete_card(client: Client, number: int, host: str) -> bool:
    """Delete the card keyed *host* on issue *number*; whether there was one."""
    line = marker(Marker.HOST, host)
    found = next((c for c in comment_list(client, number) if line in c.body), None)
    if found is not None:
        client.call('DELETE', f'{client.repo}/issues/comments/{found.id}')
    return found is not None


def read_cards(client: Client) -> tuple[HostCard, ...]:
    """Every host card on the hosts issue; none when no host ever published."""
    number = hosts_issue(client)
    if number is None:
        return ()
    return tuple(card for comment in comment_list(client, number) if (card := card_of(comment)) is not None)


def card_of(comment: Comment) -> HostCard | None:
    """The host card *comment* carries, its login the comment's forge-recorded author; ``None`` when it carries none."""
    found = _BLOCK.search(comment.body) if Marker.HOST in marker_kinds(comment.body) else None
    if found is None:
        return None
    raw = json.loads(found['json'])
    known = {key: value for key, value in raw.items() if key in HostCard.__dataclass_fields__}
    tupled = {key: tuple(raw.get(key, ())) for key in ('holds', 'alarms', 'running', 'withholds', 'verify')}
    return HostCard(**{**known, **tupled, 'login': comment.author or known.get('login', '')})


def card_owners(cards: Sequence[HostCard]) -> dict[str, tuple[str, ...]]:
    """Who may vouch for each host card: ``host -> (its forge-recorded login,)``."""
    return {card.host: (card.login,) for card in cards}


def card_host(machine: str, seat: ClusterAccount | None) -> str:
    """The name a host's card and its supply share: the seat, else the machine (:func:`this_machine`)."""
    return str(seat) if seat is not None else machine


def this_host() -> str:
    """The :func:`card_host` here -- ``<cluster>/<account>`` on a cluster login node, else the box.

    The one name a tick here publishes its card under and the ``Forge-Host`` stamp writes
    (:mod:`dev_lab.dev.forgeorigin`), so a job made here names the card it came from.
    """
    seat = this_seat()
    return card_host(this_machine(), seat)


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
    standing: forgerunstate.Standing | None,
    table: Mapping[str, Any],
    say: Callable[[str], None],
    alarms: Sequence[Alarm] = (),
    artefacts: str = '',
    tools: Mapping[str, Mapping[str, Any]] | None = None,
    progress: Mapping[tuple[str, str], str] | None = None,
    supply: Supply | None = None,
    running: Sequence[str] = (),
    priority: Mapping[str, Sequence[str]] | None = None,
    serves: str = EVERY,
    withholds: Sequence[str] = (),
    size: Mapping[str, float] | None = None,
    verify: Sequence[str] = (),
) -> None:
    """Publish this serving host's card, with the *alarms* it raised; a refusal is said, never fatal.

    *progress* is what each local part it holds has done so far, by ``(sha, platform)`` (``producing 42m``),
    published while they run. *supply* is what the tick admitted against (default: the cluster
    standing's), *running* what else runs here, *priority* the subjects this host orders first, *serves* its
    ``[serve] parts`` rule, *size* a box's size (what a part larger than any live host is refused against),
    *verify* the contexts this account produces first (:mod:`dev_lab.dev.forgeaffinity`).
    """
    progress = progress or {}
    built = client(root)
    try:
        runs = tuple(f'{run.sha[:12]} {run.progress or run.phase}' for run in forgerunstate.live(origin_url(root)))
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
                f'{one.sha[:12]} {one.platform} {progress.get((one.sha, one.platform), "")}'.rstrip() for one in claimed
            ),
            running=tuple(running),
            waiting={item.candidate.key: item.blocked for item in queue if item.blocked},
            alarms=tuple({'kind': a.kind, 'subject': a.subject, 'body': a.body} for a in alarms),
            artefacts=artefacts,
            tools=dict(tools or {}),
            priority=dict(priority or {}),
            serves=serves,
            withholds=tuple(sorted(withholds)),
            size=dict(size or {}),
            verify=tuple(verify),
        )
        say(f'[serve] host card {publish(built, card)}')
    except (ForgeCallFailed, ListingIncomplete, HostsIssueLost, OSError) as failed:
        say(f'[serve] ALARM could not publish the host card, and opened nothing: {failed}')


def main(argv: Sequence[str] | None = None, *, cwd: Path | None = None) -> int:
    """``forge hosts retire HOST``: drop a host's card from this repo's hosts issue; exit 1 when the forge fails."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge hosts', description=main.__doc__)
    verbs = parser.add_subparsers(dest='verb', required=True)
    verbs.add_parser('retire', help='delete HOST card; it rejoins by ticking again').add_argument('host')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        outcome = retire(client_for(Path.cwd() if cwd is None else cwd), args.host)
    except (ForgeCallFailed, ListingIncomplete, OSError) as failed:
        emit(f'[hosts] {failed}', err=True)
        return 1
    emit(f'[hosts] {args.host}: {outcome}')
    return 0
