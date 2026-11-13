"""The COMMIT-HOOKS-RUN deny row -- pure DATA, split from `_deny_rows` by the size band.

Principle ``every-wall-teaches`` (ruling 2026-11-13): a hook that refuses a commit is a wall, and skipping it routes
around the wall instead of closing it. ``SUBAGENT-NO-PUSH`` already refuses ``--no-verify`` inside a subagent; this
row refuses every agent the commit-time skips -- ``git commit --no-verify``/``-n`` and a ``-c core.hooksPath=`` that
points git at no hooks for one command. A token is a quoted string or a bare word, so a ``-n`` inside a message is
never read as the flag.
"""

from __future__ import annotations

__all__ = ['COMMIT_HOOKS_RUN']

#: A shell TOKEN: a quoted string or a bare word that stops at a shell separator.
_WORD = r"""(?:"[^"\n]*"|'[^'\n]*'|[^\s"';&|()]+)"""
#: `git` and its leading `-C <dir>`/`-c <k=v>` options.
_GIT = r'git(?:\.exe)?(?:\s+-[Cc]\s*' + _WORD + r')*?'

COMMIT_HOOKS_RUN: dict[str, object] = {
    'id': 'COMMIT-HOOKS-RUN',
    'pattern': (
        _GIT + r'\s+-c\s*["\']?core\.[Hh]ooks[Pp]ath='
        r'|' + _GIT + r'\s+commit(?:\s+' + _WORD + r')*?\s+(?:--no-verify|-n)(?=\s|$|[;&|)])'
    ),
    'matches': 'command',
    'hazard': 'a skipped commit hook routes around the wall it raised, so its cause is met again by the next commit.',
    'remedy': 'Commit with the hooks: fix the cause the refusing hook names; a worktree with no venv: '
    '{python} -m dev_lab.dev.dep --bootstrap <worktree>.',
    'needs': None,
    'refuses': (
        'git commit --no-verify -m "x"',
        'git commit -n -m "x"',
        'git commit -m "x" -n',
        'git -C .claude/worktrees/x commit -m "x" --no-verify',
        'git -c core.hooksPath=/dev/null commit -m "x"',
        "git -c 'core.hooksPath=' commit -m x",
        'git -c core.hookspath=nul commit -m x',
    ),
    'permits': (
        'git commit -m "x"',
        'git commit -m "refuse -n and --no-verify"',
        'git log -n 5',
        'git config --get core.hooksPath',
        'git -c user.name=t commit -m "x"',
    ),
}
