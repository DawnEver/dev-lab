"""WHAT A WORKSTATION DEPLOY REQUIRES OF THE BOX, probed read-only before anything changes.

Steps 1 and 2 of :mod:`dev_lab.dev.workstation`'s deploy. PROBE: ``uv`` and ``git`` on PATH; ``node`` and
``codex`` when ``workstation`` is declared; JMAG Designer and its Scheduler COM classes when ``jmag`` is --
every missing item named with its remedy. CREDENTIAL: ``git ls-remote`` of every repo with prompting off,
so only a STORED git credential answers; none is ever read or printed.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from lab_commons.log import emit

from dev_lab.dev.netverb import run_network_verb
from dev_lab.dev.workstationfile import WORKSTATION

if sys.platform == 'win32':
    import winreg

__all__ = ['CREDENTIAL_REMEDY', 'JMAG_PROGIDS', 'com_server', 'missing', 'refused_credentials']

#: What a ``workstation`` declaration promises on ``PATH`` -- probed at deploy, so the declaration cannot lie.
_WORKSTATION_KIT: Final = ('node', 'codex')

#: The COM classes a ``jmag`` host drives: the Designer and its Scheduler.
JMAG_PROGIDS: Final = ('designer.Application', 'scheduler.JobApplication')

_REMEDIES: Final = {
    'uv': 'install uv: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"',
    'git': 'install Git for Windows: winget install --id Git.Git -e',
    'node': 'install Node.js LTS: winget install --id OpenJS.NodeJS.LTS -e',
    'codex': 'install the Codex CLI: npm install -g @openai/codex',
}
_JMAG_REMEDY: Final = 'install JMAG-Designer; its installer registers ' + ' and '.join(JMAG_PROGIDS)
#: The one manual step a refused credential names.
CREDENTIAL_REMEDY: Final = (
    'store your OWN git credential for the forge once -- `git clone <forge>/<repo>.git` anywhere and sign '
    'in, or `python -m dev_lab.dev.forge auth login` -- then re-run'
)
#: Prompting off: only a STORED credential can answer.
_NO_PROMPT: Final = {'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'never'}


def com_server(progid: str) -> Path | None:
    """The executable COM *progid* is registered to (``HKCR`` -> ``LocalServer32``), when it exists on disk."""
    if sys.platform != 'win32':
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, f'{progid}\\CLSID') as key:
            clsid = winreg.QueryValue(key, None)
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, f'CLSID\\{clsid}\\LocalServer32') as key:
            server = winreg.QueryValue(key, None).strip()
    except OSError:
        return None
    exe = Path(server[1:].split('"', 1)[0] if server.startswith('"') else server.split(' ', 1)[0])
    return exe if exe.is_file() else None


def missing(
    which: Callable[[str], str | None], com: Callable[[str], Path | None], capabilities: Mapping[str, Any]
) -> list[str]:
    """Every tool or COM class *capabilities* needs and the box lacks, each with its remedy."""
    wanted = ['uv', 'git', *(_WORKSTATION_KIT if WORKSTATION in capabilities else ())]
    emit(f'[probe] {", ".join([*wanted, *(["jmag"] if "jmag" in capabilities else [])])}')
    out = [f'{tool} not on PATH: {_REMEDIES[tool]}' for tool in wanted if which(tool) is None]
    if 'jmag' in capabilities and (absent := [p for p in JMAG_PROGIDS if com(p) is None]):
        out.append(f'COM class {", ".join(absent)} not registered: {_JMAG_REMEDY}')
    return out


def refused_credentials(git: Sequence[str], urls: Mapping[str, str]) -> list[str]:
    """The repos of *urls* no stored credential reads -- ``git ls-remote`` with prompting off."""
    emit('[credential] git ls-remote per repo, prompting off: only a stored credential answers')
    denied = []
    for name, url in urls.items():
        argv = [*git, '-c', 'credential.interactive=never', 'ls-remote', '-q', url, 'HEAD']
        rc = run_network_verb(argv, env={**os.environ, **_NO_PROMPT}).returncode
        emit(f'  {name}: {"ok" if rc == 0 else f"refused (exit {rc})"}')
        if rc:
            denied.append(name)
    return denied
