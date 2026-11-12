"""One code, one plan: a plan's ONE code buys one single-use credential per listed grant, and nothing else.

Every refusal has its planted control: the same call with the one fault removed passes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from _ops_fixtures import NOW, RFC_KEY, code
from lab_commons.home import HOME_ENV

from dev_lab.dev import sshhold
from dev_lab.ops.consent import serve
from dev_lab.ops.consent.client import grant_plan, redeem
from dev_lab.ops.consent.credential import ConsentRefused, public_text
from dev_lab.ops.consent.issuer import Issuer, keygen
from dev_lab.ops.consent.plan import DIGEST_SHOWN, load, parsed, show
from dev_lab.ops.totp import STEP

HOST = 'ops@forge.example.org'
APPLY = {'action': 'ops.config', 'subject': 'a' * 64}
REVOKE = {'action': 'ops.forge.revoke', 'subject': 'b' * 64}
PLAN = {'host': HOST, 'grants': [APPLY, REVOKE]}


@pytest.fixture
def issuer(tmp_path: Path) -> Issuer:
    (tmp_path / 'totp').write_text(RFC_KEY + '\n', encoding='utf-8')
    keygen(tmp_path / 'consent.key')
    return Issuer(tmp_path / 'totp', tmp_path / 'consent.key', tmp_path / 'state', 'test issuer', lambda: NOW)


def _plan(tmp_path: Path, data: dict[str, Any] = PLAN) -> tuple[Path, str]:
    path = tmp_path / 'plan.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    return path, parsed(data).digest[:DIGEST_SHOWN]


def _grant(tmp_path: Path, issuer: Issuer, path: Path, shown: str, monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    monkeypatch.setenv(HOME_ENV, str(tmp_path / 'home'))
    table = {'endpoint': 'consent@forge', 'public_key': public_text(issuer.public())}

    def send(_table: object, payload: dict[str, Any]) -> tuple[int, str]:
        try:
            return 0, serve.handle(issuer, json.dumps(payload))
        except ConsentRefused as refused:
            return 2, str(refused)

    return grant_plan(path, shown, code(0), HOST, table=table, send=send, home=tmp_path / 'home', now=lambda: NOW)


def _redeem(issuer: Issuer, written: Path, action: str, subject: str) -> object:
    credential = json.loads(written.read_text(encoding='utf-8'))
    return redeem(credential, action=action, subject=subject, key=issuer.public(), register=issuer.register, now=NOW)


def test_one_code_grants_one_credential_per_listed_grant(
    tmp_path: Path, issuer: Issuer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The planted control of every refusal below."""
    written = _grant(tmp_path, issuer, *_plan(tmp_path), monkeypatch)
    actions = [json.loads(path.read_text(encoding='utf-8'))['action'] for path in written]
    assert actions == ['ops.config', 'ops.forge.revoke']
    _redeem(issuer, written[0], 'ops.config', APPLY['subject'])
    _redeem(issuer, written[1], 'ops.forge.revoke', REVOKE['subject'])
    digest = parsed(PLAN).digest
    granted = [json.loads(line) for line in issuer.ledger.read_text(encoding='utf-8').splitlines()]
    assert {line['plan'] for line in granted if line['event'] == 'granted'} == {digest}


def test_each_credential_signs_the_digest_of_its_plan_and_a_lone_one_none(issuer: Issuer) -> None:
    digest = parsed(PLAN).digest
    assert {credential['plan'] for credential in issuer.issue_plan(PLAN, code(-1))} == {digest}
    assert issuer.issue(APPLY, code(0))['plan'] is None
    forged = issuer.issue_plan(PLAN, code(1))[0] | {'plan': parsed({**PLAN, 'host': 'ops@other'}).digest}
    with pytest.raises(ConsentRefused, match='signature'):
        redeem(forged, action='ops.config', subject=APPLY['subject'], key=issuer.public(), register=issuer.register,
               now=NOW)  # fmt: skip


