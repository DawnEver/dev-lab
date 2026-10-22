"""The rules registry, CITATIONS part -- pure DATA, the same row shape as ``_rule_rows.py``.

The rows about what a tracked file may cite. A module named for its concept, not a size split.
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
