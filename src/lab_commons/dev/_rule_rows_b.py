"""The rules registry, SECOND half -- pure DATA, the same row shape as ``_rule_rows.py``.

A second file because the first is pinned at its measured size (`tests/test_arch_module_size_alarm.py`)
and a registry that only grows cannot live in one module under a band that only falls.
"""

from __future__ import annotations

ROWS: tuple[tuple[str, str, tuple[str | tuple[str, str], ...]], ...] = (
    (
        'CODE-IN-CODE-ROOTS',
        (
            'Source code lives only under a root the repo DECLARES for code -- an allow-list, walked over the '
            'filesystem rather than the index, so an untracked probe in an output or data directory is refused '
            'instead of accumulating there. A fix belongs in the function that owns the behaviour; a one-off '
            'belongs in scratch.'
        ),
        ('tests/test_arch_code_placement.py', 'tests/test_dev_codeplace.py'),
    ),
    (
        'SCRATCH-ARCHIVED-OR-PROMOTED',
        (
            'A one-off script lives in scratch for a bounded time and then leaves it: PROMOTED into the function '
            'that owns its behaviour, with tests, or ARCHIVED as evidence beside the memory of the day it '
            'served, with the '
            'finding it produced recorded. A scratch file past its time is refused, never left to rot.'
        ),
        ('tests/test_arch_code_placement.py', 'tests/test_dev_codeplace.py'),
    ),
    (
        'FORGE-THROUGH-THE-DOOR',
        (
            'Issue and pull-request reads and writes go through `python -m lab_commons.dev.forge` -- '
            '`issue list|view|create|comment|close`, `pr create|view`, the token through `auth login|status` -- '
            'never `gh`, `tea` or a raw API call, so every write the forge receives says which machine and which '
            'agent wrote it. A write the door has no verb for is reported to the integrator, not routed around.'
        ),
        ('tests/test_dev_forgework.py', 'tests/test_dev_hooks.py', 'tests/test_dev_agenthooks.py'),
    ),
    (
        'VERDICT-AS-STATUS',
        (
            'A verdict reaches the forge as a commit STATUS on the exact commit it judged, in a named context, '
            'carrying the verdict line: PASS is success, FAIL is failure, and INCONCLUSIVE publishes nothing. A '
            'verdict about a dirty or moving tree names no commit and is not posted, and a failed publish never '
            'changes the verdict or its exit code.'
        ),
        ('tests/test_dev_forgestatus.py', 'tests/test_dev_verify.py'),
    ),
    (
        'ISSUE-IS-INTENT',
        (
            'An issue records INTENT only. Its state -- todo, in progress, ready, done -- is DERIVED from the '
            'refs on origin and the gate status of a lane tip, never kept by hand in a label or a field. A claim '
            'is a stamped comment naming a branch; conflicting claims are reported for the human, and a chat '
            'message or an @-mention is a hint, never a trigger.'
        ),
        ('tests/test_dev_forgeissue.py',),
    ),
    (
        'WORKTREES-STAY-INSIDE',
        (
            'Every checkout of a repository -- a linked worktree, a moved one, a clone made for it -- lives '
            'under `<toplevel>/.claude/worktrees/<name>`, never beside or outside the repository. A tree '
            'outside is outside every scan, ignore rule and search the repository runs over itself.'
        ),
        ('tests/test_dev_worktreeplace.py', 'tests/test_dev_hooks.py'),
    ),
    (
        'NO-REFLECTION',
        (
            'No tracked Python outside attic/ and archived/ calls getattr, hasattr, setattr or delattr, or '
            'defines __getattr__. A field is read by attribute access, a capability by isinstance against a '
            'Protocol, a dataclass by dataclasses.fields/replace, a name-keyed choice by an explicit dict; '
            'routing the probe through vars() or __dict__ is the same probe. An irreducible boundary is a '
            'named allow-set entry carrying its reason.'
        ),
        ('tests/test_arch_production_carries_no_reflection.py',),
    ),
    (
        'PROJECT-FILES-HAVE-ONE-SOURCE',
        (
            'Every project-level file a repository tracks -- ignore and attribute files, the Makefile, hook and '
            'lint configuration, agent hook wiring, CI -- is either rendered from a family base plus the repo`s '
            'declared delta, or named as the repo`s own with the reason. One list says which; a file in neither, '
            'a hand edit to a rendered one, or a delta restating its base is refused.'
        ),
        ('tests/test_dev_famfiles.py', 'tests/test_dev_famconfig.py'),
    ),
)
