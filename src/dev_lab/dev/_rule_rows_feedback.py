"""The rules registry, FEEDBACK part -- pure DATA, the same row shape as ``_rule_rows.py``.

The rows of the feedback loop: what a wall an agent hits must leave behind (``docs-src/dev/feedback.md``).
"""

from __future__ import annotations

ROWS: tuple[tuple[str, str, tuple[str | tuple[str, str], ...]], ...] = (
    (
        'WALLS-ARE-RECORDED',
        (
            'Every refusal an agent hits is a wall on record (principle `every-wall-teaches`, ruling 2026-11-13): '
            'the refusal choke point appends one line per wall -- session, rule, a sha256 prefix of the command, '
            'whether the refusal named a door -- to the dated `walls` ledger; a `Stop` hook refuses once to end a '
            'turn over a wall that named no door until the gap is closed or recorded (`walls close`); and no agent '
            'skips a commit hook (`COMMIT-HOOKS-RUN`). The loop: `docs-src/dev/feedback.md`.'
        ),
        ('tests/test_dev_walls.py', 'tests/test_dev_hooks.py'),
    ),
)
