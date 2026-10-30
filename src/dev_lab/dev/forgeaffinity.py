"""HPC ACCOUNT AFFINITY -- which cluster accounts claim a verify part first (user ruling 2026-10-30).

WHO IS AFFINED IS DECLARED ONCE PER ACCOUNT, on its own deploy table: a verify account's ``[deploy] repos`` row
carries ``verify = ["tests/*"]``, the status contexts of that repo it is the default producer of
(:class:`dev_lab.dev.hpchost.spec.Repo`). Its tick reads that row (:func:`declared`) and publishes it on its host
card (``HostCard.verify``), so every other seat learns the affined accounts -- and whether they are free -- from the
cards it already reads each tick. No account name is written anywhere else. HOW LONG everyone else defers is
stated once, here (:data:`GRACE`, :data:`COLD`, :data:`WARM_FOR`, :data:`BACKLOG`).

On a cluster seat (a workstation and a request are never gated):

* an AFFINED seat orders a covered part before every other candidate (:func:`covers`, OR'd into its ``[priority]``
  ordering, which stays as each machine file declares it), and claims it at once;
* any other seat -- the research accounts -- leaves a part some LIVE affined card covers waiting, named
  :data:`DEFERRED`, until it has been claimable (``Candidate.since``) for :data:`GRACE`; or at once when
  :data:`BACKLOG` covered parts are claimable and every live affined card is :func:`saturated` (it leaves a part
  ``not admitted``). With no live affined card nothing is deferred: nobody would claim it sooner.

CACHE AFFINITY among the deferring seats: a WARM seat -- one that finished a run of the repo within
:data:`WARM_FOR`, read off the mtime of its learned-demand table (:mod:`lab_commons.compute.learned`, written by
every finished run, keyed by the repo URL) -- claims at the grace; a COLD one waits :data:`COLD` longer. No seat
reads another's cache, so the preference is a stagger in time, never a negotiation.

An affined seat's own uncovered work -- another repo, research -- is never deferred: an idle verify account is free.
Nothing is reserved or preempted; how a research job borrows a verify account is docs-src/dev/forge.md's.

THE RESEARCH SIDE reads the same cards. A workstation's ``python -m lab_commons.hpc plan|submit|retry`` loads
:func:`research_affinity` (entry point :data:`lab_commons.hpc.affinity.READER`): the verify accounts, and which
of them are BUSY -- a live card holding a run, or with a part its patterns cover waiting on it -- so
:func:`lab_commons.hpc.affinity.place` keeps research off them and borrows only an idle one, niced.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Final

from lab_commons.compute.learned import _path as learned_path  # the one spelling of a repo's learned-table path
from lab_commons.compute.model import REQUEST, Candidate, Ranked
from lab_commons.hpc.grants import Affinity

from dev_lab.dev.forgeclaim import CLAIMABLE, Claim, assess
from dev_lab.dev.forgehosts import HostCard, read_cards
from dev_lab.dev.forgeschedule import NOT_ADMITTED
from dev_lab.dev.forgestatus import CommitStatus
from dev_lab.dev.forgework import client_for
from dev_lab.dev.hpchost.spec import load
from dev_lab.dev.platformparts import part_context

__all__ = [
    'BACKLOG',
    'COLD',
    'DEFERRED',
    'GRACE',
    'WARM_FOR',
    'context_of',
    'covers',
    'declared',
    'deferral',
    'defers',
    'research_affinity',
    'research_affinity_of',
    'saturated',
    'warm',
]

#: How long a covered part waits for its affined accounts before any other seat claims it (user ruling: 15-30 min).
GRACE: Final = timedelta(minutes=20)
#: How much longer a COLD seat waits than a warm one.
COLD: Final = timedelta(minutes=10)
#: A seat is WARM for a repo it finished a run of within this long.
WARM_FOR: Final = timedelta(hours=24)
#: Covered parts claimable at once that count as a backlog.
BACKLOG: Final = 2

#: How a covered part a non-affined seat waits on is blocked: on its queue row and its host card.
DEFERRED: Final = 'deferred to the verify accounts'


def covers(patterns: Sequence[str], context: str) -> bool:
    """Whether *context* matches one of an affinity's *patterns* (fnmatch); ``''`` (a request) never does."""
    return bool(context) and any(fnmatchcase(context, one) for one in patterns)


def context_of(one: Candidate) -> str:
    """The status context of a part candidate; ``''`` for a request, which no affinity covers."""
    return '' if one.kind == REQUEST else part_context(one.platform)


