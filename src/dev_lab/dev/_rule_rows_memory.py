"""The rules registry, MEMORY part -- pure DATA, the same row shape as ``_rule_rows.py``.

The rows about how memory is kept, merged and carried. A module named for its concept, not a size split.
"""

from __future__ import annotations

ROWS: tuple[tuple[str, str, tuple[str | tuple[str, str], ...]], ...] = (
    (
        'MEMORY-SHAPE',
        (
            'Knowledge has four layers: rules, docs, memory (dated entries) and tasks '
            '(user-opened, in the global tasks repo, `dev_lab.dev.taskledger`). A memory entry sits under a '
            'YYYY/MM/DD path with '
            'frontmatter (`name`, `description`) and is never edited, deleted or moved once written -- a '
            'correction is a new entry naming it in `corrects:`, a consolidation one naming its sources in '
            '`merged_from:` -- so a change under `**/.claude/memory/**` may only ADD a file; the one move is '
            'an approved redacting rename (`dev_lab.dev.memoryentry`), and nothing moves into memory. No '
            '`accessed` field; the index `memory-index.md` is derived, gitignored, never under `rules/`.'
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
