"""The rules registry, HOOKS part -- pure DATA, the same row shape as ``_rule_rows.py``.

The rows about the agent hooks the family renders: what a hook may cost the session it runs in.
"""

from __future__ import annotations

ROWS: tuple[tuple[str, str, tuple[str | tuple[str, str], ...]], ...] = (
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
)
