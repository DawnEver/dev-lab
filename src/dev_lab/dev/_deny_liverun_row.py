"""The TREE-HAS-A-LIVE-RUN deny row -- pure DATA, judged only while the target checkout has a live run.

``when: 'live-run'``: the engine matches the pattern as for any row, and only then asks
``python -m dev_lab.dev.liverun --tree <target>`` whether a run executes from the checkout the command
targets (its cwd, ``cd X &&``, ``git -C X``). No live run, no refusal: the same command is free in an idle
tree. The Edit/Write half renders its refusal from this same row (:mod:`dev_lab.dev.liverun`).
"""

from __future__ import annotations

from dev_lab.dev.venvpath import venv_interpreter

_NT, _POSIX = venv_interpreter(os_name='nt'), venv_interpreter(os_name='posix')

#: git verbs that rewrite the working tree or the index a run's checkout executes from.
_GIT_MUTATORS = 'merge|pull|checkout|switch|reset|apply|am|cherry-pick|rebase|restore|rm|mv|clean|stash'

LIVE_RUN: dict[str, object] = {
    'id': 'TREE-HAS-A-LIVE-RUN',
    'pattern': (
        rf'(?:git(?:\s+-[Cc]\s+\S+)*\s+(?:{_GIT_MUTATORS})'
        r'|\S*python[\w.]*\s+-m\s+dev_lab\.dev\.dep\b[^\n]*\s--(?:sync|bootstrap|lock-upgrade|upgrade-package)'
        r'|uv\s+(?:sync|add|remove|pip\s+(?:install|uninstall|sync)))(?![\w-])'
    ),
    'matches': 'command',
    'when': 'live-run',
    'hazard': 'a run in progress executes this checkout and its .venv; changing either mid-run makes its '
    'result describe a tree that never existed.',
    'remedy': 'Work in another worktree (git worktree add --detach .claude/worktrees/<name> <sha>), wait for '
    'the run, or stop it: python -m dev_lab.dev.stoprun --pid <pid>.',
    'needs': None,
    'refuses': (
        'git merge origin/integrate/main',
        'git -C .claude/worktrees/x merge --no-ff lane/x',
        'git checkout -- src/a.py',
        'git switch main',
        'git cherry-pick 4a4e8b13f',
        'git restore src/a.py',
        f'{_NT} -m dev_lab.dev.dep --sync',
        f'{_POSIX} -m dev_lab.dev.dep --bootstrap .claude/worktrees/x',
        'uv sync --frozen',
        'uv pip install requests',
    ),
    'permits': (
        'git status',
        'git log --oneline -5',
        'git diff --stat',
        'git show HEAD:src/a.py',
        'git merge-base --is-ancestor a b',
        f'{_NT} -m dev_lab.dev.dep --dry-run',
        'uv pip list',
    ),
}
