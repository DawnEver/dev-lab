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
from _task_ledger import on_branch, open_task, plant_ledger
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from lab_commons.hpc.grants import ACCESS_RULE, AccessRefused, load_grants

from dev_lab.dev import taskledger
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
        'params_hash': params_hash({}), 'scope': ACTIONS[hpcsession.ACTION].scope, 'cap': None, 'plan': None,
        'issued': expires - 3600, 'expires': expires, 'issuer': 'test',
    }  # fmt: skip
    target = state_dir(home)
    target.mkdir(parents=True, exist_ok=True)
    (target / f'{fields["id"]}.json').write_text(json.dumps(sign(fields, key)), encoding='utf-8')


def _held(home: Path, session: str = _SESSION) -> frozenset[str]:
    return hpcsession.held(session=session, home=home, now=_NOW, table=_TABLE)


_TASK = 'integrator'


def _task_checkout(root: Path, slug: str = _TASK, *, authority: str = 'a1b2c3', status: str = 'open') -> str:
    """Task *slug* in this machine's one ledger, as the user's task-open writes it; its task id."""
    del root
    return open_task(plant_ledger(), slug, authority=authority, status=status)


def _task_credential(home: Path, task: str, *, expires: float = _NOW + 3600) -> None:
    fields = {
        'id': str(uuid.uuid4()), 'action': hpcsession.TASK_ACTION, 'subject': task, 'params': {},
        'params_hash': params_hash({}), 'scope': ACTIONS[hpcsession.TASK_ACTION].scope, 'cap': None, 'plan': None,
        'issued': expires - 3600, 'expires': expires, 'issuer': 'test',
    }  # fmt: skip
    target = state_dir(home)
    target.mkdir(parents=True, exist_ok=True)
    (target / f'{fields["id"]}.json').write_text(json.dumps(sign(fields, _KEY)), encoding='utf-8')


def _on_task(root: Path, slug: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The session works in a checkout on a head of task *slug*: the one thing that says which task it works on."""
    on_branch(root, f'pr/{slug}/x')
    monkeypatch.chdir(root)


def _holder(home: Path, session: str = _SESSION) -> str | None:
    return hpcsession.holder(session=session, home=home, now=_NOW, table=_TABLE)


def test_a_session_on_a_granted_tasks_branch_holds_the_role(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    task = _task_checkout(tmp_path / 'repo')
    _task_credential(tmp_path, task)
    _on_task(tmp_path / 'repo', 'elsewhere', monkeypatch)
    assert _held(tmp_path) == frozenset(), 'planted control: a granted task gives a session on no open task nothing'
    _on_task(tmp_path / 'repo', _TASK, monkeypatch)
    assert _held(tmp_path) == {hpcsession.INTEGRATOR}
    assert _holder(tmp_path) == f'task {task}', 'status names the identity that holds it'


def test_another_tasks_or_an_expired_task_credential_grants_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _task_checkout(tmp_path / 'repo')
    other = _task_checkout(tmp_path / 'repo', 'other-task')
    _on_task(tmp_path / 'repo', _TASK, monkeypatch)
    _task_credential(tmp_path, other)
    _task_credential(tmp_path, task, expires=_NOW - 3600)
    _task_credential(tmp_path, f'{_TASK}@an-older-authority')  # the same slug, closed and reopened since
    assert _held(tmp_path) == frozenset()
    _task_credential(tmp_path, task)  # planted control: the valid one beside them
    assert _held(tmp_path) == {hpcsession.INTEGRATOR}


def test_a_session_credential_still_names_the_session(tmp_path: Path) -> None:
    _credential(tmp_path)
    assert _holder(tmp_path) == f'session {_SESSION}'


def test_the_task_action_is_bounded_to_a_week_and_requested_by_task_id(tmp_path: Path) -> None:
    row = ACTIONS[hpcsession.TASK_ACTION]
    assert ACTIONS[hpcsession.ACTION].max_ttl < row.max_ttl <= 7 * 24 * 3600
    task = _task_checkout(tmp_path / 'repo')
    assert taskledger.task_in(taskledger.ledger(), _TASK) == task
    asked = hpcsession.request('', task=task)
    assert (asked['action'], asked['subject'], asked['ttl']) == (hpcsession.TASK_ACTION, task, row.default_ttl)
    _task_checkout(tmp_path / 'repo', 'shut', status='closed')
    with pytest.raises(ValueError, match='not open'):
        taskledger.task_in(taskledger.ledger(), 'shut')


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
    with pytest.raises(ValueError, match='one session or task'):
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
    monkeypatch.delenv('CLAUDE_CODE_SESSION_ID', raising=False)
    assert hpcsession.roles() == frozenset(), 'no session id in the environment: no role, nothing read'
    assert time.time() > 0


def test_the_task_is_read_from_the_working_directorys_branch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    task = _task_checkout(tmp_path / 'repo')
    on_branch(tmp_path / 'repo', 'main')
    assert taskledger.task_of(tmp_path / 'repo') is None, 'planted control: no task head yet'
    _on_task(tmp_path / 'repo', _TASK, monkeypatch)
    assert taskledger.task_of(Path.cwd()) == task


@pytest.mark.parametrize('field', ['CLAUDE_CODE_SESSION_ID', 'CODEX_THREAD_ID', 'ANTIGRAVITY_CONVERSATION_ID'])
def test_a_native_session_needs_its_own_valid_signed_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    monkeypatch.setenv(field, _SESSION)
    assert hpcsession.held(home=tmp_path, now=_NOW, table=_TABLE) == frozenset()
    _credential(tmp_path)
    assert hpcsession.held(home=tmp_path, now=_NOW, table=_TABLE) == {'integrator'}
    assert hpcsession.holder(home=tmp_path, now=_NOW, table=_TABLE) == f'session {_SESSION}'


def test_another_sessions_signed_credential_does_not_authorize_the_codex_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv('CODEX_THREAD_ID', _SESSION)
    _credential(tmp_path, subject='another-session')
    assert hpcsession.held(home=tmp_path, now=_NOW, table=_TABLE) == frozenset()


def test_the_role_request_uses_the_actual_codex_thread_without_creating_a_credential(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv('CODEX_THREAD_ID', _SESSION)
    assert hpcsession.main(['request', '--hours', '24']) == 0
    request = json.loads(capsys.readouterr().out)
    assert request == {'action': hpcsession.ACTION, 'subject': _SESSION, 'ttl': 24 * 3600}
