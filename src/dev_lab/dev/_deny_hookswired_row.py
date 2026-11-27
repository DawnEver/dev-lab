"""The HOOKS-ARE-WIRED deny row -- pure DATA, its pattern a prefilter and its judge :mod:`dev_lab.dev.hook_install`.

v1 FAM-14 (2026-11-27): every lane worktree committed, merged and pushed with zero family stages, because
``hook_install`` only REPORTED the missing shims. The pattern names a history-writing git verb -- typed, behind
``-C``/``-c``, or forwarded by the netverb door -- and ``asks`` hands the payload to
``python -m dev_lab.dev.hook_install --admit``, which refuses only when the tree the verb runs in is unwired
(:mod:`dev_lab.dev._hook_admit`). A wired tree pays one interpreter start on these verbs and nothing else.
"""

from __future__ import annotations

from dev_lab.dev._deny_push_rows import PUSH_FORWARDERS
from dev_lab.dev._hook_admit import HAZARD, RULE_ID, WRITE_VERBS

__all__ = ['HOOKS_ARE_WIRED']

_WORD = r"""(?:"[^"\n]*"|'[^'\n]*'|[^\s"';&|()]+)"""

HOOKS_ARE_WIRED: dict[str, object] = {
    'id': RULE_ID,
    'pattern': (
        PUSH_FORWARDERS + r'?(?:(?:"[^"]*[/\\])?"?\S*?\bgit(?:\.exe)?"?(?:\s+-[Cc]\s*' + _WORD + r')*)'
        r'\s+(?:' + '|'.join(WRITE_VERBS) + r')(?=\s|$|[;&|)])'
    ),
    'matches': 'command',
    'asks': 'dev_lab.dev.hook_install',
    'hazard': HAZARD,
    'remedy': '{python} -m dev_lab.dev.dep --bootstrap <tree>, then '
    '{python} -m dev_lab.dev.hook_install --repo <tree> --install.',
    'needs': None,
    'refuses': (
        'git commit -m x',
        'git merge --no-ff lane/a',
        'git -C .claude/worktrees/x push origin HEAD',
        'git cherry-pick abc123',
        'git rebase origin/main',
        'python -m dev_lab.dev.netverb -- git push origin HEAD',
    ),
    'permits': (
        'git status',
        'git log -n 3',
        'git commit-tree abc',
        'echo "git push"',
        'git merge-base HEAD origin/main',
    ),
}
