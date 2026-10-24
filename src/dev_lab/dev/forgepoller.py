"""ONE POLLER PER REPO: the forge-wide poll of a ``forge serve`` tick runs on the one host holding the lease.

THE INCIDENT (2026-10-24): five cluster accounts each served seven repos from a ``*/5`` cron line, and every
tick of every host re-derived the same repo-wide answers -- landed PRs, branch prune, records prune, issue
hygiene, starved parts, the integration and review prompts, the relock -- 9425 requests in ten minutes,
97% from two login nodes, the forge (2 cores) pegged. Those answers are the REPO's, not the host's: one
host deriving them each tick is enough, and every step was already idempotent across hosts.

THE LEASE LIVES ON THE FORGE, BECAUSE THE HOSTS SHARE NOTHING ELSE: accounts on one cluster share no
writable file, and workstations share no file system with it. It is ONE comment on the hosts issue
(:mod:`dev_lab.dev.forgehosts`), marked :attr:`~dev_lab.dev.forgepulls.Marker.POLLER`, naming its holder and
when it expires on the FORGE's clock (:func:`~dev_lab.dev.forgeclaim.forge_now`, so a skewed host cannot
misjudge it). :func:`elect`, run by every host where its poll would begin:

* a LIVE lease held by another host: this host does not poll, and writes nothing;
* its OWN live lease: renewed (``until`` moved on), and it polls -- no read-back, nobody else writes a live lease;
* no lease, or an EXPIRED one: written with this host as holder, read back, and this host polls only if the
  read-back names it. When two hosts race, the OLDEST lease comment is the lease; a host deletes its own
  younger ones when it sees them.

A race both hosts win in one tick costs one duplicate poll, never a wrong answer: every polled step is
idempotent. A holder that stops ticking is replaced once its lease expires (three tick periods,
:func:`dev_lab.dev.forgeserve.serve`). What is NOT polled -- claiming, producing, advancing this account's
runs, its card -- every host still does: claims go through commit statuses, as before.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final

from dev_lab.dev.forgeclaim import forge_now
from dev_lab.dev.forgehosts import hosts_issue
from dev_lab.dev.forgepulls import Marker, comment_list, marker

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client, Comment

__all__ = ['Lease', 'elect', 'lease_of']

_FIELDS: Final = re.compile(r'^holder: (?P<holder>\S+)\s*\nuntil: (?P<until>\S+)\s*$', re.MULTILINE)


@dataclass(frozen=True)
class Lease:
    """Who polls a repository, and until when on the forge's clock."""

    holder: str
    until: datetime

    def text(self) -> str:
        """The lease comment's body."""
        return f'{marker(Marker.POLLER)}\nholder: {self.holder}\nuntil: {self.until.isoformat()}'


def _leases(comments: Sequence[Comment]) -> list[tuple[Comment, Lease]]:
    """Every readable lease comment, oldest first."""
    line = marker(Marker.POLLER)
    found = []
    for comment in sorted(comments, key=lambda one: one.id):
        fields = _FIELDS.search(comment.body) if line in comment.body else None
        if fields is not None:
            try:
                found.append((comment, Lease(fields['holder'], datetime.fromisoformat(fields['until']))))
            except ValueError:
                continue
    return found


def lease_of(comments: Sequence[Comment]) -> tuple[Comment, Lease] | None:
    """THE lease among *comments* -- the oldest lease comment -- or ``None`` when none is held."""
    found = _leases(comments)
    return found[0] if found else None


def elect(client: Client, *, host: str, ttl: timedelta) -> tuple[bool, str]:
    """``(whether host polls this tick, who holds the lease)`` -- the module docstring's rule.

    A repository with no hosts issue yet has nowhere to hold a lease: the host polls (its card opens the issue).
    """
    number = hosts_issue(client)
    if number is None:
        return True, host
    found = _leases(comment_list(client, number))
    now = forge_now(client)
    for comment, lease in found[1:]:
        if lease.holder == host:  # a race this host lost earlier: its own younger lease goes
            client.call('DELETE', f'{client.repo}/issues/comments/{comment.id}')
    held = found[0] if found else None
    if held is not None and held[1].holder != host and held[1].until > now:
        return False, held[1].holder
    body = Lease(host, now + ttl).text()
    if held is None:
        client.issue_comment(number, body)
    else:
        client.call('PATCH', f'{client.repo}/issues/comments/{held[0].id}', {'body': body})
    if held is not None and held[1].holder == host and held[1].until > now:
        return True, host
    back = _leases(comment_list(client, number))
    for comment, lease in back[1:]:
        if lease.holder == host:
            client.call('DELETE', f'{client.repo}/issues/comments/{comment.id}')
    holder = back[0][1].holder if back else host
    return holder == host, holder
