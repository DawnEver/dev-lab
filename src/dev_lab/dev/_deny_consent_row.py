"""The agent deny registry, CONSENT-CODE-FROM-THE-USER row -- pure DATA.

The SHELL half of :mod:`dev_lab.dev.consentguard`, whose hazard and remedy this row speaks. A code the USER gave is
passed by the agent (user ruling 2026-11-08), so a code on a consent command line is no longer refused; what this row
refuses is a shell write under the consent state directory -- a credential no issuer signed. ``matches: 'line'``:
the write can sit anywhere on the line (``echo {} > ...``).
"""

from __future__ import annotations

import re

from dev_lab.dev.consentguard import HAZARD, REMEDY, RULE_ID, STATE_PARTS

__all__ = ['CONSENT_CODE_FROM_THE_USER']

#: HOME-AGNOSTIC: this row renders into every family repo's deny table, where a machine home's name is a private
#: marker, so the pattern names no home -- any ``/state/consent`` segment pair refuses, the real home under every
#: override included.
_STATE = ''.join(r'[\\/]+' + re.escape(part) for part in STATE_PARTS) + r'(?![^\s\\/"\';&|])'
_WRITERS = (
    r'(?:>|\btee\b|\bcp\b|\bmv\b|\bmkdir\b|\btouch\b'
    r'|Set-Content|Out-File|Add-Content|New-Item|Copy-Item|Move-Item)'
)

CONSENT_CODE_FROM_THE_USER: dict[str, object] = {
    'id': RULE_ID,
    'pattern': rf'{_WRITERS}[^\n;&|]*{_STATE}',
    'matches': 'line',
    'hazard': HAZARD,
    'remedy': REMEDY,
    'needs': None,
    'refuses': (
        'echo {} > ~/{home}/state/consent/x.json',
        'cp cred.json C:/Users/<user>/{home}/state/consent/',
        'Set-Content -Path $HOME\\{home}\\state\\consent\\x.json -Value x',
    ),
    'permits': (
        'python -m dev_lab.ops.consent grant output/req.json',
        'python -m dev_lab.ops.consent grant output/req.json --code 123456',
        'echo 123456 | python -m dev_lab.ops.consent grant output/req.json',
        'python -m dev_lab.dev.forge breakglass open --credential 0b1c2d3e-aaaa-bbbb-cccc-1234567890ab',
        'python -m dev_lab.dev.forge pr breakglass 123456 --reason "review bot is down"',
        'cat ~/{home}/state/consent/x.json',
    ),
}
