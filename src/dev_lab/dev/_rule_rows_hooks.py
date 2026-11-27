"""The rules registry, HOOKS part -- pure DATA, the same row shape as ``_rule_rows.py``.

The rows about the agent hooks the family renders: what the shared deny machinery answers, and what a hook may cost
the session it runs in. AGENT-GUARD moved here from ``_rule_rows.py`` by subject (2026-11-27).
"""

from __future__ import annotations

ROWS: tuple[tuple[str, str, tuple[str | tuple[str, str], ...]], ...] = (
    (
        'AGENT-GUARD',
        (
            'A hand-written test invocation and a stash are refused, and a bare network verb is hinted toward the '
            'retry door (a repo raises it to a refusal in its adoption severities), by the shared deny machinery '
            'rather than by prose, so the answer is identical in every repo that adopts it.'
        ),
        (
            '.claude/hooks/deny-commands.js',
            '.claude/hooks/deny-rules.json',
            'tests/architecture/gate/test_agent_bash_guard.py',
        ),
    ),
    (
        'HOOK-UNDER-FIVE-SECONDS',
        (
            'Every hook source on one event together finishes under five seconds (user ruling D24, 2026-11-17: a '
            'slow hook let a 30-second TOTP code expire): each rendered hook row carries a timeout of at most five, '
            'the family dispatcher keeps a far smaller share, and a row that can take longer is detached -- run to '
            'completion by one background runner per repo, its answer delivered at the next context event -- never '
            'cut or skipped; a guard cannot be detached, so it stays inline and fast. The door for a slow row: make '
            'it fast, or declare it `detached = true`.'
        ),
        ('tests/test_dev_hook_budget.py',),
    ),
    (
        'IMAGES-BY-ABSOLUTE-PATH',
        (
            # Why: user ruling 2026-11-22.
            'An image a turn delivers is named by its ABSOLUTE path: a relative one resolves against a working '
            'directory the reader is not in. The Stop hook reads the final message and sends back one that names '
            'an image file by a relative path; a URL, a pattern and a template are not paths and pass.'
        ),
        ('tests/test_dev_imagepath.py',),
    ),
    (
        'WORKTREE-NAMES-ITS-TASK',
        (
            # Why: user ruling 2026-11-22 -- an agent appending a string of hash is strictly forbidden.
            'A worktree`s directory name has a physical meaning related to its task (its feature, as its branch '
            'says); a hash-like name -- `agent-<hex>`, a name that is or ends in a hash -- is refused by name when '
            'the tree is made or moved, and a tree that arrived another way is detected from git`s own list.'
        ),
        ('tests/test_dev_worktreename.py', 'tests/test_dev_hooks.py'),
    ),
    (
        'WORKTREES-DO-NOT-NEST',
        (
            # Why: v1 family request FAM-10 (D158) -- an agent given an isolation worktree added a second one.
            'An agent spawned with worktree isolation already HAS its tree and never adds a second: a tree added '
            'from inside a linked worktree nests under it, outside the one home every scan and reclaim reads. '
            'git`s own worktree list is read and a tree lying inside another linked tree is named with the move '
            'that puts it in the home.'
        ),
        ('tests/test_dev_worktreeplace.py',),
    ),
)
