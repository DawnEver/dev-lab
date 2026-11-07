"""The agent deny registry, CONSENT-CODE-NEVER-TYPED row -- pure DATA.

The SHELL half of :mod:`dev_lab.dev.consentguard`, whose hazard and remedy this row speaks. ``matches: 'line'``: a
code piped or heredoc'd into a consent command spans segments (``echo 123456 | ... consent grant``), so the pattern
reads the whole command line. It refuses a 6-digit number as an argument to, piped, here-stringed or heredoc'd into
a consent grant, break-glass open/enrol or TOTP command, and a shell write under the consent state directory.
"""

from __future__ import annotations

from dev_lab.dev.consentguard import HAZARD, REMEDY, RULE_ID, STATE_PARTS

__all__ = ['CONSENT_CODE_NEVER_TYPED']

#: A command that takes the user's code: consent's verbs, break-glass's code verbs, anything TOTP.
_TAKES_CODE = (
    r'(?:dev_lab\.ops\.consent\b|\bconsent\s+(?:grant|serve|enrol)\b|\bbreakglass\s+(?:open|enrol|serve)\b'
    r'|\b[Tt][Oo][Tt][Pp]\b)'
)
_CODE = r"""["']?\d{6}["']?"""
_STATE = r'[\\/]+'.join(part.replace('.', r'\.') for part in STATE_PARTS)
_WRITERS = (
    r'(?:>|\btee\b|\bcp\b|\bmv\b|\bmkdir\b|\btouch\b'
    r'|Set-Content|Out-File|Add-Content|New-Item|Copy-Item|Move-Item)'
)

CONSENT_CODE_NEVER_TYPED: dict[str, object] = {
    'id': RULE_ID,
    'pattern': (
        rf'(?:{_TAKES_CODE}[^\n;&|]*[\s=]{_CODE}(?=[\s;&|)]|$)'
        rf'|\b\d{{6}}\b[^\n;&|]*\|[^\n;&]*{_TAKES_CODE}'
        rf'|{_TAKES_CODE}[^\n]*<<<\s*{_CODE}'
        rf'|{_TAKES_CODE}[^\n]*<<-?\s*["\']?\w+["\']?[^\n]*\n\s*{_CODE}\s*(?:\n|$)'
        rf'|{_WRITERS}[^\n;&|]*{_STATE})'
    ),
    'matches': 'line',
    'hazard': HAZARD,
    'remedy': REMEDY,
    'needs': None,
    'refuses': (
        'python -m dev_lab.ops.consent grant req.json 123456',
        'python -m dev_lab.ops.consent grant req.json --code=123456',
        'echo 123456 | python -m dev_lab.ops.consent grant req.json',
        "printf '123456\\n' | python -m dev_lab.ops.consent grant req.json",
        'python -m dev_lab.ops.consent grant req.json <<< 123456',
        'python -m dev_lab.ops.consent grant req.json <<EOF\n123456\nEOF',
        'echo 654321 | python -m dev_lab.dev.forge breakglass open',
        'python -m dev_lab.ops totp 123456',
        'echo {} > ~/.motronics/state/consent/x.json',
        'cp cred.json C:/Users/u/.motronics/state/consent/',
        'Set-Content -Path $HOME\\.motronics\\state\\consent\\x.json -Value x',
    ),
    'permits': (
        'python -m dev_lab.ops.consent grant output/req.json',
        'echo 123456',
        'python -m dev_lab.dev.forge breakglass open --credential 0b1c2d3e-aaaa-bbbb-cccc-1234567890ab',
        'python -m dev_lab.dev.forge pr breakglass 123456 --reason "review bot is down"',
        'cat ~/.motronics/state/consent/x.json',
        'git log -n 123456 | grep consent',
    ),
}
