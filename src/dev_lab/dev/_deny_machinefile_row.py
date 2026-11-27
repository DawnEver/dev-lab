"""The agent deny registry, MACHINE-FILE-IS-RENDERED row -- pure DATA, its pattern a prefilter and its judge a module.

The SHELL half of :mod:`dev_lab.dev.machineguard`, whose hazard and remedy this row speaks: a redirection, ``tee``,
``sed -i``, or a ``cp``/``mv``/``Copy-Item``/``Move-Item``/``Set-Content``/``Out-File``/``Add-Content`` ONTO the
machine file. Reading it (``cat``, ``sed -n``, a ``cp`` FROM it) stays free. ``matches: 'line'``: the write can sit
anywhere on the line.

NO MACHINE FILE NAME IN THE PATTERN (dev-lab #1000): the machine file's name is private to a machine, and this row
renders into every family repo's TRACKED ``deny-rules.json``. So the pattern only PREFILTERS the same write shape onto
ANY ``.toml``; the engine then asks :func:`dev_lab.dev.machineguard.main` (``--admit``), which derives this machine's
file at hook time and refuses only a write onto it.
"""

from __future__ import annotations

from dev_lab.dev.machineguard import HAZARD, REMEDY, RULE_ID, machine_parts, shell_write_pattern

__all__ = ['MACHINE_FILE_IS_RENDERED']

_PARTS = machine_parts()
#: The tail as the examples spell it (examples are proof data, never rendered).
_SHOWN = '/'.join(_PARTS)
_SHOWN_WIN = '\\'.join(_PARTS)
#: Any ``.toml`` as the last path a shell word names: the prefilter the judge narrows to this machine's file.
_ANY_TOML = r"""[\\/]+[^\\/\s"';&|]+\.toml"""

MACHINE_FILE_IS_RENDERED: dict[str, object] = {
    'id': RULE_ID,
    'pattern': shell_write_pattern(_ANY_TOML),
    'matches': 'line',
    'asks': 'dev_lab.dev.machineguard',
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
        f'cp ~/{{home}}/{_SHOWN} scratch/machine-copy.toml',
        'python -m dev_lab.dev.devhost local set repos.x C:/src/x',
        f'echo x > output/logs/26/11/20/machine/{_PARTS[-1]}.bak',
    ),
}
