"""The one consent door: nothing asks the user for a code that the issuer or the plan would waste.

Measured 2026-11-16: codes were wasted because (a) client and issuer disagreed on the credential field set, (b) a
plan whose subject could not be derived was granted, (c) a held host refused a planned open. Each refusal below has
its planted control: the same call with the one fault removed passes.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest
from _ops_fixtures import NOW, RFC_KEY
from lab_commons.home import HOME_ENV

from dev_lab.dev import planrunoffer, sshhold
from dev_lab.dev.consentguard import state_dir
from dev_lab.ops.consent import __main__ as consent_main
from dev_lab.ops.consent import serve
from dev_lab.ops.consent.actions import ACTIONS
from dev_lab.ops.consent.client import grant
from dev_lab.ops.consent.credential import FIELDS, ConsentRefused, public_text
from dev_lab.ops.consent.door import (
    CLIENT_UPGRADE,
    ISSUER_UPGRADE,
    PREFLIGHT_FRESH_S,
    Send,
    handshake,
    offer,
    record_preflight,
)
from dev_lab.ops.consent.issuer import Issuer, keygen
from dev_lab.ops.consent.plan import parsed

HOST = 'ops@forge.example.org'
PLAN = parsed({'hosts': [HOST], 'grants': [{'host': HOST, 'action': 'ops.config', 'subject': 'a' * 64}]})
WAVE = {'action': 'breakglass.wave', 'subject': 'w', 'params': {'hours': 1, 'max_merges': 1}}


@pytest.fixture
def issuer(tmp_path: Path) -> Issuer:
    (tmp_path / 'totp').write_text(RFC_KEY + '\n', encoding='utf-8')
    keygen(tmp_path / 'consent.key')
    return Issuer(tmp_path / 'totp', tmp_path / 'consent.key', tmp_path / 'state', 'test issuer', lambda: NOW)


class Wire:
    """The issuer over its serve verb, with the ``hello`` answer optionally skewed; every request recorded."""

    def __init__(self, issuer: Issuer, hello: dict[str, Any] | None = None, *, old: bool = False) -> None:
        """*hello* replaces the issuer's handshake answer; *old* refuses the verb as an issuer predating it."""
        self.issuer, self.hello, self.old, self.sent = issuer, hello, old, []

    def __call__(self, _table: object, request: dict[str, Any]) -> tuple[int, str]:
        self.sent.append(request['verb'])
        if request['verb'] == 'hello' and self.old:
            return 2, 'verb must be issue, issue-plan, register, spent or fetch-unspent'
        if request['verb'] == 'hello' and self.hello is not None:
            return 0, json.dumps(self.hello)
        try:
            return 0, serve.handle(self.issuer, json.dumps(request))
        except ConsentRefused as refused:
            return 2, str(refused)


def _skewed(**change: object) -> dict[str, Any]:
    return {'fields': list(FIELDS), 'actions': ['ops.config', 'breakglass.wave']} | change


def test_the_handshake_passes_an_issuer_that_speaks_this_client(issuer: Issuer) -> None:
    """The planted control of every skew below: the real serve verb answers what this client speaks."""
    handshake({}, send=Wire(issuer), actions=['ops.config'])


@pytest.mark.parametrize(
    ('hello', 'old', 'door'),
    [
        (_skewed(fields=[*FIELDS, 'audience']), False, CLIENT_UPGRADE),  # the issuer signs a field this client lacks
        (_skewed(fields=[f for f in FIELDS if f != 'plan']), False, ISSUER_UPGRADE),  # it drops one it requires
        (_skewed(actions=['breakglass.wave']), False, ISSUER_UPGRADE),  # it does not know the asked action
        (None, True, ISSUER_UPGRADE),  # it predates the handshake
    ],
)
def test_a_skewed_issuer_is_refused_before_a_code_naming_the_side_to_upgrade(
    issuer: Issuer, hello: dict[str, Any] | None, *, old: bool, door: str
) -> None:
    wire = Wire(issuer, hello, old=old)
    with pytest.raises(ConsentRefused, match='no code asked') as refused:
        handshake({}, send=wire, actions=['ops.config'])
    assert door in str(refused.value)
    assert wire.sent == ['hello']


