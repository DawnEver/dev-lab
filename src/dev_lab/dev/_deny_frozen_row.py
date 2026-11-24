"""The agent deny registry, USER-FROZEN-FILES row -- pure DATA, its pattern a prefilter and its judge a module.

The SHELL half of :mod:`dev_lab.dev.frozen`. Which paths are frozen is each checkout's own ``freeze.toml``, which no
regex reads, so the pattern matches any write verb and ``asks`` hands the line to ``dev_lab.dev.frozen --admit``,
which refuses only a write, move or removal landing on a frozen path. A line with no write verb spawns nothing.
"""

from __future__ import annotations

from dev_lab.dev.frozen import HAZARD, REMEDY, RULE_ID

__all__ = ['USER_FROZEN_FILES']

USER_FROZEN_FILES: dict[str, object] = {
    'id': RULE_ID,
    'pattern': (
        r'(?:\d?>(?!&)|\b(?:tee|sed\s+[^\n;&|]*-[a-zA-Z]*i|cp|mv|rm|touch|truncate)\b'
        r'|Set-Content|Out-File|Add-Content|Clear-Content|New-Item|Copy-Item|Move-Item|Remove-Item)'
    ),
    'matches': 'line',
    'asks': 'dev_lab.dev.frozen',
    'hazard': HAZARD,
    'remedy': REMEDY,
    'needs': None,
    'refuses': (
        'echo x > .vscode/settings.json',
        'rm freeze.toml',
        'Set-Content -Path .vscode/settings.json -Value x',
    ),
    'permits': (
        'cat .vscode/settings.json',
        'git status',
        'ls -la',
    ),
}
