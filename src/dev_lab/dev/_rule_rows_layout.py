"""The rules registry's LAYOUT rows -- pure DATA, the same row shape as ``_rule_rows.py``.

Every rule about which directories a checkout may hold and what each may hold.
"""

from __future__ import annotations

ROWS: tuple[tuple[str, str, tuple[str | tuple[str, str], ...]], ...] = (
    (
        'DECLARED-LAYOUT',
        (
            # Why: user requirement 2026-11-23 -- every folder of a repo is declared, and a folder may forbid suffixes.
            'Every top-level directory of a checkout is DECLARED in `[tool.dev_lab.placement.layout]` of its '
            'pyproject, each with the file suffixes forbidden anywhere beneath it; the family homes are always '
            'declared and `output/` always forbids the OUTPUT-HOLDS-NO-CODE suffixes. A new directory is refused '
            'until it is declared on purpose. The write hook refuses a Write/Edit into an undeclared directory or '
            'of a forbidden suffix, and every adopter`s architecture suite walks its filesystem against the table '
            'under a floor (`dev_lab.dev.famtests.layout`).'
        ),
        ('tests/test_dev_layout.py', 'tests/test_arch_code_placement.py'),
    ),
)