def declared(path: Path, repo_url: str) -> tuple[str, ...]:
    """The ``verify`` patterns this account's ``[deploy]`` row for *repo_url* declares; ``()`` when none."""
    spec = load(path)
    want = _bare(repo_url)
    return next((repo.verify for repo in spec.repos if _bare(repo.url) == want), ()) if spec else ()


def _bare(url: str) -> str:
    return url.strip().rstrip('/').removesuffix('.git').lower()


def saturated(cards: Sequence[HostCard]) -> bool:
    """Whether every affined card in *cards* leaves a part ``not admitted`` -- none can take one more."""
    return all(any(why.startswith(NOT_ADMITTED) for why in card.waiting.values()) for card in cards)


def defers(*, waited: timedelta, backlog: int, busy: bool, warm_here: bool, hosts: Sequence[str]) -> str:
    """Why a non-affined seat does not claim a part the live affined *hosts* cover yet, ``''`` when it may.

    *waited* is how long the part has been claimable, *backlog* how many covered parts are claimable now, *busy*
    whether every affined host is :func:`saturated`, *warm_here* whether this seat is warm for the repo.
    """
    grace = GRACE if warm_here else GRACE + COLD
    if not hosts or waited >= grace or (busy and backlog >= BACKLOG):
        return ''
    heat = 'warm' if warm_here else 'cold'
    return (
        f'{DEFERRED} ({", ".join(sorted(hosts))}): this {heat} seat claims it {_minutes(grace)} min after it became '
        f'claimable (waited {_minutes(waited)}), or at once when they are all saturated behind a backlog of {BACKLOG}'
    )


def _minutes(span: timedelta) -> int:
    return round(span.total_seconds() / 60)


def deferral(
    ranked: Sequence[Ranked],
    cards: Sequence[HostCard],
    *,
    me: Claim,
    now: datetime,
    history: Callable[[str], Sequence[CommitStatus]],
    warm_here: bool,
    mine: Sequence[str] = (),
) -> Callable[[Candidate], str]:
    """Why this seat defers a candidate (:func:`defers`), its backlog and the live affined cards read once.

    *mine* is this seat's own affinity: a part it covers is never deferred. The backlog is every part in *ranked*
    a live affined card covers that is still claimable.
    """
    live = [card for card in cards if card.verify and not card.stale(now)]

    def affined(context: str) -> list[HostCard]:
        return [card for card in live if covers(card.verify, context)]

    covered = [one.candidate for one in ranked if affined(context_of(one.candidate))]
    backlog = sum(1 for one in covered if assess(history(one.sha), context_of(one), me=me, now=now)[0] in CLAIMABLE)

    def defer(wanted: Candidate) -> str:
        if covers(mine, context_of(wanted)):
            return ''
        hosts = affined(context_of(wanted))
        return defers(
            waited=now - wanted.since,
            backlog=backlog,
            busy=saturated(hosts),
            warm_here=warm_here,
            hosts=[card.host for card in hosts],
        )

    return defer


def warm(repo_url: str, *, now: float | None = None) -> bool:
    """Whether this seat finished a run of *repo_url* within :data:`WARM_FOR`: its learned table's last write."""
    path = learned_path(repo_url)
    at = time.time() if now is None else now
    return path.is_file() and at - path.stat().st_mtime <= WARM_FOR.total_seconds()


def research_affinity_of(cards: Sequence[HostCard], *, now: datetime) -> Affinity | None:
    """The verify accounts in *cards* and the busy ones among them, each by its Slurm user; ``None`` when none.

    A card names its seat ``<cluster>/<user>``; a public repository's opaque card
    (:func:`~dev_lab.dev.forgehosts.host_id`) names no account and is not read.
    BUSY is a live card holding a run, or with a part its patterns cover waiting on it; a stale card claims
    nothing, so its account is idle.
    """
    seats = [(card, card.host.rpartition('/')[2]) for card in cards if card.verify and '/' in card.host]
    if not seats:
        return None

    def busy(card: HostCard) -> bool:
        waits = (key.rpartition(':')[2] for key in card.waiting)
        return not card.stale(now) and (bool(card.holds) or any(covers(card.verify, part_context(p)) for p in waits))

    return Affinity(
        verify=frozenset(user for _, user in seats), busy=frozenset(user for card, user in seats if busy(card))
    )


def research_affinity(root: Path | None = None) -> Affinity | None:
    """:func:`research_affinity_of` the host cards on *root*'s forge (default: the working directory's).

    THE READER lab-commons loads (entry point :data:`lab_commons.hpc.affinity.READER`), so a workstation
    session's research submission yields the accounts the forge's verify parts prefer.
    """
    return research_affinity_of(read_cards(client_for(Path.cwd() if root is None else root)), now=datetime.now(UTC))
