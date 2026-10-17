"""A session's share of the pool is DERIVED from Slurm, or ONE expiring forge record overrides it (ruling 2026-10-17).

Nothing about an allocation lives in a machine file: the pool is the accounts' measured ceilings, the
sessions are whoever holds tagged tasks in ``squeue`` now, and the override is one record every submitter
reads. These tests feed the probe's ``@@@ shared`` section the way ``squeue -r -o "%C|%m|%D|%k"`` prints it.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest
from test_hpc_grants import GRANT, _snap

from lab_commons.hpc.allocation import (
    UNTAGGED,
    Allocation,
    active,
    fair,
    parse,
    parse_shares,
    render,
    session_for,
)
from lab_commons.hpc.config import Cost, Policy
from lab_commons.hpc.grants import Grant, Session
from lab_commons.hpc.plan import allocate, session_room

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)
OTHER = Grant(user='you', hosts=('login.example',), slurm_account='acct-free')


# -- max-min fairness, work-conserving ------------------------------------------------------------------------


def test_max_min_gives_an_unbounded_asker_what_the_others_leave() -> None:
    assert fair(96, {'a': math.inf, 'b': 16}) == {'a': 80, 'b': 16}, 'b needs less than half: a takes the rest'
    assert fair(96, {'a': math.inf, 'b': 80}) == {'a': 48, 'b': 48}, 'both want more than half: equal halves'
    assert fair(96, {'a': math.inf}) == {'a': 96}, 'alone, the whole pool'
    # Planted control: three askers, one small.
    assert fair(90, {'a': math.inf, 'b': math.inf, 'c': 10}) == {'a': 40, 'b': 40, 'c': 10}


def test_the_active_streams_are_the_tags_slurm_holds_and_untagged_is_one_more() -> None:
    held = active([_snap('8 lc:session=a\n4 (null)\n'), _snap('8 lc:session=a\n2 lc:session=b\n')])
    assert set(held) == {'a', 'b', UNTAGGED}
    assert held['a'].cpus == 16
    assert held[UNTAGGED].cpus == 4


# -- the derived default -------------------------------------------------------------------------------------


def test_an_idle_session_lends_its_share_and_a_busy_one_is_held_to_half() -> None:
    """The fixture's quota is 96 CPU per account; two accounts are a 192-CPU pool."""
    me = Session(name='me')
    alone = session_room(me, [_snap(), _snap()], Cost(cpus=8))
    assert alone == 192 // 8, 'nobody else active: the whole pool'
    busy = [_snap('96 lc:session=them\n'), _snap('96 lc:session=them\n')]
    assert session_room(me, busy, Cost(cpus=8)) == 96 // 8, 'max-min: half the pool for each active stream'
    # Planted control: an idle session named nowhere in squeue takes nothing from me.
    small = [_snap('8 lc:session=them\n'), _snap()]
    assert session_room(me, small, Cost(cpus=8)) == (192 - 8) // 8


def test_untagged_jobs_are_a_stream_that_takes_a_fair_share() -> None:
    me = Session(name='me')
    held = [_snap('96 (null)\n'), _snap('96 (null)\n')]
    assert session_room(me, held, Cost(cpus=8)) == 96 // 8


def test_past_its_share_a_session_waits_never_refused() -> None:
    """The derived share never binds tighter than the pool's headroom; an override can, and then the job waits."""
    me = Session(name='me', cpus=16, mem_gb=1000)
    pool = [(GRANT, _snap('16 lc:session=me\n')), (OTHER, _snap())]
    _, plan = allocate(10, Cost(cpus=8, seconds=60), pool, session=me, policy=Policy())
    assert plan.room == 0
    assert plan.throttle == 1
    # Planted control: derived, the same holding leaves the rest of the pool.
    _, plan = allocate(10, Cost(cpus=8, seconds=60), pool, session=Session('me'), policy=Policy())
    assert plan.room == 12


# -- the override record ---------------------------------------------------------------------------------------


def test_the_record_round_trips_and_names_its_expiry() -> None:
    record = Allocation(NOW, {'a': Session('a', cpus=64, mem_gb=240), 'b': Session('b', cpus=32, mem_gb=120, tasks=2)})
    assert parse(render(record)) == record
    assert parse_shares(['a=64/240', 'b=32/120']) == {
        'a': Session('a', cpus=64, mem_gb=240),
        'b': Session('b', cpus=32, mem_gb=120),
    }
    with pytest.raises(ValueError, match='name=cpus/mem_gb'):
        parse_shares(['a=64'])


def test_an_unexpired_record_decides_and_an_expired_one_is_the_derived_default() -> None:
    record = render(Allocation(NOW + timedelta(hours=1), {'a': Session('a', cpus=64, mem_gb=240)}))
    assert session_for('a', record, now=NOW) == Session('a', cpus=64, mem_gb=240)
    assert session_for('b', record, now=NOW) == Session('b', cpus=0, mem_gb=0), 'unnamed while it holds: waits'
    # Planted control: past the expiry, or with no record, the share is derived.
    assert session_for('a', record, now=NOW + timedelta(hours=2)) == Session('a')
    assert session_for('a', None, now=NOW) == Session('a')
    assert session_for(None, record, now=NOW) is None


def test_an_override_caps_the_room_as_a_record_says() -> None:
    capped = Session('a', cpus=16, mem_gb=1000)
    assert session_room(capped, [_snap(), _snap()], Cost(cpus=8)) == 2
    assert session_room(Session('b', cpus=0, mem_gb=0), [_snap()], Cost(cpus=8)) == 0