def test_a_lone_grant_never_asks_for_the_code_of_a_skewed_issuer(issuer: Issuer, tmp_path: Path) -> None:
    """Incident (a): the code was spent, then the client refused the credential's field set."""
    request = tmp_path / 'request.json'
    request.write_text(json.dumps(WAVE), encoding='utf-8')
    table = {'endpoint': 'consent@forge', 'public_key': public_text(issuer.public())}
    asked: list[str] = []
    wire = Wire(issuer, _skewed(fields=[*FIELDS, 'audience']))
    with pytest.raises(ConsentRefused, match='no code asked'):
        grant(request, table=table, tty=True, ask=lambda p: asked.append(p) or '000000', send=wire, home=tmp_path)
    assert asked == []
    assert wire.sent == ['hello']


def test_a_plan_is_offered_only_after_a_fresh_green_preflight(issuer: Issuer, tmp_path: Path) -> None:
    """Incident (b). PLANTED CONTROL: the fresh record offers it."""
    wire = Wire(issuer)
    with pytest.raises(ConsentRefused, match=r'has no green preflight \(none recorded'):
        offer(PLAN, {}, send=wire, home=tmp_path, now=NOW)
    record_preflight(PLAN, home=tmp_path, now=NOW)
    with pytest.raises(ConsentRefused, match='s old'):
        offer(PLAN, {}, send=wire, home=tmp_path, now=NOW + PREFLIGHT_FRESH_S + 1)
    assert wire.sent == []  # refused before the issuer was even asked
    offer(PLAN, {}, send=wire, home=tmp_path, now=NOW + 1)
    assert wire.sent == ['hello']


def test_an_action_no_registry_holds_is_named_unregistered_not_an_old_client(issuer: Issuer, tmp_path: Path) -> None:
    """O17: a plan carries no dev-lab version, so 'older than the plan' was a guess that blamed the wrong cause.

    PLANTED CONTROL: the same plan with only registered actions is offered.
    """
    stray = parsed({'hosts': [HOST], 'grants': [{'host': HOST, 'action': 'hpcaccount.deploy', 'subject': 'a' * 64}]})
    record_preflight(stray, home=tmp_path, now=NOW)
    with pytest.raises(ConsentRefused) as refused:
        offer(stray, {}, send=Wire(issuer), home=tmp_path, now=NOW + 1)
    text = str(refused.value)
    assert "['hpcaccount.deploy'] not a consent action; the registered ones are" in text
    assert all(action in text for action in ACTIONS)
    assert 'older than the plan' not in text
    record_preflight(PLAN, home=tmp_path, now=NOW)
    offer(PLAN, {}, send=Wire(issuer), home=tmp_path, now=NOW + 1)


