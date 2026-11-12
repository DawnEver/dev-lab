"""The integrator is a SESSION role: a consent credential for this session, verified offline, adds verification reach.

Planted controls, each beside its refusal: a research-host session without the credential is refused a verification
account and the same session holding one is allowed; an expired credential, another session's, or one signed by
another key grants nothing; a host whose reach is empty is refused even with a valid credential.
"""

from __future__ import annotations

import json
import sys
import time
import types
import uuid
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from lab_commons.hpc.grants import ACCESS_RULE, AccessRefused, load_grants

from dev_lab.dev.consentguard import state_dir
from dev_lab.dev.hpcaccount import session as hpcsession
from dev_lab.ops.consent.actions import ACTIONS
from dev_lab.ops.consent.credential import params_hash, public_text, sign

_KEY = Ed25519PrivateKey.generate()
_TABLE = {'public_key': public_text(_KEY.public_key())}
_NOW = 1_800_000_000.0
_SESSION = 'session-a'
_VERIFIER = 'dev_lab_test_hpcsession_verifier'


def _credential(
    home: Path, *, subject: str = _SESSION, expires: float = _NOW + 3600, key: Ed25519PrivateKey = _KEY
) -> None:
    fields = {
        'id': str(uuid.uuid4()), 'action': hpcsession.ACTION, 'subject': subject, 'params': {},
        'params_hash': params_hash({}), 'scope': ACTIONS[hpcsession.ACTION].scope, 'cap': None,
        'issued': expires - 3600, 'expires': expires, 'issuer': 'test',
    }  # fmt: skip
    target = state_dir(home)
    target.mkdir(parents=True, exist_ok=True)
    (target / f'{fields["id"]}.json').write_text(json.dumps(sign(fields, key)), encoding='utf-8')


def _held(home: Path, session: str = _SESSION) -> frozenset[str]:
    return hpcsession.held(session=session, home=home, now=_NOW, table=_TABLE)


def test_the_role_is_held_only_by_a_valid_credential_for_this_session(tmp_path: Path) -> None:
    assert _held(tmp_path) == frozenset(), 'no credential: no role'
    _credential(tmp_path)
    assert _held(tmp_path) == {hpcsession.INTEGRATOR}
    assert _held(tmp_path, 'session-b') == frozenset(), "another session's credential grants this one nothing"
    assert _held(tmp_path, '') == frozenset(), 'no session id: no role'


def test_an_expired_or_foreign_credential_grants_nothing(tmp_path: Path) -> None:
    _credential(tmp_path, expires=_NOW - 3600)
    _credential(tmp_path, key=Ed25519PrivateKey.generate())
    _credential(tmp_path, subject='session-b')
    assert _held(tmp_path) == frozenset()
    _credential(tmp_path)  # planted control: a valid one beside them
    assert _held(tmp_path) == {hpcsession.INTEGRATOR}


def test_the_action_is_registered_with_a_bounded_lifetime() -> None:
    row = ACTIONS[hpcsession.ACTION]
    assert row.max_ttl <= 24 * 3600, 'a session role is never a standing grant'
    assert hpcsession.request(_SESSION)['subject'] == _SESSION
    with pytest.raises(ValueError, match='one session'):
        hpcsession.request('')


def _declared(reach: list[str]) -> dict[str, Any]:
    return {
        'reach': reach,
        'session_reach': {hpcsession.INTEGRATOR: ['verification']},
        'session_verifier': f'{_VERIFIER}:roles',
        'clusters': {'c': {'hosts': ['h'], 'slurm_accounts': {'free': {'billed': False}}}},
        'grant': [
            {'user': 'res', 'cluster': 'c', 'slurm_account': 'free', 'role': 'research'},
            {'user': 'ver', 'cluster': 'c', 'slurm_account': 'free', 'role': 'verification'},
        ],
    }


@pytest.fixture
def verifier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The declared verifier: :func:`hpcsession.held` over *tmp_path*'s consent state, for :data:`_SESSION`."""
    monkeypatch.setitem(sys.modules, _VERIFIER, types.SimpleNamespace(roles=lambda: _held(tmp_path)))
    return tmp_path


def test_a_research_host_session_reaches_verification_only_with_the_credential(verifier: Path) -> None:
    with pytest.raises(AccessRefused, match=rf'{ACCESS_RULE}.*integrator session role'):
        load_grants(_declared(['research'])).grant('ver')
    _credential(verifier)
    assert load_grants(_declared(['research'])).grant('ver').role == 'verification'


def test_a_host_reaching_nothing_is_refused_even_with_the_credential(verifier: Path) -> None:
    _credential(verifier)
    with pytest.raises(AccessRefused, match=ACCESS_RULE):
        load_grants(_declared([]))


def test_the_production_verifier_reads_this_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(hpcsession.SESSION_ENV, raising=False)
    assert hpcsession.roles() == frozenset(), 'no session id in the environment: no role, nothing read'
    assert time.time() > 0
