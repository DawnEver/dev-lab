"""FAMILY-GRANTS-ARE-RENDERED, prevention half: no agent writes the user's Claude settings; a repo file is fine."""

from __future__ import annotations

import re

import pytest

from dev_lab.dev.agent_guard import wire_settings
from dev_lab.dev.autodoors import claude_rows
from dev_lab.dev.hooks import DENY_RULES, denies
from dev_lab.dev.usersettings import PERMISSION_DENY, USER_SETTINGS_PATH, USER_SETTINGS_WRITE

_ID = USER_SETTINGS_WRITE['id']


@pytest.mark.parametrize('command', USER_SETTINGS_WRITE['refuses'])
def test_a_shell_write_to_the_user_settings_is_refused(command: str) -> None:
    """PLANTED: each write shape onto a user-level settings file fires this row by name."""
    assert denies(DENY_RULES, command, {}) == _ID


@pytest.mark.parametrize('command', USER_SETTINGS_WRITE['permits'])
def test_reading_them_or_writing_a_repo_settings_file_is_allowed(command: str) -> None:
    """PLANTED: a read, and a write to this repo's own ``.claude/settings*.json``, pass."""
    assert denies(DENY_RULES, command, {}) != _ID


@pytest.mark.parametrize(
    'path',
    ['~/.claude/settings.json', 'C:/Users/me/.claude-evans/settings.json', '/home/me/.claude/settings.local.json'],
)
def test_the_path_shape_reaches_every_user_spelling_and_not_a_repo_file(path: str) -> None:
    """The one path regex both renderings derive from."""
    assert re.search(USER_SETTINGS_PATH, path)
    assert not re.fullmatch(USER_SETTINGS_PATH, '.claude/settings.json')


def test_the_rendered_settings_deny_every_user_path_and_keep_foreign_deny_rows() -> None:
    """``wire_settings`` adds each deny row once, keeps another author's, and is idempotent."""
    after = wire_settings({'permissions': {'deny': ['Read(./secrets/**)']}})
    deny = after['permissions']['deny']
    assert deny == ['Read(./secrets/**)', *PERMISSION_DENY]
    assert wire_settings(after) == after
    assert {'Edit(~/.claude/settings.json)', 'Write(//**/claude_settings.json)'} <= set(PERMISSION_DENY)


@pytest.mark.parametrize(
    'row',
    [
        'Bash(node .claude/hooks/py.js -m dev_lab.dev.hook_install *)',
        'Bash(node .claude/hooks/py.js -m dev_lab.dev.agent_guard *)',
        'Bash(.venv/*/python* -m dev_lab.dev.forge queue *)',
        'Bash(node .claude/hooks/py.js -m dev_lab.dev.forge status list *)',
        'Bash(node .claude/hooks/py.js -m dev_lab.dev.forge review dispose *)',
        'Bash(node .claude/hooks/py.js -m dev_lab.dev.forge cancel-stuck *)',
        'Bash(node .claude/hooks/py.js -m dev_lab.dev.forge pr close-landed *)',
        'Bash(node .claude/hooks/py.js -m dev_lab.dev.branchprune delete *)',
        'Bash(node .claude/hooks/py.js -m dev_lab.dev.worktrees *)',
    ],
)
def test_the_rendered_allow_carries_each_family_grant(row: str) -> None:
    """Each grant that used to live in the user's global settings is a rendered repo row, in its real spelling."""
    assert row in claude_rows()


def test_no_rendered_row_spells_a_retired_module() -> None:
    """RETIRED-NAMES-REGISTERED: the pre-move ``lab_commons.dev`` spelling is never granted."""
    assert not [row for row in claude_rows() if 'lab_commons.dev' in row]
