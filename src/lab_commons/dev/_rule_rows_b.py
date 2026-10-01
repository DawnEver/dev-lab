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
)