def test_consent_plan_shows_the_plan_and_offers_it_only_when_the_door_passes(
    issuer: Issuer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(HOME_ENV, str(tmp_path / 'home'))
    path = tmp_path / 'plan.json'
    path.write_text(json.dumps({'hosts': list(PLAN.hosts), 'grants': list(PLAN.grants)}), encoding='utf-8')
    assert consent_main.main(['plan', str(path)], table={}, send=Wire(issuer)) == 2
    assert 'no green preflight' in capsys.readouterr().err
    record_preflight(PLAN)
    assert consent_main.main(['plan', str(path)], table={}, send=Wire(issuer)) == 0
    assert 'offered: ask the user for the one code' in capsys.readouterr().out


def test_a_green_preflight_is_recorded_only_when_the_issuer_agrees(issuer: Issuer, tmp_path: Path) -> None:
    green = (True, ['step 1 ops.config: green', 'preflight: green, every door checked (ask the user for the code)'])
    found, lines = planrunoffer.offered(PLAN, green, table={}, send=Wire(issuer, old=True), home=tmp_path)
    assert not found
    assert lines[-2].startswith('issuer: BLOCKED -- no code asked')
    assert lines[-1].startswith('preflight: BLOCKED')
    assert not (state_dir(tmp_path) / 'preflight').exists()
    blocked = (False, ['preflight: BLOCKED (fix the named blocker before asking for a code)'])
    assert planrunoffer.offered(PLAN, blocked, table={}, send=Wire(issuer), home=tmp_path) == blocked
    found, lines = planrunoffer.offered(PLAN, green, table={}, send=Wire(issuer), home=tmp_path)  # the control
    assert found
    offer(PLAN, {}, send=Wire(issuer), home=tmp_path)  # the record offers the plan


def test_sshhold_refuses_an_unoffered_plan_before_it_asks_for_the_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(HOME_ENV, str(tmp_path / 'home'))
    path = tmp_path / 'plan.json'
    path.write_text(json.dumps({'hosts': list(PLAN.hosts), 'grants': list(PLAN.grants)}), encoding='utf-8')
    asked: list[object] = []
    monkeypatch.setattr(sshhold, 'given_code', lambda code: asked.append(code) or '123456')
    assert sshhold.main(['open', '--hours', '1', '--plan', str(path), '--digest', PLAN.digest[:12]]) == 2
    assert asked == []


def _imports(source: str) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            found |= {node.module, *(f'{node.module}.{alias.name}' for alias in node.names)}
        elif isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
    return found


def test_the_consent_package_imports_no_client_of_the_forge_wave() -> None:
    """The ``ops.consent -> dev.forgebreakglass`` cycle stays removed: the wire lives in :mod:`.door`.

    PLANTED CONTROL: the former import line is caught by the same scan.
    """
    assert 'dev_lab.dev.forgebreakglass' in _imports('from dev_lab.dev.forgebreakglass import Send, ssh_send\n')
    package, former = Path(serve.__file__).parent, 'dev_lab.dev.forgebreakglass'
    offenders = {path.name for path in package.glob('*.py') if former in _imports(path.read_text(encoding='utf-8'))}
    assert offenders == set()


@pytest.mark.parametrize(
    ('said', 'names'),
    [
        ('Host key verification failed.', 'devhost enroll'),
        ('consent@forge: Permission denied (publickey).', "does not admit this machine's ssh key"),
        ('ssh: connect to host forge port 22: Connection timed out', 'unreachable over ssh'),
    ],
)
def test_a_255_is_ssh_named_with_its_last_line_never_an_old_issuer(
    issuer: Issuer, tmp_path: Path, said: str, names: str
) -> None:
    """Measured 2026-11-22: every non-zero ``hello`` read "the issuer's dev-lab is older than this client".

    Exit 255 is the transport's: the plan door and the bare handshake name ssh, its last line and the door.
    PLANTED CONTROL: a real version mismatch (an issuer answering 2 to ``hello``) keeps the upgrade message.
    """
    for shake in (
        lambda send: handshake({'endpoint': 'consent@forge'}, send=send),
        lambda send: offer_recorded(send, tmp_path),
    ):
        with pytest.raises(ConsentRefused, match='no code asked: ssh to the consent issuer consent@forge failed') as no:
            shake(lambda _table, _request: (255, f'banner line\n{said}\n'))
        refused = str(no.value)
        assert names in refused
        assert f'ssh said: {said}' in refused
        assert 'older than this client' not in refused
        assert 'version handshake' not in refused
    with pytest.raises(ConsentRefused, match='no version handshake') as old:
        handshake({'endpoint': 'consent@forge'}, send=Wire(issuer, old=True))
    assert ISSUER_UPGRADE in str(old.value)


def offer_recorded(send: Send, home: Path) -> None:
    """A plan's offer over *send*, its green preflight recorded a moment ago."""
    record_preflight(PLAN, home=home, now=NOW)
    offer(PLAN, {'endpoint': 'consent@forge'}, send=send, home=home, now=NOW + 1)
