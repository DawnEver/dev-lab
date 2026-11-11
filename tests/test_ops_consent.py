"""Consent credentials: one issuer signs, any verifier checks offline, an irreversible use registers online.

Every refusal has its planted control: the same call with the one fault removed passes.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from _ops_fixtures import NOW, RFC_KEY, code
from lab_commons.home import HOME_ENV

from dev_lab.dev.consentguard import refuse_write, state_dir
from dev_lab.ops import __main__ as ops_main
from dev_lab.ops import consentverbs
from dev_lab.ops.config import OpsConfig, load
from dev_lab.ops.consent import serve
from dev_lab.ops.consent.actions import ACTIONS
from dev_lab.ops.consent.client import grant, public_key, redeem, remote_register
from dev_lab.ops.consent.credential import FIELDS, SKEW_S, ConsentRefused, public_text, verify
from dev_lab.ops.consent.issuer import Issuer, keygen
from dev_lab.ops.totp import STEP

WAVE = {'action': 'breakglass.wave', 'subject': 'dev-lab wave', 'params': {'hours': 4, 'max_merges': 3}}
BUDGET = {'action': 'budget.approve', 'subject': 'hpc campaign 7', 'params': {}, 'cap': 5}


@dataclass
class Host:
    tmp: Path
    clock: list[float] = field(default_factory=lambda: [NOW])

    def __post_init__(self) -> None:
        """Enrol the TOTP secret and make the signing key."""
        (self.tmp / 'totp').write_text(RFC_KEY + '\n', encoding='utf-8')
        keygen(self.tmp / 'consent.key')

    @property
    def issuer(self) -> Issuer:
        return Issuer(self.tmp / 'totp', self.tmp / 'consent.key', self.tmp / 'state', 'test issuer',
                      lambda: self.clock[0], lockout_after=3)  # fmt: skip

    def code(self) -> str:
        return code(int((self.clock[0] - NOW) // STEP))

    def issue(self, request: dict[str, Any]) -> dict[str, Any]:
        credential = self.issuer.issue(request, self.code())
        self.clock[0] += STEP  # the next code is a fresh step
        return credential


@pytest.fixture
def host(tmp_path: Path) -> Host:
    return Host(tmp_path)


def test_a_valid_credential_verifies_and_registers(host: Host) -> None:
    """The planted control of every refusal below."""
    credential = host.issue(WAVE)
    found = redeem(credential, action='breakglass.wave', subject=None, key=host.issuer.public(),
                   register=host.issuer.register, now=host.clock[0])  # fmt: skip
    assert (found.action, found.params, found.cap) == ('breakglass.wave', {'hours': 4, 'max_merges': 3}, None)
    assert found.expires - found.issued == ACTIONS['breakglass.wave'].default_ttl


@pytest.mark.parametrize('name', [name for name in FIELDS if name != 'sig'])
def test_tampering_with_any_field_fails_verification(host: Host, name: str) -> None:
    credential = host.issue(WAVE)
    changed = {'id': 'other', 'action': 'review.raise-cap', 'subject': 'x', 'params': {'hours': 24, 'max_merges': 3},
               'params_hash': '0' * 64, 'scope': 'campaign', 'cap': 9, 'issued': NOW - 1, 'expires': NOW + 9e4,
               'issuer': 'mallory'}  # fmt: skip
    with pytest.raises(ConsentRefused):
        verify(credential | {name: changed[name]}, host.issuer.public(), now=host.clock[0])
    verify(credential, host.issuer.public(), now=host.clock[0])  # the control


def test_another_key_or_a_dropped_field_fails(host: Host) -> None:
    credential = host.issue(WAVE)
    with pytest.raises(ConsentRefused, match='signature'):
        verify(credential, keygen(host.tmp / 'other.key').public_key(), now=host.clock[0])
    with pytest.raises(ConsentRefused, match='exactly the fields'):
        verify({k: v for k, v in credential.items() if k != 'subject'}, host.issuer.public(), now=host.clock[0])


def test_an_expired_credential_is_refused_past_the_skew(host: Host) -> None:
    credential = host.issue(WAVE)
    verify(credential, host.issuer.public(), now=credential['expires'] + SKEW_S)  # the control: inside the skew
    with pytest.raises(ConsentRefused, match='expired'):
        verify(credential, host.issuer.public(), now=credential['expires'] + SKEW_S + 1)


def test_a_single_credential_used_twice_is_refused(host: Host) -> None:
    credential = host.issue(WAVE)
    assert host.issuer.register(credential) is None
    with pytest.raises(ConsentRefused, match='already used'):
        host.issuer.register(credential)


def test_a_campaign_over_its_cap_is_refused(host: Host) -> None:
    credential = host.issue(BUDGET)
    assert host.issuer.register(credential, 3) == 2
    with pytest.raises(ConsentRefused, match=r'2 of 5 left; 3 asked'):
        host.issuer.register(credential, 3)
    assert host.issuer.register(credential, 2) == 0  # the control: exactly the cap


def test_an_unreachable_issuer_refuses_an_irreversible_action(host: Host) -> None:
    credential = host.issue(WAVE)

    def down(_credential: object, _amount: int) -> object:
        unreachable = 'no route to host'
        raise ConnectionError(unreachable)

    with pytest.raises(ConsentRefused, match='refused, never admitted'):
        redeem(
            credential,
            action='breakglass.wave',
            subject=None,
            key=host.issuer.public(),
            register=down,
            now=host.clock[0],
        )


def test_an_issuer_answering_nonzero_over_ssh_is_unreachable_and_two_is_its_refusal(host: Host) -> None:
    credential = host.issue(WAVE)
    for status, kind in ((255, 'never admitted'), (2, 'already used')):
        register = remote_register({'endpoint': 'c@h'}, send=lambda _t, _r, s=status: (s, 'already used'))
        with pytest.raises(ConsentRefused, match=kind):
            redeem(
                credential,
                action='breakglass.wave',
                subject=None,
                key=host.issuer.public(),
                register=register,
                now=host.clock[0],
            )


def test_a_credential_for_another_action_is_refused(host: Host) -> None:
    credential = host.issue(BUDGET)
    with pytest.raises(ConsentRefused, match=r'not breakglass.wave'):
        redeem(credential, action='breakglass.wave', subject=None, key=host.issuer.public(),
               register=host.issuer.register, now=host.clock[0])  # fmt: skip


def test_a_reused_totp_code_is_refused(host: Host) -> None:
    used = host.code()
    host.issuer.issue(WAVE, used)
    with pytest.raises(ConsentRefused, match='already used'):
        host.issuer.issue(WAVE, used)


def test_wrong_codes_lock_every_code_out(host: Host) -> None:
    locked: list[float] = []
    issuer = host.issuer
    issuer.on_lock = locked.append
    for _ in range(3):
        with pytest.raises(ConsentRefused):
            issuer.issue(WAVE, '000000')
    with pytest.raises(ConsentRefused, match='too many wrong codes'):
        issuer.issue(WAVE, host.code())
    assert len(locked) == 1


@pytest.mark.parametrize(
    ('request_', 'why'),
    [
        (WAVE | {'ttl': 24 * 3600 + 1}, 'ttl must be'),
        ({**WAVE, 'action': 'merge.anything'}, 'action must be'),
        (WAVE | {'params': {'hours': 4}}, 'params are exactly'),
        (WAVE | {'cap': 3}, 'carries no cap'),
        ({k: v for k, v in BUDGET.items() if k != 'cap'}, 'cap must be'),
        (WAVE | {'scope': 'campaign'}, 'single only'),
        ({'action': 'review.raise-cap', 'subject': 's', 'params': {'cap': 3}, 'ttl': 16 * 60}, 'ttl must be'),
    ],
)
def test_a_request_the_registry_refuses_spends_no_code(host: Host, request_: dict[str, Any], why: str) -> None:
    valid = host.code()
    with pytest.raises(ConsentRefused, match=why):
        host.issuer.issue(request_, valid)
    longest = host.issuer.issue(WAVE | {'ttl': 24 * 3600}, valid)  # the control: the max TTL, and the code unspent
    assert longest['expires'] - longest['issued'] == 24 * 3600


def test_the_ledger_records_id_action_and_subject_only(host: Host) -> None:
    credential = host.issue(WAVE)
    host.issuer.register(credential)
    text = host.issuer.ledger.read_text(encoding='utf-8')
    lines = [json.loads(line) for line in text.splitlines()]
    assert [set(line) for line in lines] == [{'event', 'id', 'action', 'subject'},
                                             {'event', 'id', 'action', 'subject', 'amount'}]  # fmt: skip
    assert credential['sig'] not in text
    assert RFC_KEY not in text


def test_the_code_the_user_gave_is_passed_by_the_agent(host: Host, tmp_path: Path) -> None:
    """The USER supplies the code; the agent runs the grant with it (user ruling 2026-11-08): an argument, or stdin."""
    request = tmp_path / 'request.json'
    request.write_text(json.dumps(WAVE), encoding='utf-8')
    table = {'endpoint': 'consent@forge', 'public_key': public_text(host.issuer.public())}
    asked: list[str] = []

    def ask(prompt: str) -> str:
        asked.append(prompt)
        return host.code()

    def send(_table: object, line: dict[str, Any]) -> tuple[int, str]:
        return 0, serve.handle(host.issuer, json.dumps({k: line[k] for k in line}))

    def run(*, tty: bool, code: str | None = None, read: Callable[[], str] = str) -> Path:
        return grant(
            request, table=table, code=code, tty=tty, ask=ask, read=read, send=send, home=tmp_path,
            now=lambda: host.clock[0],
        )  # fmt: skip

    written = run(code=host.code(), tty=False)
    assert written.parent == state_dir(tmp_path)
    assert json.loads(written.read_text(encoding='utf-8'))['action'] == 'breakglass.wave'
    host.clock[0] += STEP  # a fresh TOTP step: a code is single-use
    assert run(tty=False, read=lambda: host.code() + '\n').parent == state_dir(tmp_path)  # stdin, not a terminal
    assert not asked  # neither path prompted
    host.clock[0] += STEP
    assert run(tty=True).parent == state_dir(tmp_path)  # the control: a terminal prompts
    assert asked


def test_a_code_that_is_not_six_digits_is_refused_before_it_is_sent(host: Host, tmp_path: Path) -> None:
    request = tmp_path / 'request.json'
    request.write_text(json.dumps(WAVE), encoding='utf-8')
    sent: list[object] = []

    def send(_table: object, line: dict[str, Any]) -> tuple[int, str]:
        sent.append(line)
        return 1, 'unreached'

    table = {'endpoint': 'consent@forge', 'public_key': public_text(host.issuer.public())}
    with pytest.raises(ConsentRefused, match='six digits'):
        grant(request, table=table, code='12345', tty=False, send=send, home=tmp_path)
    with pytest.raises(ConsentRefused, match='six digits'):
        grant(request, table=table, tty=False, read=lambda: '', send=send, home=tmp_path)
    assert not sent


def test_the_public_key_comes_from_the_machine_file_else_refuses(host: Host) -> None:
    text = public_text(host.issuer.public())
    assert public_text(public_key({'public_key': text})) == text
    with pytest.raises(ConsentRefused, match='no consent public key'):
        public_key({})


def test_an_agent_write_under_the_consent_state_is_refused(tmp_path: Path) -> None:
    assert refuse_write(state_dir(tmp_path) / 'x.json', home=tmp_path) is not None
    assert refuse_write(tmp_path / 'state' / 'other.json', home=tmp_path) is None  # the control


def test_the_consent_state_lives_under_the_declared_machine_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(HOME_ENV, str(tmp_path / 'acme-home'))
    assert state_dir() == tmp_path / 'acme-home' / 'state' / 'consent'


def _judge_host(tmp: Path, client: str) -> OpsConfig:
    """A host that is NOT the issuer (no ``[ops.consent]``): only *client* says where consent is verified."""
    path = tmp / 'judge.toml'
    path.write_text(f'[ops]\nhome = "{(tmp / "home").as_posix()}"\npython = "/opt/ops/bin/python"\n{client}',
                    encoding='utf-8')  # fmt: skip
    return load(path, environ={}, as_root=False)


def _client(host: Host) -> str:
    key = public_text(host.issuer.public()).strip()
    return (
        f'[ops.consent_client]\nendpoint = "consent@issuer"\npublic_key = "{key}"\n'
        'known_hosts = "/srv/ops/ssh/consent_known_hosts"\n'
    )


def test_a_host_that_is_not_the_issuer_redeems_at_the_issuer_over_its_endpoint(
    host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[Any] = []

    def send(table: Mapping[str, Any], request: dict[str, Any]) -> tuple[int, str]:
        sent.append((table['endpoint'], table['known_hosts']))
        try:
            return 0, serve.handle(host.issuer, json.dumps(request))
        except ConsentRefused as refused:
            return 2, str(refused)

    monkeypatch.setattr(consentverbs, 'remote_register', lambda table: remote_register(table, send=send))
    monkeypatch.setattr(ops_main.time, 'time', lambda: host.clock[0])
    judge = _judge_host(host.tmp, _client(host))
    assert judge.consent is None
    credential = host.issue(WAVE)
    redeem_wave = ops_main._redeemer(judge)('breakglass.wave')
    assert redeem_wave(credential, None).action == 'breakglass.wave'
    assert sent == [('consent@issuer', '/srv/ops/ssh/consent_known_hosts')]
    with pytest.raises(ConsentRefused, match='already used'):  # registered AT the issuer: its ledger refuses a reuse
        redeem_wave(credential, None)


def test_a_host_with_neither_issuer_nor_client_table_names_the_key_to_set(host: Host) -> None:
    with pytest.raises(ConsentRefused, match=r'\[ops\.consent_client\] endpoint'):
        ops_main._redeemer(_judge_host(host.tmp, ''))
    ops_main._redeemer(_judge_host(host.tmp, _client(host)))  # the control
