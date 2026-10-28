"""The rules registry, GRANTS part -- pure DATA, the same row shape as ``_rule_rows.py``.

The rows about where an agent's unattended permissions are declared, and where they may never be written.
"""

from __future__ import annotations

ROWS: tuple[tuple[str, str, tuple[str | tuple[str, str], ...]], ...] = (
    (
        'FAMILY-GRANTS-ARE-RENDERED',
        (
            'A family permission grant is declared once in dev-lab -- a door row in `dev_lab.dev.autodoors`, its '
            'intent in `dev_lab.dev.automode.INTENTS` -- and rendered into each repo (`permissions.allow`, the '
            'machine-local `.claude/automode.json`), never written into the user`s global Claude settings: the '
            'agent guard '
            'renders `permissions.deny` for Edit/Write of `~/.claude*/settings.json` and `claude_settings.json` '
            'and refuses a shell write to them (user ruling 2026-10-28).'
        ),
        ('tests/test_dev_usersettings.py', 'tests/test_dev_autodoors.py'),
    ),
)
