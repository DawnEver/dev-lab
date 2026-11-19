"""``verify_held``: a consumer spends a HELD consent (the user's ``grant`` wrote it) on one ``desktop.*`` act."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from _ops_fixtures import NOW, RFC_KEY, code
from lab_commons.home import HOME_ENV

from dev_lab.ops.consent.actions import ACTIONS
from dev_lab.ops.consent.client import verify_held
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.consent.issuer import Issuer, keygen

PLAN = hashlib.sha256(json.dumps({'exe': 'Simba.exe', 'case': 'buck'}, sort_keys=True).encode()).hexdigest()


@pytest.fixture
def held(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Issuer, str]:
    """An issuer, and one ``desktop.open`` credential for PLAN held in the consent state (as ``grant`` leaves it)."""
    monkeypatch.setenv(HOME_ENV, str(tmp_path / 'home'))
    (tmp_path / 'totp').write_text(RFC_KEY + '\n', encoding='utf-8')
    keygen(tmp_path / 'consent.key')
    issuer = Issuer(tmp_path / 'totp', tmp_path / 'consent.key', tmp_path / 'state', 'test', lambda: NOW)
    credential = issuer.issue({'action': 'desktop.open', 'subject': PLAN, 'params': {}}, code(0))
    store = tmp_path / 'home' / 'state' / 'consent'
    store.mkdir(parents=True)
    (store / f'{credential["id"]}.json').write_text(json.dumps(credential), encoding='utf-8')
    return issuer, credential['id']


def test_the_gui_acts_are_registry_rows_single_and_not_boundary() -> None:
    for name in ('desktop.open', 'desktop.focus'):
        assert ACTIONS[name].scope == ACTIONS['shell.lifetime'].scope
        assert ACTIONS[name].boundary is False


def test_a_held_credential_for_the_plan_is_spent_once(held: tuple[Issuer, str]) -> None:
    """The planted control of every refusal below."""
    issuer, grant_id = held
    found = verify_held(grant_id, action='desktop.open', subject=PLAN, key=issuer.public(),
                        register=issuer.register, now=NOW)  # fmt: skip
    assert (found.action, found.subject) == ('desktop.open', PLAN)
    with pytest.raises(ConsentRefused):
        verify_held(grant_id, action='desktop.open', subject=PLAN, key=issuer.public(),
                    register=issuer.register, now=NOW)  # fmt: skip


def test_another_plan_is_refused_without_spending(held: tuple[Issuer, str]) -> None:
    issuer, grant_id = held
    with pytest.raises(ConsentRefused, match='another request'):
        verify_held(grant_id, action='desktop.open', subject='0' * 64, key=issuer.public(),
                    register=issuer.register, now=NOW)  # fmt: skip
    verify_held(grant_id, action='desktop.open', subject=PLAN, key=issuer.public(),
                register=issuer.register, now=NOW)  # fmt: skip


def test_an_open_credential_is_not_a_focus(held: tuple[Issuer, str]) -> None:
    issuer, grant_id = held
    with pytest.raises(ConsentRefused, match=r'not desktop.focus'):
        verify_held(grant_id, action='desktop.focus', subject=PLAN, key=issuer.public(),
                    register=issuer.register, now=NOW)  # fmt: skip


def test_an_absent_credential_names_the_grant_door(held: tuple[Issuer, str]) -> None:
    issuer, _ = held
    with pytest.raises(ConsentRefused, match=r'dev_lab\.ops\.consent grant'):
        verify_held('nope', action='desktop.open', subject=PLAN, key=issuer.public(),
                    register=issuer.register, now=NOW)  # fmt: skip
