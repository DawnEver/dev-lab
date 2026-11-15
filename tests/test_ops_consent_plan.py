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

from dev_lab.dev import sshhold, sshholdwire
from dev_lab.ops.consent import serve
from dev_lab.ops.consent.client import grant_plan, redeem
from dev_lab.ops.consent.credential import ConsentRefused, public_text
from dev_lab.ops.consent.issuer import Issuer, keygen
from dev_lab.ops.consent.plan import DIGEST_SHOWN, load, parsed, request, show
from dev_lab.ops.consentrole import Consent
from dev_lab.ops.consentverbs import issuer as issuer_of
from dev_lab.ops.totp import STEP

HOST = 'ops@forge.example.org'
JUDGE = 'ops@judge.example.org'
APPLY = {'host': HOST, 'action': 'ops.config', 'subject': 'a' * 64}
REVOKE = {'host': HOST, 'action': 'ops.forge.revoke', 'subject': 'b' * 64}
PLAN = {'hosts': [HOST], 'grants': [APPLY, REVOKE]}


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
    assert issuer.issue(request(APPLY), code(0))['plan'] is None
    forged = issuer.issue_plan(PLAN, code(1))[0] | {'plan': parsed({**PLAN, 'hosts': [HOST, JUDGE]}).digest}
    with pytest.raises(ConsentRefused, match='signature'):
        redeem(forged, action='ops.config', subject=APPLY['subject'], key=issuer.public(), register=issuer.register,
               now=NOW)  # fmt: skip


