"""THE ONE Scheduled Task that makes a Windows workstation a ``forge serve`` host: its name, command and state.

The workstation counterpart of a cluster account's crontab lines (:mod:`lab_commons.hpc.deploy`). ONE
Task, ``lab-forge-serve``, serves every repo the machine file declares (``[serve] repos``): its action
runs :mod:`lab_commons.dev.workstation` ``serve`` from the lab-commons checkout, which takes the
per-user serve lock once (:mod:`lab_commons.dev.servelock`) and serves each repo in turn from its own
checkout and venv. One Task and not one per repo, because the lock is per host: per-repo Tasks firing
on the same minute would either overlap (per-repo locks) or starve all but the first (one lock).
:mod:`lab_commons.dev.workstation` ``deploy`` writes it; nothing else does.

THE TASK, as one ``schtasks /Create`` command:

* every 5 minutes (``/SC MINUTE /MO 5``); a tick still running when the next fires is skipped --
  ``MultipleInstancesPolicy IgnoreNew``, the policy ``schtasks /Create`` writes;
* as THIS user, only while logged on (``/RU <user> /IT``, no stored password): the forge credential and
  a vendor's scheduler are per user, and nothing non-interactive has been measured yet;
* the action ``cmd /c cd /d <lab-commons checkout> && <its .venv python> -m lab_commons.dev.workstation
  serve --mode <mode>``.

THE STOP STEP is to disable the Task -- ``schtasks /Change /TN lab-forge-serve /DISABLE`` (``/ENABLE``
resumes it) -- then stop a serve still running with ``python -m lab_commons.dev.stoprun --pid <pid>``,
which releases its claim as ``stopped``.
"""

from __future__ import annotations

import html
import os
import re
from pathlib import Path
from typing import Final

from lab_commons.dev.venvpath import venv_interpreter

__all__ = ['DISABLE', 'TASK', 'TR_MAX', 'action_of', 'create_argv', 'installed_action', 'query_argv', 'this_user']

#: The Scheduled Task's name.
TASK: Final = 'lab-forge-serve'

#: ``schtasks /TR`` refuses an action longer than this.
TR_MAX: Final = 261

#: The documented stop.
DISABLE: Final = f'schtasks /Change /TN {TASK} /DISABLE'

#: The checkout's own interpreter, relative to the checkout the action changes into.
_VENV_PYTHON: Final = venv_interpreter(os_name='nt')


def this_user() -> str:
    """The domain-qualified name of the account running this, the account the Task runs as."""
    user = os.environ.get('USERNAME') or os.environ.get('USER', '')
    domain = os.environ.get('USERDOMAIN', '')
    return f'{domain}\\{user}' if domain else user


def action_of(lab: Path, *, mode: str = 'integrate') -> str:
    """The Task's action: serve every declared repo, from the lab-commons checkout *lab*."""
    return f'cmd /c cd /d "{lab}" && "{_VENV_PYTHON}" -m lab_commons.dev.workstation serve --mode {mode}'


def create_argv(lab: Path, *, user: str, mode: str = 'integrate') -> list[str]:
    """The one ``schtasks /Create`` command that schedules the serve of every declared repo."""
    action = action_of(lab, mode=mode)
    return ['schtasks', '/Create', '/TN', TASK, '/SC', 'MINUTE', '/MO', '5', '/TR', action, '/RU', user, '/IT', '/F']


def query_argv() -> list[str]:
    """The read-only query whose XML :func:`installed_action` reads."""
    return ['schtasks', '/Query', '/TN', TASK, '/XML']


def installed_action(xml: str) -> str:
    """The action of the Task whose ``schtasks /Query /XML`` is *xml*: ``<Command> <Arguments>``."""
    command = re.search(r'<Command>(.*?)</Command>', xml, re.DOTALL)
    arguments = re.search(r'<Arguments>(.*?)</Arguments>', xml, re.DOTALL)
    parts = [html.unescape(found[1]).strip() for found in (command, arguments) if found]
    return ' '.join(part for part in parts if part)
