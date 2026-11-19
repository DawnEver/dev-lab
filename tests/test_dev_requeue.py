"""ONE RETRY POLICY PER OWNER CLASS, ONLY ON THE NEWEST HEAD (:mod:`dev_lab.dev.requeue`; user ruling 2026-11-16).

An environment or scheduling release on a ref's newest head is requeued up to its :data:`RETRIES` count; the same
release on a superseded head stays settled; ``class=code`` never requeues. Each positive carries its planted control.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dev_lab.dev.forgeclaim import DONE, OPEN, Claim, assess
from dev_lab.dev.forgestatus import CommitStatus
from dev_lab.dev.producer import RETRYABLE, Owner, owned
from dev_lab.dev.requeue import RETRIES, newest_head, requeued

NOW = datetime(2026, 11, 16, tzinfo=UTC)
CONTEXT = 'tests/base'


def _released(*descriptions: str) -> list[CommitStatus]:
    return [CommitStatus(CONTEXT, 'error', one, '', index) for index, one in enumerate(descriptions)]


def test_every_class_has_one_policy_and_code_never_retries() -> None:
    assert set(RETRIES) == set(Owner), 'one policy per class'
    assert RETRIES[Owner.CODE] == 0
    assert RETRIES[Owner.ENVIRONMENT] > 0
    assert RETRIES[Owner.SCHEDULING] > 0


@pytest.mark.parametrize('owner', [Owner.ENVIRONMENT, Owner.SCHEDULING, Owner.PART_REFUSAL])
def test_a_bounded_class_on_the_newest_head_requeues_to_its_limit(owner: Owner) -> None:
    """PLANTED CONTROL: one release past the table count settles."""
    released = owned(owner, 'released: the box gave up')
    limit = RETRIES[owner]
    assert requeued(_released(*[released] * limit), newest=True)
    assert not requeued(_released(*[released] * (limit + 1)), newest=True), 'CONTROL: past its limit it settles'


@pytest.mark.parametrize('owner', [Owner.ENVIRONMENT, Owner.SCHEDULING, Owner.PART_REFUSAL])
def test_the_same_release_on_a_superseded_head_stays_settled(owner: Owner) -> None:
    """PLANTED CONTROL: the identical history on the newest head is requeued."""
    history = _released(owned(owner, 'released: the box gave up'))
    assert not requeued(history, newest=False)
    assert requeued(history, newest=True), 'CONTROL: the newest head requeues it'


@pytest.mark.parametrize('newest', [True, False], ids=['newest', 'superseded'])
def test_code_never_requeues(*, newest: bool) -> None:
    assert not requeued([CommitStatus(CONTEXT, 'failure', 'scope=full ran=3', '', 0)], newest=newest)
    assert not requeued(_released(owned(Owner.CODE, 'released: a defect of the commit')), newest=newest)
    assert not requeued(_released('released: something'), newest=newest), 'an unowned error'


def test_a_retryable_release_stays_open() -> None:
    assert requeued(_released(f'{RETRYABLE} -- this host had no room'), newest=True)


def test_newest_head_is_the_tip_and_no_tip_is_no_head() -> None:
    assert newest_head('a' * 40, 'a' * 40)
    assert not newest_head('a' * 40, 'b' * 40), 'CONTROL: a moved ref'
    assert not newest_head('a' * 40, ''), 'CONTROL: a gone ref'


def test_assess_requeues_only_a_vouched_newest_head() -> None:
    """``assess`` derives from :func:`requeued`: unvouched (the default), a scheduling release stays DONE."""
    history = _released(owned(Owner.SCHEDULING, 'released: the box killed it'))
    me = Claim('G', 'alice', NOW)
    assert assess(history, CONTEXT, me=me, now=NOW, newest=True)[0] == OPEN
    assert assess(history, CONTEXT, me=me, now=NOW)[0] == DONE, 'CONTROL: a superseded head'
