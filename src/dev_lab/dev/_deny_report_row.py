"""The agent deny registry, REPORTS-LIVE-IN-MEMORY row -- pure DATA.

USER RULING 2026-10-11: a report a person or agent WRITES (audit, analysis, design, plan, findings,
workflow write-up) belongs in ``.claude/memory/``, never in ``output/``; ``output/`` holds only what a
program can regenerate. This row is the SHELL half: a redirection, ``tee`` or ``Out-File`` that
creates a Markdown file under any ``output/``. The Write/Edit half is
:func:`dev_lab.dev.reportplace.refuse_report`, called by the ``codeplace`` write hook, and it
hands back the same hazard and remedy from this row. A program that writes its own Markdown (a run's
``comparison.md``) is unaffected: it writes through no agent tool.
"""

from __future__ import annotations

__all__ = ['REPORTS_LIVE_IN_MEMORY']

REPORTS_LIVE_IN_MEMORY: dict[str, object] = {
    'id': 'REPORTS-LIVE-IN-MEMORY',
    'pattern': (
        r'(?:>>?|\btee\b(?:\s+-a)?|\bOut-File\b(?:\s+-FilePath)?|\b(?:Set|Add)-Content\b(?:\s+-Path)?)'
        r'\s*["\']?(?:[^\s"\'<>|;&]*[/\\])?output[/\\][^\s"\'<>|;&]*\.md(?=["\'\s;&|)]|$)'
    ),
    'matches': 'argument',
    'hazard': 'a written report (audit, analysis, design, plan, findings) is not regenerable, '
    'and output/ holds only what a program can regenerate.',
    'remedy': 'Write it as a dated memory entry: .claude/memory/<yyyy>/<mm>/<dd>/<slug>.md with the '
    'MEMORY-SHAPE frontmatter (name, description, created, accessed, tags, metadata).',
    'needs': None,
    'refuses': (
        'echo x > output/logs/26/10/10/audit/test-suite-audit.md',
        'git log >> output/summary.md',
        'cat notes | tee output/logs/26/10/11/report/x.md',
        'Get-Content a | Out-File -FilePath D:\\repo\\output\\findings.md',
    ),
    'permits': (
        'git log > output/logs/26/10/11/merge/log.txt',
        'echo x > .claude/memory/2026/10/11/audit.md',
        'cat output/logs/26/10/10/audit/test-suite-audit.md',
        'cargo run -- --out output/logs/26/10/11/case/comparison.md',
    ),
}
