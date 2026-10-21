"""The rules registry, THIRD half -- pure DATA, the same row shape as ``_rule_rows.py``.

A third file because ``_rule_rows_b.py`` reached the module-size band (`tests/test_arch_module_size_alarm.py`).
"""

from __future__ import annotations

ROWS: tuple[tuple[str, str, tuple[str | tuple[str, str], ...]], ...] = (
    (
        'TRACKED-CITES-NO-EPHEMERAL',
        (
            'No tracked file lives under, or cites, a git-ignored or machine-local path (code may still WRITE '
            'one); a `<placeholder>` shape passes, and escapes are a declared set under a falling ceiling.'
        ),
        ('tests/test_famtests_ephemeralrefs.py',),
    ),
)
