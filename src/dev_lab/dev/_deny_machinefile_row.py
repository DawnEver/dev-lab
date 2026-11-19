"""The agent deny registry, MACHINE-FILE-IS-RENDERED row -- pure DATA.

The SHELL half of :mod:`dev_lab.dev.machineguard`, whose hazard and remedy this row speaks: a redirection, ``tee``,
``sed -i``, or a ``cp``/``mv``/``Copy-Item``/``Move-Item``/``Set-Content``/``Out-File``/``Add-Content`` ONTO the
machine file. Reading it (``cat``, ``sed -n``, a ``cp`` FROM it) stays free. ``matches: 'line'``: the write can sit
anywhere on the line. HOME-AGNOSTIC: the tail is derived from :func:`lab_commons.config.config_path` below
:func:`lab_commons.home.home`, so no machine home's name is in the pattern.
"""

from __future__ import annotations

import re

from lab_commons.config import config_path
from lab_commons.home import home

from dev_lab.dev.machineguard import HAZARD, REMEDY, RULE_ID

__all__ = ['MACHINE_FILE_IS_RENDERED']

_PARTS = config_path().relative_to(home()).parts
#: The tail as the examples spell it: ``config/<file>``, derived, so no consumer's name is written here.
_SHOWN = '/'.join(_PARTS)
_SHOWN_WIN = '\\'.join(_PARTS)
_TAIL = ''.join(r'[\\/]+' + re.escape(part) for part in _PARTS)
#: The machine file as the LAST thing a shell word names (quoted or not).
_FILE = _TAIL + r'["\']?(?![^\s;&|])'
_END = r'\s*(?:$|[;&|)\n])'
_ANY = r'[^\n;&|]*'

MACHINE_FILE_IS_RENDERED: dict[str, object] = {
    'id': RULE_ID,
    'pattern': (
        rf'(?:>{_ANY}{_FILE}'
        rf'|\btee\b{_ANY}{_FILE}'
        rf'|\bsed\b(?=[^\n;&|]*\s-[a-zA-Z]*i){_ANY}{_FILE}'
        rf'|(?:Set-Content|Out-File|Add-Content){_ANY}{_FILE}'
        rf'|\b(?:cp|mv|Copy-Item|Move-Item)\b{_ANY}{_FILE}{_END})'
    ),
    'matches': 'line',
    'hazard': HAZARD,
    'remedy': REMEDY,
    'needs': None,
    'refuses': (
        f'echo "x = 1" >> ~/{{home}}/{_SHOWN}',
        f'sed -i "s/a/b/" C:/Users/<user>/{{home}}/{_SHOWN}',
        f'cat new.toml | tee ~/{{home}}/{_SHOWN}',
        f'cp new.toml ~/{{home}}/{_SHOWN}',
        rf'Set-Content -Path $HOME\{{home}}\{_SHOWN_WIN} -Value x',
    ),
    'permits': (
        f'cat ~/{{home}}/{_SHOWN}',
        f'sed -n "/repos/,/^$/p" ~/{{home}}/{_SHOWN}',
        f'cp ~/{{home}}/{_SHOWN} output/machine-copy.toml',
        'python -m dev_lab.dev.devhost local set repos.x C:/src/x',
        f'echo x > output/{_SHOWN}.bak',
    ),
}
