"""The rules registry, MEMORY part -- pure DATA, the same row shape as ``_rule_rows.py``.

The rows about how memory is kept, merged and carried. A module named for its concept, not a size split.
"""

from __future__ import annotations

ROWS: tuple[tuple[str, str, tuple[str | tuple[str, str], ...]], ...] = (
    (
        'MEMORY-SHAPE',
        (
            'Each memory entry lives under a dated YYYY/MM/DD path with frontmatter and is written once; it leaves '
            'only when a live entry names it in `merged_from` -- folded verbatim, superseded by a successor that '
            'restates the current truth, or distilled into the rule a crystallize ledger points at -- and is then '
            'deleted, git keeping its text; nothing records reads, the index is generated from what is there '
            'rather than curated beside it, and a task lands its state file with the commit that completes it.'
        ),
        (
            'tests/architecture/repo/test_memory_lives_in_dated_directories.py',
            'tests/architecture/docs/test_memory_files_live_under_a_dated_directory.py',
            'tests/architecture/docs/test_memory_index_map.py',
            'tests/architecture/docs/test_memory_leaves_only_by_merging.py',
        ),
    ),
    (
        'MONTHLY-PLANS-CARRIED',
        (
            'Every month holding a memory entry carries `YYYY/MM/SUMMARY-YYYY-MM.md`, whose `## Plans` section '
            'lists every plan the previous summary left open or partial, and an entry closes only by naming its '
            'evidence.'
        ),
        ('tests/test_famtests_monthsummary.py',),
    ),
)
