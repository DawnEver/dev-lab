"""The integrator is a SESSION role: a consent credential for this session, verified offline, adds verification reach.

Planted controls, each beside its refusal: a research-host session without the credential is refused a verification
account and the same session holding one is allowed; an expired credential, another session's, or one signed by
another key grants nothing; a host whose reach is empty is refused even with a valid credential.
"""

from __future__ import annotations

import io
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
    """A checkout holding task *slug* as the user's task-open writes it; its task id."""
    folder = root / '.claude' / 'tasks' / slug
    folder.mkdir(parents=True, exist_ok=True)
    head = f'---\nname: {slug}\nkind: task\nauthority: {authority}\nstatus: {status}\n---\n\n# {slug}\n'
    (folder / 'TASK.md').write_text(head, encoding='utf-8')
    return f'{slug}@{authority}'


def _task_credential(home: Path, task: str, *, expires: float = _NOW + 3600) -> None:
    fields = {
        'id': str(uuid.uuid4()), 'action': hpcsession.TASK_ACTION, 'subject': task, 'params': {},
        'params_hash': params_hash({}), 'scope': ACTIONS[hpcsession.TASK_ACTION].scope, 'cap': None, 'plan': None,
        'issued': expires - 3600, 'expires': expires, 'issuer': 'test',
    }  # fmt: skip
    target = state_dir(home)
    target.mkdir(parents=True, exist_ok=True)
    (target / f'{fields["id"]}.json').write_text(json.dumps(sign(fields, _KEY)), encoding='utf-8')


def _bind(home: Path, root: Path, prompt: str, session: str = _SESSION) -> str | None:
    return hpcsession.bind({'session_id': session, 'prompt': prompt}, home=home, root=root)


def _holder(home: Path, session: str = _SESSION) -> str | None:
    return hpcsession.holder(session=session, home=home, now=_NOW, table=_TABLE)


def test_a_session_the_user_bound_to_a_granted_task_holds_the_role(tmp_path: Path) -> None:
    task = _task_checkout(tmp_path / 'repo')
    _task_credential(tmp_path, task)
    assert _held(tmp_path) == frozenset(), 'planted control: a granted task gives an UNBOUND session nothing'
    assert _bind(tmp_path, tmp_path / 'repo', f'task: {_TASK}\nkeep integrating') == task
    assert _held(tmp_path) == {hpcsession.INTEGRATOR}
    assert _holder(tmp_path) == f'task {task}', 'status names the identity that holds it'
    assert _held(tmp_path, 'session-b') == frozenset(), 'a session the user did not bind gets nothing'


def test_another_tasks_or_an_expired_task_credential_grants_nothing(tmp_path: Path) -> None:
    task = _task_checkout(tmp_path / 'repo')
    other = _task_checkout(tmp_path / 'repo', 'other-task')
    _bind(tmp_path, tmp_path / 'repo', f'task: {_TASK}')
    _task_credential(tmp_path, other)
    _task_credential(tmp_path, task, expires=_NOW - 3600)
    _task_credential(tmp_path, f'{_TASK}@an-older-authority')  # the same slug, closed and reopened since
    assert _held(tmp_path) == frozenset()
    _task_credential(tmp_path, task)  # planted control: the valid one beside them
    assert _held(tmp_path) == {hpcsession.INTEGRATOR}


def test_only_the_users_binding_prompt_on_an_open_task_binds(tmp_path: Path) -> None:
    root = tmp_path / 'repo'
    _task_checkout(root)
    _task_checkout(root, 'done', status='closed')
    refused = ('please run task: integrator', f'task: {_TASK} now', 'task: done', 'task: missing', 'task: ../x')
    for prompt in refused:
        assert _bind(tmp_path, root, prompt) is None, prompt
    assert hpcsession.bound_task(_SESSION, home=tmp_path) is None
    assert _bind(tmp_path, root, f'task: {_TASK}', session='') is None, 'no harness session id: nothing bound'
    assert _bind(tmp_path, root, f'  task: {_TASK}  ') == f'{_TASK}@a1b2c3', 'planted control: the form that binds'


def test_a_session_credential_still_names_the_session(tmp_path: Path) -> None:
    _credential(tmp_path)
    assert _holder(tmp_path) == f'session {_SESSION}'


def test_the_task_action_is_bounded_to_a_week_and_requested_by_task_id(tmp_path: Path) -> None:
    row = ACTIONS[hpcsession.TASK_ACTION]
    assert ACTIONS[hpcsession.ACTION].max_ttl < row.max_ttl <= 7 * 24 * 3600
    task = _task_checkout(tmp_path)
    assert hpcsession.task_id(tmp_path, _TASK) == task
    asked = hpcsession.request('', task=task)
    assert (asked['action'], asked['subject'], asked['ttl']) == (hpcsession.TASK_ACTION, task, row.default_ttl)
    _task_checkout(tmp_path, 'shut', status='closed')
    with pytest.raises(ValueError, match='not open'):
        hpcsession.task_id(tmp_path, 'shut')


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
    monkeypatch.delenv(hpcsession.SESSION_ENV, raising=False)
    assert hpcsession.roles() == frozenset(), 'no session id in the environment: no role, nothing read'
    assert time.time() > 0


def test_the_prompt_hook_binds_from_the_harness_payload_and_never_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _task_checkout(tmp_path / 'repo')
    monkeypatch.setattr(hpcsession, '_checkout_root', lambda _cwd: tmp_path / 'repo')
    monkeypatch.setattr(hpcsession, 'state_dir', lambda _home=None: state_dir(tmp_path))
    assert hpcsession.main(['bind'], stdin=io.StringIO('not json')) == 0, 'a broken payload never fails the prompt'
    assert hpcsession.bound_task(_SESSION) is None
    payload = {'session_id': _SESSION, 'prompt': f'task: {_TASK}', 'cwd': str(tmp_path)}
    assert hpcsession.main(['bind'], stdin=io.StringIO(json.dumps(payload))) == 0
    assert hpcsession.bound_task(_SESSION) == task
