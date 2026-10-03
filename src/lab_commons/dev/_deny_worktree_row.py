"""The agent deny registry, WORKTREES-STAY-INSIDE row -- pure DATA, split from `_deny_rows` by the size band.

Its path regex is derived from :data:`lab_commons.dev.worktreeplace.WORKTREES_REL`, the one spelling.
"""

from __future__ import annotations

from lab_commons.dev.worktreeplace import WORKTREES_REL

__all__ = ['WORKTREES_STAY_INSIDE']

#: WORKTREES-STAY-INSIDE, built from pieces so the PATTERN and the OPENING name the same verbs.
#: A shell TOKEN: a quoted string or a bare word that stops at a shell separator.
_SHELL_WORD = r"""(?:"[^"\n]*"|'[^'\n]*'|[^\s;&|()]+)"""
#: The location, spelled from the one constant, accepting either separator (Windows and POSIX).
_WT = r'[\\/]+'.join(WORKTREES_REL.replace('.', r'\.').split('/')) + r'[\\/]+[\w.-]+[\\/]?'
#: A target INSIDE `.claude/worktrees/<name>`, bare or quoted, with no `..` segment anywhere in it.
_INSIDE = (
    r'(?:"(?![^"\n]*\.\.)(?:[^"\n]*[\\/])?' + _WT + r'"'
    r"|'(?![^'\n]*\.\.)(?:[^'\n]*[\\/])?" + _WT + r"'"
    r'|(?![^\s;&|()]*\.\.)(?:[^\s"\';&|()]*[\\/])?' + _WT + r')'
)
_END = r'(?=\s|$|[;&|)])'
#: `git [-C <dir>] [-c <k=v>]`, and the retry wrapper a repo routes its network verbs through.
_GIT = r'\bgit(?:\.exe)?(?:\s+-[Cc]\s+' + _SHELL_WORD + r')*\s+'
_RETRY = r'\b(?:sh|bash)\s+\S*retry\S*\s+'
#: `worktree add`'s options; `-b`/`-B`/`--reason` consume a value, so the PATH is the first word after them.
_ADD_OPT = (
    r'(?:-[bB]\s+' + _SHELL_WORD + r'|--reason(?:=|\s+)' + _SHELL_WORD + r'|--(?!reason\b)[\w-]+|-(?![bB](?:\s|$))\w+)'
)
_GOOD_ADD = r'(?:\s+' + _ADD_OPT + r')*\s+' + _INSIDE + _END
_GOOD_MOVE = r'(?:\s+-\S+)*\s+' + _SHELL_WORD + r'\s+' + _INSIDE + _END
_GOOD_CLONE = r'(?:\s+' + _SHELL_WORD + r')*?\s+' + _INSIDE + r'\s*(?=$|[;&|)\n])'

WORKTREES_STAY_INSIDE: dict[str, object] = {
    'id': 'WORKTREES-STAY-INSIDE',
    'pattern': (
        r'(?:git(?:\.exe)?(?:\s+-[Cc]\s+' + _SHELL_WORD + r')*\s+(?:worktree\s+(?:add|move)|clone)'
        r'|(?:sh|bash)\s+\S*retry\S*\s+clone)\b'
    ),
    'matches': 'command',
    # The opening holds only when EVERY such verb in the text lands inside: the engine tests an
    # opening against the WHOLE command, so an opening that matched one good verb would also open a
    # second, misplaced one chained after it with `&&`.
    'allow': (
        r'^(?![\s\S]*(?:' + _GIT + r'(?:worktree\s+add(?!' + _GOOD_ADD + r')|worktree\s+move(?!' + _GOOD_MOVE + r')'
        r'|clone(?!' + _GOOD_CLONE + r'))|' + _RETRY + r'clone(?!' + _GOOD_CLONE + r')))'
    ),
    'hazard': (
        'a checkout created OUTSIDE its repository is outside every scan, ignore rule and search that '
        'repository runs over itself, and outside the place the next agent looks for it. MEASURED '
        '2026-10-03: eight worktrees across the family had been created as siblings of their repos, and '
        'the user ruled that day that it is forbidden family-wide.'
    ),
    'remedy': (
        f'Put it inside the repository: git worktree add --detach {WORKTREES_REL}/<name> <sha> (from the '
        f'repo root; with -C, git -C <repo> worktree add --detach <repo>/{WORKTREES_REL}/<name> <sha>). '
        f'To relocate one: git worktree move <tree> <repo>/{WORKTREES_REL}/<name>. A clone takes an '
        f'explicit target <repo>/{WORKTREES_REL}/<name> -- or is better a worktree.'
    ),
    'needs': None,
    'refuses': (
        'git worktree add --detach ../lab-commons-wt-cf 4ad12b6',
        'git worktree add -b feat/x ../ms-placement origin/main',
        'git -C C:/Users/me/PEMC/lab-commons worktree add C:/Users/me/PEMC/lc-placement 4ad12b6',
        'git -C "C:/Users/me/PEMC/lab commons" worktree add "C:/Users/me/PEMC/lc placement" HEAD',
        r'git worktree add C:\Users\me\PEMC\lab-commons-integrator HEAD',
        'git worktree add --detach /tmp/probe 4ad12b6',
        'git worktree add .claude/worktrees/../../escape 4ad12b6',
        'git worktree add -b .claude/worktrees/x ../evil origin/main',
        'git worktree move .claude/worktrees/lane ../lane',
        'git clone https://forge.example/o/r.git ../r-copy',
        'git clone https://forge.example/o/r.git',
        'sh scripts/hooks/with-retry.sh clone https://forge.example/o/r.git ../r-copy',
    ),
    'permits': (
        'git worktree add --detach .claude/worktrees/probe 4ad12b6',
        'git worktree add -b feat/x .claude/worktrees/x origin/main',
        'git worktree add --detach ./.claude/worktrees/probe 4ad12b6',
        'git -C C:/me/lab-commons worktree add --detach C:/me/lab-commons/.claude/worktrees/wt 4ad12b6',
        'git -C "C:/Users/me/PEMC/lab commons" worktree add "C:/Users/me/PEMC/lab commons/.claude/worktrees/wt" HEAD',
        r'git worktree add --detach C:\Users\me\PEMC\lab-commons\.claude\worktrees\wt 4ad12b6',
        'git worktree move ../lab-commons-wt-cf .claude/worktrees/lab-commons-wt-cf',
        'sh scripts/hooks/with-retry.sh clone https://forge.example/o/r.git .claude/worktrees/r-copy',
        'git worktree list --porcelain',
        'git worktree remove .claude/worktrees/probe',
        'git commit -m "refuse git worktree add ../x"',
    ),
}
