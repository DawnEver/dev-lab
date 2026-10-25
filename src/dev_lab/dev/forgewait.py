"""A PART'S WAIT IS ANSWERED, BOUNDED AND SEEN -- why a box does not admit it, until when, and who is told.

Measured 2026-10-25: a base part asked ``mem_gb`` 12.4 of a box with 30 GB of size and sat ``not admitted``
for hours while interactive verifies kept taking the memory it waited for; nobody but a reader of
``forge queue`` could see it, and the claim pass claimed every smaller part past it. Three answers, all on the
ONE admission and ordering path (:func:`lab_commons.compute.admission.admit`, :mod:`lab_commons.box.order`):

- NEVER: a demand larger than the box's SIZE (:class:`~lab_commons.box.Capacity`, after its reserve) has no
  start to wait for. It is said at once (``never fits here``) and, when no LIVE host that serves its needs
  is large enough or of unknown size (:func:`nowhere`), REFUSED on its own commit naming the remedy.
- BOUNDED: a demand within the size has an EARLIEST START (:func:`lab_commons.box.order.earliest`): now, or a
  held claim's deadline. The claim pass protects it -- a lower-ranked part is claimed past it only when that
  delays no earlier start (:meth:`Box.delays`, the ledger's own backfill rule) -- and says it with the holders
  that must end first. A start of ``inf`` means the room is used OUTSIDE the ledger (the host's own work):
  no claim can be named, and that is said.
- SEEN: a part blocked ``not admitted`` past the schedule's ``request_unadmitted_hours`` gets a pending
  ``waits/<part>`` status on its commit (:func:`tell`) naming the short dimension, the holders and the
  earliest start -- at most once per waited hour per host -- settled ``success`` once the part is claimed. It
  is no part context (``tests/``), so it is never a claim, a verdict or a merge gate.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from lab_commons.box import GB, Capacity, Holding
from lab_commons.box.order import blocks, earliest
from lab_commons.box.supply import Reading
from lab_commons.compute.model import REQUEST, Demand, Ranked

from dev_lab.dev.forgeschedule import NOT_ADMITTED
from dev_lab.dev.forgestatus import CommitStatus, status_post

if TYPE_CHECKING:
    from dev_lab.dev.forgeclaim import Work
    from dev_lab.dev.forgehosts import HostCard
    from dev_lab.dev.forgework import Client

__all__ = ['NEVER_FITS', 'WAITS_PREFIX', 'Box', 'Outlook', 'claim_vector', 'nowhere', 'tell', 'wait_context']

#: Why a demand is answered rather than waited on: it is larger than the host's size.
NEVER_FITS: Final = 'never fits'
#: The status context prefix a waiting part is told on; never ``tests/``, so never read as a part.
WAITS_PREFIX: Final = 'waits/'

_SHARES: Final = ('cpu', 'mem_gb')


def wait_context(part: str) -> str:
    """``waits/<part>`` -- the one context a part's wait is told on."""
    return f'{WAITS_PREFIX}{part}'


def claim_vector(asked: Mapping[str, float], capacity: Capacity, needs: frozenset[str] | None = None) -> Demand:
    """What a box part declares to the ledger: whole cores within the box, its memory, a seat of each declared need.

    *needs* default: every name of *asked* but cores and memory. The one source of a box part's claim
    (:func:`dev_lab.dev.forgeproduce.box_claim`) and of the outlook a waiting one is judged by.
    """
    named = frozenset(asked) - set(_SHARES) if needs is None else needs
    seats = {name: 1 for name in named if name in capacity.seats}
    cpu = max(1, min(math.floor(capacity.cpu), int(asked.get('cpu', 1))))
    return Demand({**seats, 'cpu': cpu, 'mem_gb': float(asked.get('mem_gb', 0.0))})


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).strftime('%Y-%m-%dT%H:%MZ')


@dataclass(frozen=True)
class Outlook:
    """When a demand could start on a box: *over* its size (never), else at *start* once *ending* ended."""

    over: tuple[tuple[str, float, float], ...] = ()  # (name, asked, size)
    start: float = 0.0  # epoch seconds; inf: only use outside the ledger keeps it out
    ending: tuple[Holding, ...] = ()

    def text(self, now: float) -> str:
        """One clause a status or a queue line carries."""
        if self.over:
            return f'{NEVER_FITS} here: ' + ', '.join(f'{n} {a:g} asked of a {s:g} size' for n, a, s in self.over)
        if math.isinf(self.start):
            return 'no computed start: the room is in use outside the ledger (this host own work)'
        if self.start <= now:
            return 'fits once this pass ends'
        ends = ', '.join(f'{h.what} (pid {h.pid}) until {_iso(h.deadline)}' for h in self.ending)
        return f'earliest start {_iso(self.start)} (in {(self.start - now) / 3600:.1f} h), after {ends}'


