"""The agent deny registry, LEDGER-WRITES-THROUGH-ITS-DOOR row -- pure DATA.

The SHELL half of :mod:`dev_lab.dev.ledgerguard`: a redirect, ``tee``, a ``cp``/``mv``/``Copy-Item``/``Move-Item``
target, ``sed -i``, ``touch``, ``Out-File``/``Set-Content``/``Add-Content`` onto a task's ``TASK.md`` or
``JOURNAL.md``. The file's shape is :data:`dev_lab.dev.ledgerguard.LEDGER_FILE`, spoken here; reading one is allowed.
And the DIRECTORY half (folded in 2026-11-24 from the second ledger guard): a ``mkdir``/``rm``/``rmdir``/``mv`` or
its PowerShell spelling naming the ledger directory or a path in it (:data:`dev_lab.dev.ledgerguard.LEDGER_DIR_TAIL`,
derived below the machine home, so no home name is in the pattern).
"""

from __future__ import annotations

from dev_lab.dev.ledgerguard import HAZARD, LEDGER_DIR_TAIL, LEDGER_FILE, REMEDY, RULE_ID

__all__ = ['LEDGER_WRITES_THROUGH_ITS_DOOR']

_PATH = r"""["']?[^\s"';&|()<>]*?"""
_TARGET = rf"""{_PATH}{LEDGER_FILE}["']?(?=[\s;&|)]|$)"""
# spelling-off -- the regexes below spell character classes ([Ii]tem), not words
#: What creates, removes or moves a directory entry, in either shell.
_MUTATORS = r'(?:mkdir|md|rm|rmdir|rd|del|mv|[Nn]ew-[Ii]tem|ni|[Rr]emove-[Ii]tem|ri|[Mm]ove-[Ii]tem|[Rr]ename-[Ii]tem)'
_WRITERS = (
    rf'>>?\s*{_TARGET}'
    rf'|\btee\b(?:\s+-\S+)*\s+{_TARGET}'
    rf'|\bsed\b[^;&|\n]*\s-i\S*\s[^;&|\n]*?{_TARGET}'
    rf'|\b(?:touch|[Oo]ut-[Ff]ile|[Ss]et-[Cc]ontent|[Aa]dd-[Cc]ontent)\b[^;&|\n]*?\s(?:-\w+\s+)?{_TARGET}'
    rf'|\b(?:cp|mv|[Cc]opy-[Ii]tem|[Mm]ove-[Ii]tem)\b[^;&|\n]*\s{_TARGET}\s*(?=[;&|)]|$)'
    rf'|\b{_MUTATORS}\b[^;&|\n]*?{LEDGER_DIR_TAIL}'
)
# spelling-on

LEDGER_WRITES_THROUGH_ITS_DOOR: dict[str, object] = {
    'id': RULE_ID,
    'pattern': f'(?:{_WRITERS})',
    'matches': 'argument',
    'hazard': HAZARD,
    'remedy': REMEDY,
    'needs': None,
    'refuses': (
        'echo "- done" >> ~/repos/tasks/toolchain/JOURNAL.md',
        'printf x > work/tasks/t/TASK.md',
        'echo x | tee -a D:\\home\\repos\\tasks\\t\\JOURNAL.md',
        'sed -i s/open/closed/ repos/tasks/t/TASK.md',
        'cp draft.md repos/tasks/archive/2026-11-23/t/TASK.md',
        'Set-Content -Path repos\\tasks\\t\\TASK.md -Value x',
        'mkdir ~/m/repos/tasks/new-task',
        'rm -rf ~/m/repos/tasks/toolchain',
        'Remove-Item -Recurse C:\\m\\repos\\tasks\\toolchain',
        'mv ~/m/repos/tasks/t ~/m/repos/tasks/archive/2026-11-24/t',
    ),
    'permits': (
        'cat repos/tasks/t/TASK.md',
        'git diff -- repos/tasks/t/JOURNAL.md',
        'echo x > docs/TASK.md',
        'echo x > tasks/t/NOTES.md',
        'cp repos/tasks/t/TASK.md output/logs/26/11/23/t/TASK.md',
        'python -m dev_lab.dev.task log t "done"',
        'ls ~/m/repos/tasks/t',
        'git -C ~/m/repos/tasks push',
    ),
}
