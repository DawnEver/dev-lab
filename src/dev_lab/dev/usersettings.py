"""FAMILY-GRANTS-ARE-RENDERED: an agent never writes the USER's Claude Code settings. ONE deny list, two renderings.

User ruling 2026-10-28: family-specific grants must not live in the user's global Claude settings. They
are declared once in dev-lab -- the door rows in :mod:`dev_lab.dev.autodoors`, the intent prose in
:mod:`dev_lab.dev.automode` -- and rendered into each repo (``permissions.allow``, ``.claude/automode.json``).
A user-level settings file is personal, often synced (a live session on another box races the write), and a
grant written there is a second, unreviewed source no repo can see. So nothing an agent runs may write one:

* :data:`PERMISSION_DENY` -- ``Edit``/``Write`` rows :func:`dev_lab.dev.agent_guard.wire_settings` merges into
  every repo's ``permissions.deny`` (a deny applies in every permission mode);
* :data:`USER_SETTINGS_WRITE` -- the shell half. A shell line's write target is not readable from its text
  (``cd`` then a relative path, ``dd of=``, ``cp -t``, an interpreter's ``open()``), so the row FAILS CLOSED:
  any command naming a user-level ``.claude*`` directory or settings file is refused unless it is ONE plain
  read verb (``cat``, ``jq``, ``grep``, ``diff``, ...) with no redirection, chaining or substitution.
  Copying one out is refused too; read it instead.

A user-level path is an ANCHORED one -- ``~``, an environment variable, a drive or ``/`` -- ending in
``.claude`` or ``.claude-<profile>`` (the directory, or its ``settings[.local].json``), plus any
``claude_settings.json`` (the name a synced config folder gives the symlink target) and
``$CLAUDE_CONFIG_DIR``. A repo-relative ``.claude/settings.json`` is not one, nor is
``$CLAUDE_PROJECT_DIR/.claude/...``; an ABSOLUTE path to a repo's own settings is refused too (fail closed --
spell it repo-relative).
"""

from __future__ import annotations

from typing import Final

__all__ = ['PERMISSION_DENY', 'REMEDY', 'USER_SETTINGS_PATH', 'USER_SETTINGS_WRITE']

#: What to do instead -- the one sentence both renderings carry.
REMEDY: Final = (
    'Declare the grant in dev-lab (dev_lab.dev.autodoors, automode.INTENTS) by PR, then render it: '
    'node .claude/hooks/py.js -m dev_lab.dev.agent_guard --install'
)

#: An anchored root: ``~``, a variable (never ``$CLAUDE_PROJECT_DIR``, the repo), a drive, or ``/``.
_ROOT: Final = r'(?:~|\$(?!\{?CLAUDE_PROJECT_DIR)\{?\w+\}?|%\w+%|\$env:\w+|[A-Za-z]:|/)'

#: A user-level Claude directory or settings file, in the subset JavaScript and Python regexes spell alike.
USER_SETTINGS_PATH: Final = (
    rf'(?:(?<![\w.]){_ROOT}[^\s"\'<>|;&]*?[/\\]\.claude(?:-[\w.-]+)?(?:[/\\]settings(?:\.local)?\.json)?'
    r'(?=[/\\]?(?:["\'\s;&|)]|$))'
    r'|[^\s"\'<>|;&]*claude_settings\.json|\$\{?CLAUDE_CONFIG_DIR\b)'
)

#: The one opening: a single plain read verb, no redirection, chaining, pipe or substitution anywhere.
_READ_ONLY: Final = (
    r'^\s*(?:cat|head|tail|less|more|grep|rg|jq|diff|ls|dir|stat|readlink|realpath|wc|type|Get-Content'
    r'|Get-Item|Test-Path|sha256sum|md5sum|file)\b(?:(?!\$\()[^>;&|\n`])*$'
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
    'pattern': USER_SETTINGS_PATH,
    'matches': 'argument',
    'allow': _READ_ONLY,
    'hazard': 'user-level Claude settings are personal and synced; a grant there is a source no repo sees.',
    'remedy': REMEDY,
    'needs': None,
    'refuses': (
        'echo x > ~/.claude/settings.json',
        'jq . a.json | tee ~/.claude-work/settings.json',
        'cp new.json "$HOME/.claude/settings.json"',
        "sed -i 's/a/b/' C:/Users/me/Sync/cc-config/claude_settings.json",
        r'Get-Content a | Set-Content -Path C:\Users\me\.claude\settings.json',
        'echo x > /root/.claude/settings.json',
        'echo x > /mnt/c/Users/me/.claude/settings.json',
        'cp a.json $USERPROFILE/.claude/settings.json',
        'cd ~/.claude && echo x > settings.json',
        'dd if=a.json of=~/.claude/settings.json',
        'cp -t ~/.claude a.json',
        'echo x > $CLAUDE_CONFIG_DIR/settings.json',
        """python -c "open('/home/me/.claude/settings.json', 'w')\"""",
        'cat ~/.claude/settings.json > /tmp/x; echo y > ~/.claude/settings.json',
        'cp ~/.claude/settings.json backup.json',
    ),
    'permits': (
        'cat ~/.claude/settings.json',
        'jq .permissions ~/.claude-work/settings.json',
        'grep tee ~/.claude/settings.json',
        'echo x > .claude/settings.json',
        'cp a.json .claude/settings.local.json',
        'cp a.json .claude/worktrees/lane/.claude/settings.json',
        'cat "$CLAUDE_PROJECT_DIR/.claude/settings.json"',
        'ls ~/.claude/skills',
    ),
}
