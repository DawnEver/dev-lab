"""FAMILY-GRANTS-ARE-RENDERED: an agent never writes the USER's Claude Code settings. ONE deny list, two renderings.

User ruling 2026-10-28: family-specific grants must not live in the user's global Claude settings. They
are declared once in dev-lab -- the door rows in :mod:`dev_lab.dev.autodoors`, the intent prose in
:mod:`dev_lab.dev.automode` -- and rendered into each repo (``permissions.allow``, ``.claude/automode.json``).
A user-level settings file is personal, often synced (a live session on another box races the write), and a
grant written there is a second, unreviewed source no repo can see. So nothing an agent runs may write one:

* :data:`PERMISSION_DENY` -- ``Edit``/``Write`` rows :func:`dev_lab.dev.agent_guard.wire_settings` merges into
  every repo's ``permissions.deny`` (a deny applies in every permission mode);
* :data:`USER_SETTINGS_WRITE` -- the shell half, a deny-registry row refusing a redirection, ``tee``,
  ``Set-Content``/``Out-File``, ``cp``/``mv``/``ln`` or ``sed -i`` onto one. Reading is untouched.

The paths are SHAPES, never a machine's names: ``~/.claude/settings.json``, every ``~/.claude-<profile>/``
twin, and ``claude_settings.json`` -- the file name a synced config folder gives the symlink target.
"""

from __future__ import annotations

from typing import Final

__all__ = ['PERMISSION_DENY', 'REMEDY', 'USER_SETTINGS_PATH', 'USER_SETTINGS_WRITE']

#: What to do instead -- the one sentence both renderings carry.
REMEDY: Final = (
    'Declare the grant in dev-lab (dev_lab.dev.autodoors, automode.INTENTS) by PR, then render it: '
    'node .claude/hooks/py.js -m dev_lab.dev.agent_guard --install'
)

_HOME: Final = (
    r'(?:~|\$HOME|\$\{HOME\}|%USERPROFILE%|\$env:USERPROFILE'
    r'|[A-Za-z]:[/\\]+Users[/\\]+[^/\\\s"\']+|/[a-z]/Users/[^/\s"\']+|/(?:home|Users)/[^/\s"\']+)'
)

#: A user-level settings file, in the subset JavaScript and Python regexes spell alike.
USER_SETTINGS_PATH: Final = (
    rf'(?:{_HOME}[/\\]+\.claude(?:-[\w.-]+)?[/\\]+settings(?:\.local)?\.json'
    r'|[^\s"\'<>|;&]*claude_settings\.json)'
)

#: The ``permissions.deny`` rows: every file tool, every spelling of the paths above the client resolves.
PERMISSION_DENY: Final = tuple(
    f'{tool}({path})'
    for tool in ('Edit', 'Write')
    for path in (
        '~/.claude/settings.json',
        '~/.claude/settings.local.json',
        '~/.claude-*/settings.json',
        '~/.claude-*/settings.local.json',
        '//**/claude_settings.json',
    )
)

USER_SETTINGS_WRITE: Final[dict[str, object]] = {
    'id': 'FAMILY-GRANTS-ARE-RENDERED',
    'pattern': (
        r'(?:>>?|\btee\b(?:\s+-a)?|\bOut-File\b(?:\s+-FilePath)?|\b(?:Set|Add)-Content\b(?:\s+-Path)?'
        r'|\b(?:cp|mv|ln|Copy-Item|Move-Item)\b[^\n;&|]*\s|\bsed\s+-i\b[^\n;&|]*\s)'
        rf'\s*["\']?{USER_SETTINGS_PATH}'
    ),
    'matches': 'argument',
    'hazard': 'user-level Claude settings are personal and synced; a grant there is a source no repo sees.',
    'remedy': REMEDY,
    'needs': None,
    'refuses': (
        'echo x > ~/.claude/settings.json',
        'jq . a.json | tee ~/.claude-evans/settings.json',
        'cp new.json "$HOME/.claude/settings.json"',
        "sed -i 's/a/b/' C:/Users/me/OneDrive/Sync/cc-config/claude_settings.json",
        'Get-Content a | Set-Content -Path C:\\Users\\me\\.claude\\settings.json',
    ),
    'permits': (
        'cat ~/.claude/settings.json',
        'jq .permissions ~/.claude-evans/settings.json',
        'echo x > .claude/settings.json',
        'cp a.json .claude/settings.local.json',
    ),
}
