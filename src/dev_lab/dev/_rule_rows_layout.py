"""The rules registry's LAYOUT rows -- pure DATA, the same row shape as ``_rule_rows.py``.

Every rule about which directories a checkout may hold and what each may hold.
"""

from __future__ import annotations

ROWS: tuple[tuple[str, str, tuple[str | tuple[str, str], ...]], ...] = (
    (
        'DECLARED-LAYOUT',
        (
            # Why: user rulings 2026-11-23 -- the WHOLE directory and subdirectory tree is declared with its formats.
            'A checkout`s whole tree is an ALLOW-LIST in `[tool.dev_lab.placement.layout]` of its pyproject: each '
            'directory pattern (one glob per segment; the deepest matching row judges) lists the formats a file '
            'there may be, and anything undeclared is refused. Every family home is declared; `output/` never '
            'allows code or `*`; a `read_only` path (user-maintained input) is never written; a `.claude/` below '
            'the root is refused. The write hook refuses a Write/Edit, every `verify` and forge tick runs the '
            'INCREMENTAL scan (a journal of directory mtimes in the git dir), and every adopter`s architecture '
            'suite walks the filesystem under a floor (`dev_lab.dev.famtests.layout`).'
        ),
        ('tests/test_dev_layout.py', 'tests/test_arch_code_placement.py'),
    ),
    (
        'NO-BACKUP-COPIES',
        (
            # Why: user ruling 2026-11-23 -- 3.4 M copied source files under one repo's output/ (333 GB).
            '`output/` and `scratch/` never hold a copy or backup of work: no clone or worktree (a `.git`), no '
            'exported tree (`pyproject.toml` beside `src/`), no bundle, patch or diff, whatever a layout row says. '
            'Work is merged or deleted (MERGE-OR-DELETE), never saved aside. The shell guard refuses a command '
            'that makes one there, the write hook refuses the file, and the layout scan names the directory.'
        ),
        ('tests/test_dev_layout.py', 'tests/test_dev_nobackup.py'),
    ),
    (
        'PRIOR-ART-FIRST',
        (
            # Why: two sessions writing one concept twice under one name, neither having searched the tree first.
            'Before new code, search the tree and memory for the capability. A NEW product-source module named like '
            'a tracked one is refused at the write (`priorart`, the `codeplace` hook) until its own text cites each '
            'such module by path or dotted name, saying how it differs; same concept, extend the existing one.'
        ),
        ('tests/test_dev_priorart.py',),
    ),
)
