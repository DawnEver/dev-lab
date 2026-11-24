"""The agent deny registry, LEDGER-WRITES-THROUGH-ITS-DOOR row -- pure DATA.

The SHELL half of :mod:`dev_lab.dev.ledgerguard`: a redirect, ``tee``, a ``cp``/``mv``/``Copy-Item``/``Move-Item``
target, ``sed -i``, ``touch``, ``Out-File``/``Set-Content``/``Add-Content`` onto a task's ``TASK.md`` or
``JOURNAL.md``. The file's shape is :data:`dev_lab.dev.ledgerguard.LEDGER_FILE`, spoken here; reading one is allowed.
"""

from __future__ import annotations

from dev_lab.dev.ledgerguard import HAZARD, LEDGER_FILE, REMEDY, RULE_ID

__all__ = ['LEDGER_WRITES_THROUGH_ITS_DOOR']

_PATH = r"""["']?[^\s"';&|()<>]*?"""
_TARGET = rf"""{_PATH}{LEDGER_FILE}["']?(?=[\s;&|)]|$)"""
_WRITERS = (
    rf'>>?\s*{_TARGET}'
    rf'|\btee\b(?:\s+-\S+)*\s+{_TARGET}'
    rf'|\bsed\b[^;&|\n]*\s-i\S*\s[^;&|\n]*?{_TARGET}'
    rf'|\b(?:touch|[Oo]ut-[Ff]ile|[Ss]et-[Cc]ontent|[Aa]dd-[Cc]ontent)\b[^;&|\n]*?\s(?:-\w+\s+)?{_TARGET}'
    rf'|\b(?:cp|mv|[Cc]opy-[Ii]tem|[Mm]ove-[Ii]tem)\b[^;&|\n]*\s{_TARGET}\s*(?=[;&|)]|$)'
)

LEDGER_WRITES_THROUGH_ITS_DOOR: dict[str, object] = {
    'id': RULE_ID,
    'pattern': f'(?:{_WRITERS})',
    'matches': 'argument',
    'hazard': HAZARD,
    'remedy': REMEDY,
    'needs': None,
    'refuses': (
        'echo "- done" >> ~/repos/tasks/toolchain/JOURNAL.md',
        'printf x > .claude/tasks/t/TASK.md',
        'echo x | tee -a D:\\home\\repos\\tasks\\t\\JOURNAL.md',
        'sed -i s/open/closed/ repos/tasks/t/TASK.md',
        'cp draft.md repos/tasks/archive/2026-11-23/t/TASK.md',
        'Set-Content -Path repos\\tasks\\t\\TASK.md -Value x',
    ),
    'permits': (
        'cat repos/tasks/t/TASK.md',
        'git diff -- repos/tasks/t/JOURNAL.md',
        'echo x > docs/TASK.md',
        'echo x > tasks/t/NOTES.md',
        'cp repos/tasks/t/TASK.md output/logs/26/11/23/t/TASK.md',
        'python -m dev_lab.dev.task log t "done"',
    ),
}