def test_a_credential_issued_from_plan_a_is_refused_for_plan_b(
    tmp_path: Path, issuer: Issuer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plan B grants the same pairs as plan A; an issuer answering B's credentials for A is refused by the digest."""
    monkeypatch.setenv(HOME_ENV, str(tmp_path / 'home'))
    answered = json.dumps(issuer.issue_plan({**PLAN, 'hosts': [HOST, JUDGE]}, code(0)))
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


def test_a_plan_not_naming_the_session_host_is_refused_before_a_code_is_spent(
    tmp_path: Path, issuer: Issuer, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = {'hosts': [JUDGE], 'grants': [APPLY | {'host': JUDGE}]}
    path, shown = _plan(tmp_path, other)
    with pytest.raises(ConsentRefused, match=r'not ops@forge\.example\.org'):
        _grant(tmp_path, issuer, path, shown, monkeypatch)
    assert not issuer.ledger.exists()
    path, shown = _plan(tmp_path, {**other, 'hosts': [JUDGE, HOST]})  # the control: HOST is one of its hosts
    assert len(_grant(tmp_path, issuer, path, shown, monkeypatch)) == 1


def test_a_grant_naming_a_host_outside_the_plan_is_refused() -> None:
    """PLANTED: the same plan with the grant's host listed parses."""
    with pytest.raises(ConsentRefused, match='not one of the plan hosts'):
        parsed({'hosts': [HOST], 'grants': [APPLY, REVOKE | {'host': JUDGE}]})
    assert parsed({'hosts': [HOST, JUDGE], 'grants': [APPLY, REVOKE | {'host': JUDGE}]}).hosts == (HOST, JUDGE)


def test_the_digest_covers_every_host_and_where_each_grant_runs() -> None:
    """Moving a grant to another host, or adding a host, is another plan; the control: the same plan, same digest."""
    two = {'hosts': [HOST, JUDGE], 'grants': [APPLY, REVOKE]}
    moved = {'hosts': [HOST, JUDGE], 'grants': [APPLY, REVOKE | {'host': JUDGE}]}
    digests = {parsed(data).digest for data in (PLAN, two, moved)}
    assert len(digests) == 3
    assert parsed(json.loads(json.dumps(moved))).digest == parsed(moved).digest


def test_a_plan_in_the_retired_single_host_shape_is_refused_by_name_with_its_migration() -> None:
    """D51: migrates once, never upgraded on read. PLANTED: its migrated form parses."""
    retired = {'host': HOST, 'grants': [{'action': 'ops.config', 'subject': 'a' * 64}]}
    with pytest.raises(ConsentRefused, match='retired single-host shape: migrate it once'):
        parsed(retired)
    assert parsed({'hosts': [HOST], 'grants': [APPLY]}).hosts == (HOST,)


def test_a_reused_credential_is_refused(tmp_path: Path, issuer: Issuer, monkeypatch: pytest.MonkeyPatch) -> None:
    written = _grant(tmp_path, issuer, *_plan(tmp_path), monkeypatch)
    _redeem(issuer, written[1], 'ops.forge.revoke', REVOKE['subject'])
    with pytest.raises(ConsentRefused, match='already used'):
        _redeem(issuer, written[1], 'ops.forge.revoke', REVOKE['subject'])


@pytest.mark.parametrize(
    ('data', 'match'),
    [
        ({'hosts': [HOST], 'grants': []}, 'non-empty'),
        ({'hosts': [], 'grants': [APPLY]}, '<user>@<host>'),
        ({'hosts': ['forge'], 'grants': [APPLY]}, '<user>@<host>'),
        ({'hosts': [HOST, HOST], 'grants': [APPLY]}, 'distinct'),
        ({'hosts': [HOST], 'grants': [APPLY, APPLY]}, 'twice on one host.*drop the repeated grant'),
        ({'hosts': [HOST], 'grants': [{'action': 'ops.config', 'subject': 'a'}]}, 'naming a host'),
        ({'hosts': [HOST], 'grants': [APPLY], 'extra': 1}, 'exactly hosts and grants'),
    ],
)
def test_a_malformed_plan_is_refused(data: dict[str, Any], match: str) -> None:
    with pytest.raises(ConsentRefused, match=match):
        parsed(data)
    parsed(PLAN)  # the control


def test_an_unregistered_grant_is_refused_before_the_code(issuer: Issuer) -> None:
    with pytest.raises(ConsentRefused, match='action must be one of'):
        issuer.issue_plan(
            {'hosts': [HOST], 'grants': [{'host': HOST, 'action': 'root.everything', 'subject': 'x'}]}, code(0)
        )
    assert len(issuer.issue_plan(PLAN, code(0))) == 2  # the control: the refusal spent no step


def test_show_names_every_grant_and_the_digest(tmp_path: Path) -> None:
    path, shown = _plan(tmp_path)
    said = show(path)
    assert said.startswith(f'plan {shown}: one code opens {HOST}')
    assert APPLY['subject'] in said
    assert REVOKE['subject'] in said
    assert load(path, shown).hosts == (HOST,)


def _open_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, refuse: str = '', late: bool = False
) -> tuple[bool, list[str], list[str]]:
    path, shown = _plan(tmp_path, {'hosts': [HOST, JUDGE], 'grants': [APPLY, REVOKE | {'host': JUDGE}]})
    order: list[str] = []
    monkeypatch.setenv(HOME_ENV, str(tmp_path / 'home'))

    def grant(plan: Path, shown_: str, given: str, host: str) -> list[Path]:
        order.append(f'grant {given} {host}')
        return [tmp_path / 'one.json'] if parsed(json.loads(plan.read_text())).digest.startswith(shown_) else []

    def opener(dest: str, _hours: float, given: str, *, ssh: tuple[str, ...]) -> str:
        del ssh
        order.append(f'open {given} {dest}')
        if dest == refuse:
            msg = f'{dest} did not authenticate: unreachable'
            raise sshholdwire.HoldRefused(msg)
        return f'{dest}: open'

    ticks = iter([0.0, sshhold.OPEN_WINDOW_S + 1 if late else 1.0])
    opened, lines = sshhold.open_planned(
        1, '123456', path, shown, grant=grant, opener=opener, clock=lambda: next(ticks)
    )
    return opened, lines, order


def test_sshhold_grants_first_then_opens_every_plan_host_with_the_one_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The planted control of the failure paths below."""
    opened, lines, order = _open_two(tmp_path, monkeypatch)
    assert opened
    assert order[0] == f'grant 123456 {HOST}'
    assert sorted(order[1:]) == [f'open 123456 {HOST}', f'open 123456 {JUDGE}']
    assert lines[-2:] == [f'{HOST}: open', f'{JUDGE}: open']
    assert STEP == 30  # one code: every verifier accepts it inside the same step


def test_a_host_unreachable_mid_open_is_reported_and_never_retried_with_the_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened, lines, order = _open_two(tmp_path, monkeypatch, refuse=JUDGE)
    assert not opened
    assert order.count(f'open 123456 {JUDGE}') == 1  # never retried
    assert lines[-2] == f'{HOST}: open'  # the other host still opened
    assert lines[-1].startswith(f'{JUDGE}: NOT opened')
    assert f'sshhold open {JUDGE} --hours 1' in lines[-1]


def test_a_grant_past_the_window_sends_the_code_to_no_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    opened, lines, order = _open_two(tmp_path, monkeypatch, late=True)
    assert not opened
    assert order == [f'grant 123456 {HOST}']
    assert all('window' in line for line in lines[-2:])


def test_open_names_a_dest_or_a_plan_exactly_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(HOME_ENV, str(tmp_path / 'home'))
    path, shown = _plan(tmp_path)
    assert sshhold.main(['open', HOST, '--hours', '1', '--code', '123456', '--plan', str(path), '--digest', shown]) == 2
    assert sshhold.main(['open', '--hours', '1', '--code', '123456']) == 2


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


def _grants(count: int) -> list[dict[str, str]]:
    return [{'host': HOST, 'action': 'ops.config', 'subject': f'{index:064x}'} for index in range(count)]


def test_a_plan_over_the_declared_max_grants_is_refused_naming_the_key(tmp_path: Path) -> None:
    """The cap is ``[ops.consent] max_grants``, read from the role -- never a constant; one AT the cap passes."""
    (tmp_path / 'totp').write_text(RFC_KEY + '\n', encoding='utf-8')
    keygen(tmp_path / 'consent.key')
    small = Issuer(tmp_path / 'totp', tmp_path / 'consent.key', tmp_path / 'state', 'test', lambda: NOW, max_grants=3)
    with pytest.raises(ConsentRefused, match=r'\[ops\.consent\] max_grants = 3'):
        small.issue_plan({'hosts': [HOST], 'grants': _grants(4)}, code(0))
    assert not small.ledger.exists()  # refused before the code
    assert len(small.issue_plan({'hosts': [HOST], 'grants': _grants(3)}, code(0))) == 3


def test_the_issuer_reads_max_grants_from_its_declared_role() -> None:
    role = Consent(account='consent', totp='t', key='k', state='s', max_grants=40)
    assert issuer_of(role, alert=lambda *_: None).max_grants == 40
    assert Consent(account='consent', totp='t', key='k', state='s').max_grants == 16


def test_show_groups_by_host_and_action_and_names_the_boundary_grants(tmp_path: Path) -> None:
    """PLANTED: a boundary grant (ops.config) is in the summary; a non-boundary one (review.raise-cap) is not."""
    raise_cap = {'host': JUDGE, 'action': 'review.raise-cap', 'subject': 'r' * 8}
    grants = [APPLY, raise_cap, REVOKE, APPLY | {'subject': 'd' * 64}]
    path, _ = _plan(tmp_path, {'hosts': [HOST, JUDGE], 'grants': grants})
    lines = show(path).splitlines()
    summary = next(line for line in lines if line.startswith('boundary:'))
    assert 'ops.config x2' in summary
    assert 'ops.forge.revoke x1' in summary
    assert 'review.raise-cap' not in summary
    assert f'  {HOST}' in lines
    assert lines.index('    ops.config (2)') < lines.index(f'      {APPLY["subject"]}')
    assert '    review.raise-cap (1)' in lines
    assert lines.index(f'  {JUDGE}') < lines.index('    review.raise-cap (1)')  # under its own host


TWO_HOSTS = {'hosts': [HOST, JUDGE], 'grants': [APPLY, APPLY | {'host': JUDGE}]}


def test_one_pair_on_two_hosts_is_two_grants_and_one_code_grants_both(
    tmp_path: Path, issuer: Issuer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A grant is (host, action, subject): one sha upgraded on two hosts is two grants; the same host twice is one."""
    assert len(parsed(TWO_HOSTS).grants) == 2
    written = _grant(tmp_path, issuer, *_plan(tmp_path, TWO_HOSTS), monkeypatch)
    assert len(written) == 2
    for path in written:  # each single-use credential redeems once
        _redeem(issuer, path, 'ops.config', APPLY['subject'])
    with pytest.raises(ConsentRefused, match='twice on one host'):  # the planted control
        parsed({'hosts': [HOST, JUDGE], 'grants': [APPLY, APPLY]})