def test_a_credential_issued_from_plan_a_is_refused_for_plan_b(
    tmp_path: Path, issuer: Issuer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plan B grants the same pairs as plan A; an issuer answering B's credentials for A is refused by the digest."""
    monkeypatch.setenv(HOME_ENV, str(tmp_path / 'home'))
    answered = json.dumps(issuer.issue_plan({**PLAN, 'host': 'ops@other.example.org'}, code(0)))
    path, shown = _plan(tmp_path)
    table = {'endpoint': 'consent@forge', 'public_key': public_text(issuer.public())}
    with pytest.raises(ConsentRefused, match='not of'):
        grant_plan(path, shown, code(0), HOST, table=table, send=lambda _t, _p: (0, answered),
                   home=tmp_path / 'home', now=lambda: NOW)  # fmt: skip
    mine = json.dumps(issuer.issue_plan(PLAN, code(1)))  # the control: the plan's own credentials are accepted
    assert len(grant_plan(path, shown, code(0), HOST, table=table, send=lambda _t, _p: (0, mine),
                          home=tmp_path / 'home', now=lambda: NOW)) == 2  # fmt: skip


def test_the_one_code_is_spent_once_at_the_issuer(
    tmp_path: Path, issuer: Issuer, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, shown = _plan(tmp_path)
    _grant(tmp_path, issuer, path, shown, monkeypatch)
    with pytest.raises(ConsentRefused):
        _grant(tmp_path, issuer, path, shown, monkeypatch)


def test_a_subject_outside_the_plan_is_refused_and_the_credential_is_not_spent(
    tmp_path: Path, issuer: Issuer, monkeypatch: pytest.MonkeyPatch
) -> None:
    written = _grant(tmp_path, issuer, *_plan(tmp_path), monkeypatch)
    with pytest.raises(ConsentRefused, match='another request'):
        _redeem(issuer, written[0], 'ops.config', 'c' * 64)
    _redeem(issuer, written[0], 'ops.config', APPLY['subject'])  # the control: not spent by the refusal


def test_a_plan_changed_after_it_was_shown_is_refused_before_a_code_is_spent(
    tmp_path: Path, issuer: Issuer, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, shown = _plan(tmp_path)
    path.write_text(json.dumps(PLAN | {'grants': [APPLY, REVOKE | {'subject': 'c' * 64}]}), encoding='utf-8')
    with pytest.raises(ConsentRefused, match='not the one shown'):
        _grant(tmp_path, issuer, path, shown, monkeypatch)
    assert not issuer.ledger.exists()  # nothing granted, no step spent
    _, shown_again = _plan(tmp_path, json.loads(path.read_text(encoding='utf-8')))
    assert len(_grant(tmp_path, issuer, path, shown_again, monkeypatch)) == 2  # the control


def test_a_plan_for_another_host_is_refused_before_a_code_is_spent(
    tmp_path: Path, issuer: Issuer, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, shown = _plan(tmp_path, PLAN | {'host': 'ops@other.example.org'})
    with pytest.raises(ConsentRefused, match=r'not ops@forge\.example\.org'):
        _grant(tmp_path, issuer, path, shown, monkeypatch)
    assert not issuer.ledger.exists()


def test_a_reused_credential_is_refused(tmp_path: Path, issuer: Issuer, monkeypatch: pytest.MonkeyPatch) -> None:
    written = _grant(tmp_path, issuer, *_plan(tmp_path), monkeypatch)
    _redeem(issuer, written[1], 'ops.forge.revoke', REVOKE['subject'])
    with pytest.raises(ConsentRefused, match='already used'):
        _redeem(issuer, written[1], 'ops.forge.revoke', REVOKE['subject'])


@pytest.mark.parametrize(
    ('data', 'match'),
    [
        ({'host': HOST, 'grants': []}, '1..16'),
        ({'host': 'forge', 'grants': [APPLY]}, '<user>@<host>'),
        ({'host': HOST, 'grants': [APPLY, APPLY]}, 'twice'),
        ({'host': HOST, 'grants': [APPLY], 'extra': 1}, 'exactly host and grants'),
    ],
)
def test_a_malformed_plan_is_refused(data: dict[str, Any], match: str) -> None:
    with pytest.raises(ConsentRefused, match=match):
        parsed(data)
    parsed(PLAN)  # the control


def test_an_unregistered_grant_is_refused_before_the_code(issuer: Issuer) -> None:
    with pytest.raises(ConsentRefused, match='action must be one of'):
        issuer.issue_plan({'host': HOST, 'grants': [{'action': 'root.everything', 'subject': 'x'}]}, code(0))
    assert len(issuer.issue_plan(PLAN, code(0))) == 2  # the control: the refusal spent no step


def test_show_names_every_grant_and_the_digest(tmp_path: Path) -> None:
    path, shown = _plan(tmp_path)
    said = show(path)
    assert said.startswith(f'plan {shown}: one code opens {HOST}')
    assert APPLY['subject'] in said
    assert REVOKE['subject'] in said
    assert load(path, shown).host == HOST


def test_sshhold_spends_the_plan_before_the_session_and_only_for_its_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, shown = _plan(tmp_path)
    order: list[str] = []
    monkeypatch.setenv(HOME_ENV, str(tmp_path / 'home'))
    monkeypatch.setattr(sshhold, 'open_session', lambda dest, *_a, **_k: order.append('session') or f'{dest}: open')

    def grant(plan: Path, shown_: str, given: str, host: str) -> list[Path]:
        order.append(f'grant {given} {host}')
        return [tmp_path / 'one.json'] if parsed(json.loads(plan.read_text())).digest.startswith(shown_) else []

    said = sshhold.open_planned(HOST, 1, '123456', path, shown, grant=grant)
    assert order == [f'grant 123456 {HOST}', 'session']
    assert said[-1] == f'{HOST}: open'
    assert STEP == 30  # one code: both verifiers accept it inside the same step


def test_a_notice_around_the_issuers_answer_does_not_lose_the_credentials(
    tmp_path: Path, issuer: Issuer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A notice beside the issuer's JSON answer never costs a spent code's credentials.

    2026-11-11 forge-a1: the host printed an upgrade-on-read notice beside the answer, the client parsed the whole
    output and lost thirteen credentials. The answer is its one JSON line.
    """
    monkeypatch.setenv(HOME_ENV, str(tmp_path / 'home'))
    table = {'endpoint': 'consent@forge', 'public_key': public_text(issuer.public())}
    path, shown = _plan(tmp_path)

    def send(_table: object, payload: dict[str, Any]) -> tuple[int, str]:
        notice = '[ops] upgraded [ops.forge] read_only on read'
        return 0, f'{notice}\n{serve.handle(issuer, json.dumps(payload))}\n{notice}\n'

    written = grant_plan(path, shown, code(0), HOST, table=table, send=send, home=tmp_path / 'home', now=lambda: NOW)
    assert len(written) == len(PLAN['grants'])


def test_two_json_answers_are_refused_rather_than_guessed(
    tmp_path: Path, issuer: Issuer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(HOME_ENV, str(tmp_path / 'home'))
    table = {'endpoint': 'consent@forge', 'public_key': public_text(issuer.public())}
    path, shown = _plan(tmp_path)
    with pytest.raises(ConsentRefused, match='2 JSON lines'):
        grant_plan(path, shown, code(0), HOST, table=table, send=lambda _t, _p: (0, '[]\n[]\n'),
                   home=tmp_path / 'home', now=lambda: NOW)  # fmt: skip
