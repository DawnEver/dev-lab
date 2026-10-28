"""FAMILY-GRANTS-ARE-RENDERED: an agent never writes the USER's Claude Code settings. ONE deny list, two renderings.

User ruling 2026-10-28: family-specific grants must not live in the user's global Claude settings. They
are declared once in dev-lab -- the door rows in :mod:`dev_lab.dev.autodoors`, the intent prose in
:mod:`dev_lab.dev.automode` -- and rendered into each repo (``permissions.allow``, ``.claude/automode.json``).
A user-level settings file is personal, often synced (a live session on another box races the write), and a
grant written there is a second, unreviewed source no repo can see. So nothing an agent runs may write one:

* :data:`PERMISSION_DENY` -- ``Edit``/``Write`` rows :func:`dev_lab.dev.agent_guard.wire_settings` merges into
  every repo's ``permissions.deny`` (a deny applies in every permission mode);
* :data:`USER_SETTINGS_WRITE` -- the shell half, a TEXT SCREEN and not a file-system control. A shell line's
  write target is not readable from its text (``dd of=``, ``cp -t``, an interpreter's ``open()``), so the row
  refuses every command whose text CAN reach a user-level settings file, unless it is ONE plain read verb
  (``cat``, ``jq``, ``grep``, ``diff``, ...) with no redirection, chaining or substitution. Copying one out is
  refused too; read it instead.

What the text can reach a home by, each refused: an ANCHORED path -- ``~``, an environment variable, a drive
or ``/``, a quote allowed inside it -- ending in ``.claude`` or ``.claude-<profile>`` (the directory, or its
``settings[.local].json``); a hidden component under such a root carrying a glob or brace (``~/.cl*de``,
``~/.{claude,x}``); a command substitution opening a hidden path (``"$(echo ~)"/.claude``); any
``claude_settings.json`` (the name a synced config folder gives the symlink target); ``$CLAUDE_CONFIG_DIR``;
and a RELATIVE ``.claude*`` path on a line that changes directory (``cd``, ``pushd``, ``Set-Location``, ...)
or assigns ``HOME``/``USERPROFILE``/``CLAUDE_CONFIG_DIR``. A relative path on a line that does neither is the
repo's own and passes, as does ``$CLAUDE_PROJECT_DIR/.claude/...``; an ABSOLUTE path to a repo's own settings
is refused (spell it repo-relative). What a text screen cannot see -- a path computed inside an interpreter, an
escape the shell removes -- is out of its reach, and :data:`PERMISSION_DENY` is the half the client enforces.
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

#: A path-ish character: anything but whitespace, a redirection, a pipe or a command separator.
_PATHCH: Final = r'[^\s<>|;&]'

#: A hidden component that names no literal ``.claude``: a glob or brace in it (``.cl*de``, ``.{claude,x}``).
_GLOBBED: Final = r'\.[^\s"\x27<>|;&/\\]*[*?\[{]'

#: The tail that ends a ``.claude`` / ``.claude-<profile>`` name: the directory, or its settings file.
_DOTCLAUDE: Final = r'\.claude(?:-[\w.-]+)?(?:[/\\]settings(?:\.local)?\.json)?(?=[/\\]?(?:["\x27\s;&|)`]|$))'

#: A command substitution opening a hidden path: ``$(echo ~)/.x``, ```echo ~`/.x``.
_SUBSTITUTED: Final = r'(?:\$\([^)]*\)|`[^`]*`)["\x27]?[/\\]\.'

#: Every spelling that can only reach a home: anchored ``.claude*`` (a quote may split it), an anchored globbed
#: hidden component, a substitution opening a hidden path, any ``claude_settings.json``, ``$CLAUDE_CONFIG_DIR``.
_HOME_SPELLING: Final = (
    rf'(?<![\w.]){_ROOT}{_PATHCH}*?[/\\]["\x27]?(?:{_DOTCLAUDE}|{_GLOBBED})'
    rf'|{_SUBSTITUTED}|[^\s"\x27<>|;&]*claude_settings\.json|\$\{{?CLAUDE_CONFIG_DIR\b'
)

#: A user-level Claude directory or settings file, in the subset JavaScript and Python regexes spell alike:
#: a home spelling, or a RELATIVE ``.claude*`` path -- opened again by :data:`_REPO_RELATIVE` only when nothing
#: on the line can have moved the directory it resolves against.
USER_SETTINGS_PATH: Final = rf'(?:{_HOME_SPELLING}|(?<![\w./\\$}}%:-]){_DOTCLAUDE})'

#: The first opening: a single plain read verb, no redirection, chaining, pipe or substitution anywhere.
_READ_ONLY: Final = (
    r'^\s*(?:cat|head|tail|less|more|grep|rg|jq|diff|ls|dir|stat|readlink|realpath|wc|type|Get-Content'
    r'|Get-Item|Test-Path|sha256sum|md5sum|file)\b(?:(?!\$\()[^>;&|\n`])*$'
)

#: What can make a relative ``.claude`` path resolve under a home: a directory change or a home assignment.
_MOVES_HOME: Final = (
    r'(?:^|[\s;&|(])(?:cd|pushd|popd|chdir|Set-Location|sl|Push-Location)\b'
    r'|\b(?:HOME|USERPROFILE|CLAUDE_CONFIG_DIR)='
)

#: The second opening: no home spelling anywhere on the line and nothing on it moves a home, so every hit is
#: a repo-relative ``.claude*`` path.
_REPO_RELATIVE: Final = rf'^(?![\s\S]*(?:{_MOVES_HOME}))(?![\s\S]*(?:{_HOME_SPELLING}))'

_ALLOW: Final = f'(?:{_READ_ONLY})|(?:{_REPO_RELATIVE})'

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
    'allow': _ALLOW,
    'hazard': 'user-level Claude settings are personal and synced; a grant there is a source no repo sees.',
    'remedy': REMEDY,
    'needs': None,
    'refuses': (
        'echo x > ~/.claude/settings.json',
        'jq . a.json | tee ~/.claude-work/settings.json',
        'cp new.json "$HOME/.claude/settings.json"',
        "sed -i 's/a/b/' D:/Sync/cc-config/claude_settings.json",
        r'Get-Content a | Set-Content -Path D:\profiles\me\.claude\settings.json',
        'echo x > /root/.claude/settings.json',
        'echo x > /mnt/c/Users/me/.claude/settings.json',
        'cp a.json $USERPROFILE/.claude/settings.json',
        'cd ~/.claude && echo x > settings.json',
        'dd if=a.json of=~/.claude/settings.json',
        'cp -t ~/.claude a.json',
        'echo x > $CLAUDE_CONFIG_DIR/settings.json',
        """python -c "open('/srv/me/.claude/settings.json', 'w')\"""",
        'cat ~/.claude/settings.json > /tmp/x; echo y > ~/.claude/settings.json',
        'cp ~/.claude/settings.json backup.json',
        'cd ~ && echo x > .claude/settings.json',
        'pushd ~; cp a.json .claude-work/settings.json',
        'Set-Location $HOME; Set-Content .claude/settings.local.json x',
        'HOME=/tmp/h sh -c "echo x > .claude/settings.json"',
        'echo x > ~/.cl*de/settings.json',
        'echo x > ~/.claude*/settings.json',
        'cp a.json ~/.{claude,x}/settings.json',
        'echo x > ~/.c?aude/settings.json',
        'echo x > "$(echo ~)"/.claude/settings.json',
        'cp a.json `echo ~`/.claude/settings.json',
        'echo x > ~/".claude"/settings.json',
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
        'cd .claude/worktrees/lane && git status',
        'ls ~/.cache/*',
    ),
}
