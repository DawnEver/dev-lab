"""The rules registry, MEMORY part -- pure DATA, the same row shape as ``_rule_rows.py``.

The rows about how memory is kept, merged and carried. A module named for its concept, not a size split.
"""

from __future__ import annotations

ROWS: tuple[tuple[str, str, tuple[str | tuple[str, str], ...]], ...] = (
    (
        'MEMORY-SHAPE',
        (
            'Knowledge has four layers: rules, docs, memory (dated entries) and tasks '
            '(`.claude/tasks/<slug>/`, user-opened). A memory entry sits under a YYYY/MM/DD path with '
            'frontmatter (`name`, `description`) and is never edited, deleted or moved once written -- a '
            'correction is a new entry naming it in `corrects:`, a consolidation one naming its sources in '
            '`merged_from:` -- so a change under `**/.claude/memory/**` may only ADD a file; the two moves are '
            'a task archived into memory and an approved redacting rename (`dev_lab.dev.memoryentry`). No '
            '`accessed` field and no derived index: memory stays in each repo root, read and written through '
            '`python -m dev_lab.dev.memory` (`search`, `add`, `amend`, `redact`, `rename`).'
        ),
        (
            'tests/architecture/repo/test_memory_lives_in_dated_directories.py',
            'tests/architecture/docs/test_memory_files_live_under_a_dated_directory.py',
            'tests/architecture/docs/test_memory_leaves_only_by_merging.py',
            'tests/test_dev_memory.py',
        ),
    ),
    (
        'REM-RETIRED',
        (
            'The rem plugin is retired (user, 2026-11-23): no repo keeps `.claude/rules/rem/`, a memory index, rem`s '
            'state file or its config, and no machine keeps rem installed. A repo migrates once '
            '(`python -m dev_lab.dev.remretired migrate --apply`: crystallized pages fold into the topic pages, the '
            'rest is deleted, memory stays); a machine uninstalls once (`... uninstall --apply`). Its kept duties '
            'are dev-lab`s: rules at SessionStart, the ledger guard, the branch-derived task, forge events, memory.'
        ),
        ('tests/test_dev_remretired.py', 'tests/test_famtests_alwayson.py'),
    ),
    (
        'LEDGER-WRITES-THROUGH-ITS-DOOR',
        (
            'A task`s `TASK.md` and `JOURNAL.md` are written by the ledger CLI alone (`python -m dev_lab.dev.task`): '
            'opening or closing a task is the user`s act and a journal is append-only, so a file tool or a shell '
            'writer onto one is refused, wherever the ledger lives; reading one is allowed.'
        ),
        ('tests/test_dev_ledgerguard.py',),
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
