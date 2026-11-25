"""A subagent's refusal names its REAL cause: publishing is one row, a main-only door another, a read is neither.

MEASURED 2026-11-22: ``hpcaccount deploy-fleet --account A --dry-run`` -- which starts nothing and opens no
connection -- was refused inside a subagent by SUBAGENT-NO-PUSH, whose remedy ("commit on your lane and hand the SHA
back") answers a push. The row was derived from EVERY main-only door of the policy table, publishing or not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.dev import agenthooks
from dev_lab.dev._deny_subagent_row import PUBLISHING_MODULES
from dev_lab.dev.agentpolicy import MAIN, POLICY
from dev_lab.dev.hook_adoption import HookAdoption, render

_PY = '.venv/Scripts/python.exe'
_PUSH, _DOOR = 'SUBAGENT-NO-PUSH', 'MAIN-ONLY-DOOR'


@pytest.fixture(scope='module')
def rules(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The rows that need no repo artifact, rendered as a repo ships them: both subagent rows are among them."""
    path = tmp_path_factory.mktemp('rules') / 'deny-rules.json'
    path.write_text(render(HookAdoption(app_name='subagent rows (suite)')), encoding='utf-8')
    return path


def _row(reason: str | None) -> str | None:
    return None if reason is None else reason.split(':', 1)[0]


@pytest.mark.parametrize(
    'command',
    [
        f'{_PY} -m dev_lab.dev.sshhold status',
        f'{_PY} -m dev_lab.dev.hpcaccount deploy-fleet --account A --dry-run',
        f'{_PY} -m dev_lab.dev.hpcaccount drift-fleet',
        f'{_PY} -m dev_lab.dev.hpcaccount look --account A inventory work',
    ],
)
def test_a_read_only_verb_is_a_subagents_own(rules: Path, command: str) -> None:
    assert agenthooks.decide(command, rules, agent_id='a1') is None


@pytest.mark.parametrize(
    'command',
    [
        # THE PLANTED CONTROLS of the dry run: the same door without the flag, the flag in a LATER segment, and a
        # dry run that still reads every account over ssh.
        f'{_PY} -m dev_lab.dev.hpcaccount deploy-fleet --account A',
        f'{_PY} -m dev_lab.dev.hpcaccount deploy-fleet --account A; echo --dry-run',
        f'{_PY} -m dev_lab.dev.hpcaccount forget --repo u --row k --fleet --dry-run',
        # MEASURED 2026-11-25: a subagent's census was answered with the push remedy by a consumer's stale render.
        f'{_PY} -m dev_lab.dev.hpcaccount retention --account A --census',
        f'{_PY} -m dev_lab.dev.hpcaccount archive --account A work/data --apply',
        f'{_PY} -m dev_lab.dev.hpcaccount archive-clean --account A work/data',
        f'{_PY} -m dev_lab.dev.sshhold open alice@hpclogin01.example.org --hours 2 --code 123456',
        f'{_PY} -m dev_lab.dev.opsserver status',
    ],
)
def test_a_main_only_door_is_refused_by_its_own_row_and_names_its_own_door(rules: Path, command: str) -> None:
    reason = agenthooks.decide(command, rules, agent_id='a1')
    assert _row(reason) == _DOOR, reason
    assert reason is not None
    assert 'Hand the exact command back to the main session' in reason
    assert 'push' not in reason, 'a door that publishes nothing was answered with the push remedy'
    assert 'Commit on your lane' not in reason
    assert agenthooks.decide(command, rules) is None, 'the main session lost its own door'


def test_a_publishing_door_keeps_the_push_row(rules: Path) -> None:
    for command in ('git push origin HEAD', f'{_PY} -m dev_lab.dev.forge pr ready 12', 'gh workflow disable ci.yml'):
        assert _row(agenthooks.decide(command, rules, agent_id='a1')) == _PUSH, command


def test_every_main_door_of_the_policy_table_is_refused_a_subagent_by_the_row_of_its_subject(rules: Path) -> None:
    """DERIVED, both ways: a publishing module's door is the push row's, every other main door the door row's."""
    doors = [door.argv for door in POLICY if door.actor == MAIN and door.argv[:1] in (('python',), ('gh',))]
    assert len(doors) >= 20, f'only {len(doors)} main doors were read; an unread table proves nothing'
    seen = set()
    for argv in doors:
        command = ' '.join((_PY, *argv[1:]) if argv[0] == 'python' else argv)
        publishes = argv[0] == 'gh' or argv[2] in PUBLISHING_MODULES
        row = _row(agenthooks.decide(command, rules, agent_id='a1'))
        assert row == (_PUSH if publishes else _DOOR), command
        seen.add(row)
    assert seen == {_PUSH, _DOOR}
