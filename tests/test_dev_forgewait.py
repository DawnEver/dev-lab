"""A part's wait is answered, bounded and seen (:mod:`dev_lab.dev.forgewait`); aging brings a waiter to the front."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from _box_fake import quiet
from lab_commons.box import GB, Capacity, Holding
from lab_commons.box.supply import Reading
from lab_commons.compute.model import FEATURE, PR, REQUEST, Candidate, Ranked, Schedule, rank

from dev_lab.dev.forgeclaim import MINE, Work
from dev_lab.dev.forgehosts import HostCard
from dev_lab.dev.forgeschedule import NOT_ADMITTED
from dev_lab.dev.forgestatus import CommitStatus
from dev_lab.dev.forgewait import NEVER_FITS, Box, nowhere, tell, wait_context
from dev_lab.dev.forgework import Client
from dev_lab.dev.platformparts import part_context

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
T0 = NOW.timestamp()
SIZE = Capacity(cpu=8.0, mem_bytes=32 * GB, seats={})
HOUR = 3600


def _held(gb: float, *, ends_in_s: float, what: str = 'verify:lane') -> Holding:
    return Holding(what, 4242, 1, int(gb * GB), {}, T0 + ends_in_s)


def _box(*held: Holding, reading: Reading | None = None) -> Box:
    read = (lambda _pids: reading) if reading is not None else quiet(SIZE)
    return Box(SIZE, list(held), read, T0)


def test_a_demand_larger_than_the_box_never_fits_and_says_its_size() -> None:
    """PLANTED CONTROL: the same demand within the size has a start."""
    seen = _box().outlook({'cpu': 1, 'mem_gb': 40})
    assert seen.over == (('mem_gb', 40.0, 32.0),)
    assert seen.text(T0) == f'{NEVER_FITS} here: mem_gb 40 asked of a 32 size'
    assert _box().outlook({'cpu': 1, 'mem_gb': 30}).over == ()


def test_a_wait_behind_a_claim_starts_at_its_deadline_and_names_it() -> None:
    """The G wait of 2026-10-25: 12.4 GB behind a verify's claim -- bounded by that claim's deadline."""
    holder = _held(24, ends_in_s=HOUR)
    seen = _box(holder).outlook({'cpu': 1, 'mem_gb': 12.4})
    assert (seen.start, seen.ending) == (holder.deadline, (holder,))
    assert (
        seen.text(T0)
        == 'earliest start 2026-10-25T13:00Z (in 1.0 h), after verify:lane (pid 4242) until 2026-10-25T13:00Z'
    )
    assert _box().outlook({'cpu': 1, 'mem_gb': 12.4}).start == T0, 'PLANTED CONTROL: nothing held, it starts now'


def test_room_used_outside_the_ledger_has_no_start_and_says_so() -> None:
    """The host's own work is no claim: there is no deadline to wait for, and the wait says that."""
    busy = Reading(cores=9.0, idle_cores=9.0, total_bytes=33 * GB, available_bytes=2 * GB)
    seen = _box(reading=busy).outlook({'cpu': 1, 'mem_gb': 12.4})
    assert math.isinf(seen.start)
    assert 'outside the ledger' in seen.text(T0)


def test_a_smaller_claim_that_would_delay_a_waiting_start_is_held_back() -> None:
    """Backfill by reservation: 14 GB for a day leaves 18 when the holder ends -- the 20 GB waiter could not start.

    PLANTED CONTROL: 4 GB leaves 28, so the waiter still starts at the holder's deadline and it passes.
    """
    box = _box(_held(16, ends_in_s=HOUR))
    assert box.delays({'cpu': 1, 'mem_gb': 20}, {'cpu': 1, 'mem_gb': 14}, 86_400)
    assert not box.delays({'cpu': 1, 'mem_gb': 20}, {'cpu': 1, 'mem_gb': 4}, 86_400)


def test_a_claim_taken_in_the_pass_counts_as_held_until_its_wall() -> None:
    box = _box()
    box.hold({'cpu': 1, 'mem_gb': 30}, HOUR)
    assert box.outlook({'cpu': 1, 'mem_gb': 10}).start == T0 + HOUR


def _card(host: str, *, size: dict[str, float], ticked: datetime = NOW, platform: str = 'windows') -> HostCard:
    return HostCard(host, 'alice', platform, ticked.isoformat(), supply={'cpu': 8, platform: 8}, size=size)


def test_a_part_too_large_for_every_live_host_is_answered_with_the_remedy() -> None:
    """Every live host is too small: an answer now. Any doubt -- a big host, an unsized one -- waits instead."""
    asked = {'cpu': 1, 'mem_gb': 40}
    seen = _box().outlook(asked)
    small = _card('host2', size={'cpu': 16, 'mem_gb': 24})
    why = nowhere(asked, seen, [small, _card('G', size={'cpu': 8, 'mem_gb': 30})], me='G', now=NOW)
    assert why.startswith(f'{NEVER_FITS} here: mem_gb 40 asked of a 32 size; no other live host')
    assert 'host2 cpu 16, mem_gb 24' in why
    assert 'remedy' in why
    assert nowhere(asked, seen, [], me='G', now=NOW).endswith(
        'no other live host serves it -- remedy: a host of that size, a cluster part, or a narrower selection'
    )
    assert nowhere(asked, seen, [small, _card('big', size={'cpu': 64, 'mem_gb': 256})], me='G', now=NOW) == ''
    assert nowhere(asked, seen, [_card('ada/x', size={}, platform='linux')], me='G', now=NOW) == '', (
        'a live host of unstated size may fit'
    )
    stale = _card('big', size={'cpu': 64, 'mem_gb': 256}, ticked=NOW - timedelta(hours=2))
    assert nowhere(asked, seen, [stale], me='G', now=NOW) != '', 'a STALE host fits nothing'


