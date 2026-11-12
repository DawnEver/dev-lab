"""The rules registry, MEMORY part -- pure DATA, the same row shape as ``_rule_rows.py``.

The rows about how memory is kept, merged and carried. A module named for its concept, not a size split.
"""

from __future__ import annotations

ROWS: tuple[tuple[str, str, tuple[str | tuple[str, str], ...]], ...] = (
    (
        'MEMORY-SHAPE',
        (
            'Knowledge has four layers: rules (hard constraints), docs (mechanism), memory (dated entries) '
            'and tasks (`.claude/tasks/<slug>/TASK.md` + `JOURNAL.md`, user-opened). A memory entry sits '
            'under a YYYY/MM/DD path with frontmatter (`name`, `description`) and is never deleted, but may be '
            'updated in place or moved within memory (a package scope into the root included); a correction '
            'may name what it corrects in `corrects:`, a consolidation names its same-scope sources in '
            '`merged_from:`, citing a source file per paragraph -- so a change under `**/.claude/memory/**` '
            'never deletes a file nor moves one out of memory, the one move in being a task archived into '
            'memory; no `accessed` field is kept, and the index `<scope>/.claude/memory-index.md` is derived, '
            'gitignored and never under `rules/`.'
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
