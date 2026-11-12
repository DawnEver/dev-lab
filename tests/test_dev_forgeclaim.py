"""Contract 3 (producer claim): the holder is a pure function of the status history; a result posts once."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

import pytest

from dev_lab.dev import forgeclaim
from dev_lab.dev.forgeclaim import CLAIMED, MINE, STALE, Claim, Work, assess, claim, holder, publish
from dev_lab.dev.forgestatus import CommitStatus

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
LEASE = timedelta(hours=6)
SHA = 'a' * 40
CONTEXT = 'tests/linux'


class _Forge:
    """One commit's status history; every post is dated by the forge clock *now*."""

    def __init__(self) -> None:
        self.posts: list[CommitStatus] = []
        self.now = NOW

    def post(
        self, _client: object, _sha: str, *, context: str, state: str, description: str, target_url: str = ''
    ) -> CommitStatus:
        status = CommitStatus(context, state, description, target_url, len(self.posts) + 1, created=self.now)
        self.posts.append(status)
        return status

    def history(self, _client: object, _sha: str) -> tuple[CommitStatus, ...]:
        return tuple(self.posts)


@pytest.fixture
def forge(monkeypatch: pytest.MonkeyPatch) -> _Forge:
    made = _Forge()
    monkeypatch.setattr(forgeclaim, 'status_post', made.post)
    monkeypatch.setattr(forgeclaim, 'status_history', made.history)
    monkeypatch.setattr(forgeclaim, 'forge_now', lambda _client: made.now)
    return made


def _work() -> Work:
    return Work('main', SHA, 'linux', 'open')


def _results(forge: _Forge) -> list[CommitStatus]:
    return [one for one in forge.posts if one.state != 'pending']


def test_two_simultaneous_claimants_exactly_one_publishes(forge: _Forge) -> None:
    first, second = Claim('G', 'alice', NOW + LEASE), Claim('H', 'bob', NOW + LEASE)
    forge.post(None, SHA, context=CONTEXT, state='pending', description=first.description())
    forge.post(None, SHA, context=CONTEXT, state='pending', description=second.description())  # both posted first
    states = [assess(forge.posts, CONTEXT, me=one, now=NOW)[0] for one in (first, second)]
    assert states == [MINE, CLAIMED], 'both read one history: the earliest claim holds'
    published = [publish(None, _work(), one, state='success', description='pass') for one in (second, first)]
    assert published == [False, True]
    assert [one.description for one in _results(forge)] == ['pass']


def test_a_stale_retake_while_the_lease_is_live_is_refused(forge: _Forge) -> None:
    owner, taker = Claim('G', 'alice', NOW + LEASE), Claim('H', 'bob', NOW + LEASE)
    claim(None, _work(), owner)
    forge.now = NOW + LEASE / 2
    taken = claim(None, _work(), dataclasses.replace(taker, until=forge.now + LEASE))
    assert (taken.state, taken.holder.login) == (CLAIMED, 'alice')
    assert claim(None, _work(), dataclasses.replace(owner, until=forge.now + LEASE)).state == MINE, 'its renewal holds'


def test_a_retake_after_the_lease_lapsed_holds_and_the_old_owners_renewal_loses(forge: _Forge) -> None:
    owner, taker = Claim('G', 'alice', NOW + LEASE), Claim('H', 'bob', NOW)
    claim(None, _work(), owner)
    forge.now = NOW + LEASE + timedelta(minutes=1)
    assert assess(forge.posts, CONTEXT, me=taker, now=forge.now)[0] == STALE
    assert claim(None, _work(), dataclasses.replace(taker, until=forge.now + LEASE)).state == MINE
    late = claim(None, _work(), dataclasses.replace(owner, until=forge.now + LEASE))
    assert (late.state, late.holder.login) == (CLAIMED, 'bob'), 'the lapsed owner returned to a job another holds'
    assert not publish(None, _work(), owner, state='success', description='pass')


def test_a_duplicate_result_post_is_a_no_op(forge: _Forge) -> None:
    owner = Claim('G', 'alice', NOW + LEASE)
    claim(None, _work(), owner)
    assert publish(None, _work(), owner, state='success', description='pass')
    assert not publish(None, _work(), owner, state='success', description='pass')
    assert len(_results(forge)) == 1


def test_the_holder_replay_takes_a_post_with_no_forge_date_at_now() -> None:
    owner, taker = Claim('G', 'alice', NOW + LEASE), Claim('H', 'bob', NOW + 2 * LEASE)
    posts = [CommitStatus(CONTEXT, 'pending', one.description(), '', index) for index, one in enumerate((owner, taker))]
    assert holder(posts, now=NOW).login == 'alice'
    assert holder(posts, now=NOW + LEASE).login == 'bob', 'PLANTED CONTROL: lapsed at now, the next claim takes'
