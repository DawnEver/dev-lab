"""The rules registry, THIRD half -- pure DATA, the same row shape as ``_rule_rows.py``.

A third file because ``_rule_rows_b.py`` reached the module-size band (`tests/test_arch_module_size_alarm.py`).
"""

from __future__ import annotations

ROWS: tuple[tuple[str, str, tuple[str | tuple[str, str], ...]], ...] = (
    (
        'TRACKED-CITES-NO-EPHEMERAL',
        (
            'No git-tracked file references what the repo`s own ignore rules ignore (`git check-ignore`), nor a '
            'machine-local path (a drive letter, a home or cluster root, a temp dir, the agent job tree), and no '
            'tracked file lives under an ignored root. Two tiers: PROSE (Markdown and the comments of code and '
            'config) gets the full rule; CODE refuses only READING such a path as an input, since writing to '
            'the output tree is what it is for. A `<placeholder>` segment or a bare ignored root names a shape '
            'and passes. Escapes are one declared, reasoned set whose count equals a ceiling that only goes '
            'down. Memory is included: an entry keeps its measured numbers inline, or a regeneration command.'
        ),
        ('tests/test_famtests_ephemeralrefs.py',),
    ),
)