@dataclass
class Box:
    """A box as one claim pass sees it: its size, the ledger's claims, the OS read once, the pass's clock."""

    capacity: Capacity
    held: Sequence[Holding]
    read: Callable[[Sequence[int]], Reading]
    now: float
    _reading: Reading | None = field(default=None, repr=False)

    def reading(self) -> Reading:
        """The OS, read at most once a pass (a reading samples for a moment)."""
        if self._reading is None:
            self._reading = self.read([h.pid for h in self.held])
        return self._reading

    def hold(self, asked: Mapping[str, float], wall_s: int) -> None:
        """Count a claim this pass took as held until its wall: no usage yet, so it is owed in full."""
        self.held = [*self.held, Holding('this pass', 0, *self._shares(asked), self.now + wall_s)]

    def size(self) -> dict[str, float]:
        """Cores and memory the box admits at most, after its reserve."""
        return {'cpu': self.capacity.cpu, 'mem_gb': self.capacity.mem_bytes / GB}

    def outlook(self, asked: Mapping[str, float]) -> Outlook:
        """When *asked* could start here (module docstring): never, ``inf``, or a held claim's deadline."""
        wanted = claim_vector(asked, self.capacity)
        over = tuple((n, float(asked.get(n, 0.0)), s) for n, s in self.size().items() if asked.get(n, 0.0) > s)
        if over:
            return Outlook(over=over)
        start = earliest(self.capacity, self.held, self.reading(), wanted, self.now)
        ending = () if math.isinf(start) else tuple(h for h in self.held if h.deadline <= start)
        return Outlook(start=start, ending=ending)

    def delays(self, ahead: Mapping[str, float], jumper: Mapping[str, float], wall_s: int) -> bool:
        """Whether claiming *jumper* for *wall_s* moves the earliest start of *ahead* later (the ledger's rule)."""
        first = claim_vector(ahead, self.capacity)
        seats = {n: int(v) for n, v in first.items() if n not in _SHARES}
        asked = (int(first['cpu']), int(first['mem_gb'] * GB), json.dumps(seats))
        claim = Holding('this pass', 0, *self._shares(jumper), self.now + wall_s)
        return blocks(asked, claim, capacity=self.capacity, held=self.held, reading=self.reading(), now=self.now)

    def _shares(self, asked: Mapping[str, float]) -> tuple[int, int, dict[str, int]]:
        """``(cores, bytes, seats)`` of *asked* as the box claims it."""
        taken = claim_vector(asked, self.capacity)
        return int(taken['cpu']), int(taken['mem_gb'] * GB), {n: int(v) for n, v in taken.items() if n not in _SHARES}


def nowhere(asked: Mapping[str, float], seen: Outlook, cards: Sequence[HostCard], *, me: str, now: datetime) -> str:
    """Why *asked* -- over this host's size (*seen*) -- can run on NO live host, ``''`` when one may take it.

    A live card serving its needs whose stated size holds it, or that states no size (a cluster seat, an
    older kit), may take it: ANY DOUBT WAITS. Only every live candidate too small is an answer.
    """
    needs = frozenset(asked) - set(_SHARES)
    sizes = []
    for card in cards:
        if card.host == me or card.stale(now):
            continue
        names = {*card.supply, *card.tools_present(), card.platform}
        if not needs <= names:
            continue
        if not card.size or all(asked.get(n, 0.0) <= float(card.size.get(n, math.inf)) for n in _SHARES):
            return ''
        sizes.append(f'{card.host} ' + ', '.join(f'{n} {float(card.size.get(n, 0)):g}' for n in _SHARES))
    others = f'no other live host serving it is that size ({"; ".join(sizes)})' if sizes else ''
    remedy = 'remedy: a host of that size, a cluster part, or a narrower selection'
    return f'{seen.text(now.timestamp())}; {others or "no other live host serves it"} -- {remedy}'


def _last(history: Sequence[CommitStatus], context: str) -> CommitStatus | None:
    mine = [one for one in history if one.context == context]
    return max(mine, key=lambda one: one.id) if mine else None


def tell(
    client: Client,
    queue: Sequence[Ranked],
    claimed: Sequence[Work],
    *,
    history: Callable[[str], Sequence[CommitStatus]],
    hours: float,
    host: str,
    post: Callable[..., object] = status_post,
) -> list[str]:
    """Post each part blocked ``not admitted`` past *hours* as pending ``waits/<part>``; settle each *claimed* one.

    At most one post per waited hour per host: a pending status already saying ``waited <h> h on <host>`` is left.
    """
    said = []
    for item in queue:
        one = item.candidate
        if one.kind == REQUEST or not item.blocked.startswith(NOT_ADMITTED) or item.wait_h < hours:
            continue
        context, head = wait_context(one.platform), f'waited {int(item.wait_h)} h on {host}'
        last = _last(history(one.sha), context)
        if last is not None and last.state == 'pending' and last.description.startswith(head):
            continue
        why = item.blocked.removeprefix(NOT_ADMITTED).lstrip(': ')
        post(client, one.sha, context=context, state='pending', description=f'{head}: {why}')
        said.append(f'told {one.ref}@{one.sha[:12]} {context}: {head}: {why}')
    for work in claimed:
        context = wait_context(work.platform)
        last = _last(history(work.sha), context)
        if last is not None and last.state == 'pending':
            post(client, work.sha, context=context, state='success', description=f'claimed by {host}')
            said.append(f'settled {work.ref}@{work.sha[:12]} {context}: claimed by {host}')
    return said
