"""Native harness identity is shared by PR, task, wall, milestone and consent mechanisms."""

from __future__ import annotations

import json
from importlib import import_module
from types import ModuleType
from typing import TYPE_CHECKING

import pytest
from _forge_state import FORGE

from dev_lab.dev import sessionprs, taskgate, walls

if TYPE_CHECKING:
    from pathlib import Path

_CODEX = 'CODEX_THREAD_ID'
_CLAUDE = 'CLAUDE_CODE_SESSION_ID'
_ID = 'native-session-7'


def _native() -> ModuleType:
    """Import inside the executed control: a missing contract is a call failure, not failed collection."""
    return import_module('dev_lab.dev.native_session')


@pytest.mark.parametrize('field', [_CLAUDE, _CODEX])
def test_each_native_harness_keeps_its_actual_session_without_an_environment_alias(field: str) -> None:
    env = {field: _ID}
    assert _native().session_of(env) == _ID
    assert env == {field: _ID}, 'reading identity must not manufacture another harness environment'


def test_an_ordinary_process_has_no_native_agent_identity() -> None:
    assert _native().session_of({}) == ''
    assert _native().session_of({'LAB_SESSION': 'a-worktree-not-a-native-session'}) == ''


@pytest.mark.parametrize('value', ['', ' ', '../escape', 'x' * 129, 17, None])
def test_a_declared_but_invalid_native_identity_is_refused_not_treated_as_a_human(value: object) -> None:
    with pytest.raises(ValueError, match='native session') as refused:
        _native().session_of({_CODEX: value})
    assert 'Door:' in str(refused.value)


@pytest.mark.parametrize('claude', [_ID, 'another-native-session'])
def test_two_declared_native_harnesses_are_not_resolved_by_order_or_equal_labels(claude: str) -> None:
    with pytest.raises(ValueError, match='native session') as refused:
        _native().session_of({_CODEX: _ID, _CLAUDE: claude})
    assert 'Door:' in str(refused.value)


def test_auxiliary_codex_session_metadata_cannot_replace_its_missing_thread_identity() -> None:
    with pytest.raises(ValueError, match='native session') as refused:
        _native().session_of({'CODEX_SESSION_ID': 'auxiliary-not-the-thread'})
    assert _CODEX in str(refused.value)
    assert 'Door:' in str(refused.value)


def test_identity_refusals_do_not_echo_an_invalid_private_value() -> None:
    private_value = 'planted/private/value'
    with pytest.raises(ValueError, match='native session') as refused:
        _native().session_of({_CODEX: private_value})
    assert private_value not in str(refused.value)


def test_the_pr_door_records_the_codex_thread_in_its_own_existing_journal() -> None:
    opened = sessionprs.record_opened(FORGE, 7, branch='pr/native', sha='a' * 40, env={_CODEX: _ID})
    assert opened is not None, 'a successful native Codex PR must not disappear from session tracking'
    assert [row.number for row in sessionprs.rows(_ID)] == [7]


def test_the_same_pr_door_does_not_invent_an_agent_for_an_ordinary_process() -> None:
    assert sessionprs.record_opened(FORGE, 7, env={}) is None


def test_the_required_task_gate_applies_to_codex_too(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text('[tool.dev_lab.task]\nrequired = true\n', encoding='utf-8')
    refusal = taskgate.refusal(tmp_path, env={_CODEX: _ID}, read=lambda *_: (0, '(none)'))
    assert refusal is not None
    assert taskgate.RULE in refusal
    assert '/rem:task open' in refusal


def test_a_real_bound_task_still_admits_the_native_codex_session(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text('[tool.dev_lab.task]\nrequired = true\n', encoding='utf-8')
    assert taskgate.refusal(tmp_path, env={_CODEX: _ID}, read=lambda *_: (0, 'native-task')) is None


def test_wall_records_carry_the_codex_thread_not_an_empty_claude_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_CODEX, _ID)
    path = walls.record(tmp_path, rule='PLANTED-NATIVE-WALL', remedy=True, command='a planted command')
    [line] = path.read_text(encoding='utf-8').splitlines()
    recorded = json.loads(line)
    assert recorded['session'] == _ID
    assert 'a planted command' not in line
    assert recorded['remedy_present'] is True