def test_a_host_lacking_the_parts_needs_cannot_take_it() -> None:
    asked = {'cpu': 1, 'mem_gb': 40, 'windows': 1}
    linux = _card('ada/x', size={}, platform='linux')
    assert nowhere(asked, _box().outlook(asked), [linux], me='G', now=NOW) != ''


def _ranked(part: str, wait_h: float, blocked: str, kind: str = PR, sha: str = 'a' * 40) -> Ranked:
    one = Candidate('o/r', 'pr/x', sha, part, kind, NOW - timedelta(hours=wait_h), 'full')
    return Ranked(one, 0.0, 1.0, 0.0, wait_h, blocked=blocked)


class _Posts:
    def __init__(self) -> None:
        self.made: list[tuple[str, str, str, str]] = []

    def __call__(self, _client: object, sha: str, *, context: str, state: str, description: str) -> None:
        self.made.append((sha, context, state, description))


#: tell() never reads its client when post and history are given.
_NO_CLIENT = cast('Client', None)


def test_a_part_waiting_past_the_bound_is_told_once_an_hour_and_settled_when_claimed() -> None:
    """PLANTED CONTROLS: under the bound, a request (told on its issue), or a fleet hold -- nothing is posted."""
    post = _Posts()
    blocked = f'{NOT_ADMITTED}: lacking mem_gb (12.4 asked, 0 free); earliest start 2026-10-25T13:00Z'
    queue = [
        _ranked('base', 7.2, blocked),
        _ranked('base', 1.0, blocked, sha='b' * 40),
        _ranked('base', 9.0, blocked, kind=REQUEST, sha='c' * 40),
        _ranked('base', 9.0, 'waiting behind its ref run', sha='d' * 40),
    ]
    said = tell(_NO_CLIENT, queue, [], history=lambda _sha: (), hours=6.0, host='gbox', post=post)
    head = 'waited 7 h on gbox: lacking mem_gb (12.4 asked, 0 free); earliest start 2026-10-25T13:00Z'
    assert post.made == [('a' * 40, 'waits/base', 'pending', head)]
    assert len(said) == 1
    told = CommitStatus(wait_context('base'), 'pending', head, '', id=7)
    post.made.clear()
    tell(_NO_CLIENT, queue[:1], [], history=lambda _sha: (told,), hours=6.0, host='gbox', post=post)
    assert post.made == [], 'told this hour already'
    claimed = Work('pr/x', 'a' * 40, 'base', MINE)
    tell(_NO_CLIENT, [], [claimed], history=lambda _sha: (told,), hours=6.0, host='gbox', post=post)
    assert post.made == [('a' * 40, 'waits/base', 'success', 'claimed by gbox')]


def test_the_wait_context_is_never_a_part_context() -> None:
    assert not wait_context('base').startswith(part_context(''))


@pytest.mark.parametrize(('weight', 'cost_h'), [(1.0, 1.0), (4.0, 1.0), (1.0, 0.25)], ids=['even', 'heavy', 'cheap'])
def test_aging_brings_an_old_waiter_to_the_front_of_its_tier_within_a_computed_bound(
    weight: float, cost_h: float
) -> None:
    """ORDERING CANNOT STARVE: a fresh rival of a better-scored repo arrives every tick; the old one still leads by h*.

    Within a scored tier, score = weight * (base + aging * h) / cost, so an old waiter passes a fresh rival once
    ``h > (w2 c1 / (w1 c2) - 1) * base / aging``. PLANTED CONTROL: just before that bound the rival leads.
    """
    schedule = Schedule()
    base, aging = schedule.base(FEATURE), schedule.aging_rate
    bound_h = (weight / cost_h - 1) * base / aging
    old_since = NOW - timedelta(hours=bound_h + 0.01)

    def front(at: datetime) -> str:
        old = Candidate('o/slow', 'feat/old', 'a' * 40, 'base', FEATURE, old_since, 'full')
        fresh = Candidate('o/fast', 'feat/new', 'b' * 40, 'base', FEATURE, at, 'full')
        ranked = rank([old, fresh], {'o/slow': schedule, 'o/fast': schedule}, at,
                      cost_h={'o/slow': 1.0, 'o/fast': cost_h}, weights={'o/fast': weight})  # fmt: skip
        return ranked[0].candidate.ref

    assert front(NOW) == 'feat/old'
    if bound_h > 0.05:
        assert front(NOW - timedelta(hours=0.05)) == 'feat/new', 'PLANTED CONTROL: before the bound the rival leads'
