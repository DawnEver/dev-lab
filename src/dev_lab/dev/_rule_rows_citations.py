"""The rules registry, CITATIONS part -- pure DATA, the same row shape as ``_rule_rows.py``.

The rows about what a tracked file may cite. A module named for its concept, not a size split.
"""

from __future__ import annotations

ROWS: tuple[tuple[str, str, tuple[str | tuple[str, str], ...]], ...] = (
    (
        'TRACKED-CITES-NO-EPHEMERAL',
        (
            'No tracked file lives under, or cites, untracked content in a place git never keeps -- a git-ignored '
            'path or a declared stray root such as `scratch/` -- nor a machine-local path (code may still WRITE '
            'one); a `<placeholder>` shape passes, and escapes are a declared set under a falling ceiling.'
        ),
        ('tests/test_famtests_ephemeralrefs.py',),
    ),
    (
        'EVIDENCE-OUTLIVES-OUTPUT',
        (
            'A recorded number, verdict, golden or decision in a tracked file names a tracked home for its evidence '
            '(a dated memory entry, a tracked fixture); a path under the output tree, or any ignored path, is never '
            'provenance -- every Python literal, a literal joined onto the repo root, and TOML/YAML/JSON values are '
            'judged; code may still WRITE there, and escapes are a declared set under a falling ceiling.'
        ),
        ('tests/test_famtests_evidencerefs.py',),
    ),
)
