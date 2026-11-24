"""The agent deny registry, LEDGER-WRITTEN-BY-ITS-DOOR row -- pure DATA.

The SHELL half of :mod:`dev_lab.dev.taskguard`, whose hazard and remedy this row speaks: a redirection, ``tee``,
``sed -i``, ``touch``/``mkdir``/``rm``, ``Set-Content``/``Out-File``/``Add-Content``/``New-Item``/``Remove-Item``
into the task ledger, or a ``cp``/``mv``/``Copy-Item``/``Move-Item`` ONTO it (its last word). Reading stays free, and
so does git (the door's own commit door, a push of the clone). ``matches: 'line'``: the write can sit anywhere on
the line. HOME-AGNOSTIC: the pattern names the ledger's ``repos/tasks`` tail, never a machine home.
"""

from __future__ import annotations

import re

from dev_lab.dev.taskguard import HAZARD, REMEDY, RULE_ID
from dev_lab.dev.taskledger import LEDGER_DIR

__all__ = ['LEDGER_WRITTEN_BY_ITS_DOOR']

_LEDGER = r'[\/]+repos[\/]+' + re.escape(LEDGER_DIR) + r'(?![^\s\/"\';&|])'
_ANY = r'[^\n;&|]*'
_LAST = r'[^\s;&|]*["\']?\s*(?:$|[;&|)\n])'

LEDGER_WRITTEN_BY_ITS_DOOR: dict[str, object] = {
    'id': RULE_ID,
    'pattern': (
        rf'(?:>{_ANY}{_LEDGER}'
        rf'|\b(?:tee|touch|mkdir|rm|rmdir|truncate)\b{_ANY}{_LEDGER}'
        rf'|\bsed\b(?=[^\n;&|]*\s-[a-zA-Z]*i){_ANY}{_LEDGER}'
        rf'|(?:Set-Content|Out-File|Add-Content|New-Item|Remove-Item){_ANY}{_LEDGER}'
        rf'|\b(?:cp|mv|Copy-Item|Move-Item)\b{_ANY}{_LEDGER}{_LAST})'
    ),
    'matches': 'line',
    'hazard': HAZARD,
    'remedy': REMEDY,
    'needs': None,
    'refuses': (
        'echo "- 2026-11-23 progress: x" >> ~/{home}/repos/tasks/t/JOURNAL.md',
        'sed -i "s/a/b/" C:/Users/<user>/{home}/repos/tasks/t/TASK.md',
        'rm -rf ~/{home}/repos/tasks/t',
        'cp TASK.md ~/{home}/repos/tasks/t/TASK.md',
        r'Add-Content -Path $HOME\{home}\repos\tasks\t\JOURNAL.md -Value x',
    ),
    'permits': (
        'cat ~/{home}/repos/tasks/t/JOURNAL.md',
        'cp ~/{home}/repos/tasks/t/JOURNAL.md scratch/journal.md',
        'git -C ~/{home}/repos/tasks push',
        'python -m dev_lab.dev.task log "repos/tasks moved"',
        'echo x > output/repos/tasks-list.txt',
    ),
}
