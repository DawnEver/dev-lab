"""Recover: a plan's granted, never-used credentials are delivered AGAIN, with no code -- and never anything more.

The boundary under test: re-delivery of the same signed credentials, at most one per grant of the plan; never a new
grant, never a spent one, never an expired one, never another plan's. Each refusal has its planted control.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from _ops_fixtures import NOW, RFC_KEY, code

from dev_lab.ops.consent import serve
from dev_lab.ops.consent.client import recover
from dev_lab.ops.consent.credential import ConsentRefused, public_text
from dev_lab.ops.consent.issuer import Issuer, keygen
from dev_lab.ops.consent.plan import DIGEST_SHOWN, parsed, request
from dev_lab.ops.totp import STEP

HOST = 'ops@forge.example.org'
APPLY = {'host': HOST, 'action': 'ops.config', 'subject': 'a' * 64}
REVOKE = {'host': HOST, 'action': 'ops.forge.revoke', 'subject': 'b' * 64}
PLAN = {'hosts': [HOST], 'grants': [APPLY, REVOKE]}
OTHER = {'hosts': [HOST], 'grants': [{'host': HOST, 'action': 'ops.forge.token', 'subject': 'c' * 64}]}


class Clock:
    """The issuer's clock, moved by a test."""

    def __init__(self) -> None:
        """Start at the fixtures' NOW."""
        self.now = NOW

    def __call__(self) -> float:
        """The current time."""
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def issuer(tmp_path: Path, clock: Clock) -> Issuer:
    (tmp_path / 'totp').write_text(RFC_KEY + '\n', encoding='utf-8')
    keygen(tmp_path / 'consent.key')
    return Issuer(tmp_path / 'totp', tmp_path / 'consent.key', tmp_path / 'state', 'test issuer', clock)


def _recover(tmp_path: Path, issuer: Issuer, clock: Clock, data: dict[str, Any] = PLAN) -> list[dict[str, Any]]:
    path = tmp_path / 'plan.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    sent: list[dict[str, Any]] = []

    def send(_table: object, payload: dict[str, Any]) -> tuple[int, str]:
        sent.append(payload)
        return 0, serve.handle(issuer, json.dumps(payload))

    table = {'endpoint': 'consent@forge', 'public_key': public_text(issuer.public())}
    written = recover(path, parsed(data).digest[:DIGEST_SHOWN], table=table, send=send, home=tmp_path / 'home',
                      now=clock)  # fmt: skip
    assert all('code' not in payload for payload in sent)  # no code is ever asked
    return [json.loads(found.read_text(encoding='utf-8')) for found in written]


def _same(credentials: list[dict[str, Any]]) -> list[str]:
    """Each credential's canonical bytes, sorted: equal lists are the same signed credentials."""
    return sorted(json.dumps(found, sort_keys=True) for found in credentials)


def test_a_lost_credential_comes_back_byte_for_byte_without_a_code(
    tmp_path: Path, issuer: Issuer, clock: Clock
) -> None:
    """The planted control of every refusal below."""
    issued = issuer.issue_plan(PLAN, code(0))
    assert _same(_recover(tmp_path, issuer, clock)) == _same(issued)


def test_a_spent_credential_is_never_revived(tmp_path: Path, issuer: Issuer, clock: Clock) -> None:
    first, second = issuer.issue_plan(PLAN, code(0))
    issuer.register(first)
    assert _recover(tmp_path, issuer, clock) == [second]
    with pytest.raises(ConsentRefused, match='already used'):
        issuer.register(first)


def test_an_expired_credential_is_never_revived(tmp_path: Path, issuer: Issuer, clock: Clock) -> None:
    issuer.issue_plan(PLAN, code(0))
    clock.now += 2 * 3600  # past ops.config's and ops.forge.revoke's 15 min default, and every skew
    assert _recover(tmp_path, issuer, clock) == []


def test_two_codes_for_one_plan_never_return_more_than_its_grants(tmp_path: Path, issuer: Issuer, clock: Clock) -> None:
    issuer.issue_plan(PLAN, code(0))
    clock.now += STEP
    later = issuer.issue_plan(PLAN, code(1))
    assert _same(_recover(tmp_path, issuer, clock)) == _same(later)


def test_a_grant_whose_earlier_credential_was_used_is_done_and_not_returned(
    tmp_path: Path, issuer: Issuer, clock: Clock
) -> None:
    first, _ = issuer.issue_plan(PLAN, code(0))
    issuer.register(first)
    clock.now += STEP
    _, later_revoke = issuer.issue_plan(PLAN, code(1))
    assert _recover(tmp_path, issuer, clock) == [later_revoke]


def test_another_plans_credentials_are_never_returned(tmp_path: Path, issuer: Issuer, clock: Clock) -> None:
    issuer.issue_plan(OTHER, code(0))
    assert _recover(tmp_path, issuer, clock) == []
    assert len(_recover(tmp_path, issuer, clock, OTHER)) == 1  # the control: its own plan gets it


def test_a_lone_grant_is_never_fetched(tmp_path: Path, issuer: Issuer, clock: Clock) -> None:
    issuer.issue(request(APPLY), code(0))  # no plan: nothing is kept to re-deliver
    assert not (issuer.state / 'issued').exists()
    assert _recover(tmp_path, issuer, clock) == []


def test_the_issuer_refuses_anything_but_a_full_digest(issuer: Issuer) -> None:
    with pytest.raises(ConsentRefused, match='full SHA-256'):
        issuer.unspent(parsed(PLAN).digest[:DIGEST_SHOWN])
    assert issuer.unspent(parsed(PLAN).digest) == []  # the control


def test_the_client_refuses_a_credential_outside_the_plan(tmp_path: Path, issuer: Issuer, clock: Clock) -> None:
    foreign = issuer.issue_plan(OTHER, code(0))
    path = tmp_path / 'plan.json'
    path.write_text(json.dumps(PLAN), encoding='utf-8')
    table = {'endpoint': 'consent@forge', 'public_key': public_text(issuer.public())}
    with pytest.raises(ConsentRefused, match='does not grant once'):
        recover(path, parsed(PLAN).digest[:DIGEST_SHOWN], table=table, send=lambda _t, _p: (0, json.dumps(foreign)),
                home=tmp_path / 'home', now=clock)  # fmt: skip
    assert not (tmp_path / 'home').exists() or not any((tmp_path / 'home').rglob('*.json'))


TWO_HOSTS = {'hosts': [HOST, 'ops@judge.example.org'],
             'grants': [APPLY, APPLY | {'host': 'ops@judge.example.org'}]}  # fmt: skip


def test_one_pair_on_two_hosts_comes_back_once_per_grant(tmp_path: Path, issuer: Issuer, clock: Clock) -> None:
    first, second = issuer.issue_plan(TWO_HOSTS, code(0))
    assert _same(_recover(tmp_path, issuer, clock, TWO_HOSTS)) == _same([first, second])
    issuer.register(first)  # the first host's step ran: only the second host's credential is still owed
    assert _recover(tmp_path, issuer, clock, TWO_HOSTS) == [second]
    clock.now += STEP
    issuer.issue_plan(TWO_HOSTS, code(1))  # a second code never returns more than the plan's two grants
    assert len(_recover(tmp_path, issuer, clock, TWO_HOSTS)) == 1
