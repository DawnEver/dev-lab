"""THE ONE Scheduled Task that makes a Windows workstation a ``forge serve`` host: its name, definition and state.

The workstation counterpart of a cluster account's crontab lines (:mod:`lab_commons.hpc.deploy`). ONE
Task, ``lab-forge-serve``, serves every repo the machine file declares (``[serve] repos``): its action
runs :mod:`lab_commons.dev.workstation` ``serve`` from the lab-commons checkout, which takes the
per-user serve lock once (:mod:`lab_commons.dev.servelock`) and serves each repo in turn from its own
checkout and venv. One Task and not one per repo, because the lock is per host: per-repo Tasks firing
on the same minute would either overlap (per-repo locks) or starve all but the first (one lock).
:mod:`lab_commons.dev.workstation` ``deploy`` writes it; nothing else does.

THE TASK, as one ``schtasks /Create /XML`` definition (:func:`task_xml`):

* every 5 minutes; a tick still running when the next fires is skipped (``IgnoreNew``);
* as THIS user, only while logged on (``InteractiveToken``, no stored password): the forge credential
  and a vendor's scheduler are per user, and JMAG's COM classes need the user's session;
* the action ``<lab-commons checkout>/.venv/Scripts/pythonw.exe -m lab_commons.dev.workstation serve
  --mode <mode>``, its working directory the checkout, the Task ``Hidden``.

INVISIBLE ON A WORKSTATION, MEASURED 2026-10-13: the earlier action ``cmd /c cd /d <checkout> && python
...`` opened a console window every five minutes while the user worked. ``pythonw.exe`` is a
GUI-subsystem interpreter and opens none; but a console child it started would open its OWN window, so
the serve starts its one child per repo with :func:`windowless` (``CREATE_NO_WINDOW``). That child gets a
console with no window, and every descendant -- verify, pytest workers, git, uv -- INHERITS that console
instead of allocating one. One flag at the root of the tree is therefore the whole fix, as long as
nothing below detaches (``DETACHED_PROCESS``/``CREATE_NEW_CONSOLE``), which nothing in the kit does.
With no console, the serve's own output and its children's go to :func:`log_path`, size-capped by one
rotation (:func:`open_log`). ``/TR`` takes neither a working directory nor ``Hidden``, hence ``/XML``.

THE STOP STEP is to disable the Task -- ``schtasks /Change /TN lab-forge-serve /DISABLE`` (``/ENABLE``
resumes it) -- then stop a serve still running with ``python -m lab_commons.dev.stoprun --pid <pid>``,
which releases its claim as ``stopped``.
"""

from __future__ import annotations

import html
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import IO, Final

from lab_commons.dev.servelock import default_lock
from lab_commons.dev.venvpath import venv_interpreter

__all__ = [
    'DISABLE', 'LOG_CAP', 'TASK', 'Definition', 'create_argv', 'definition_of', 'home', 'installed', 'log_path',
    'open_log', 'query_argv', 'task_xml', 'this_user', 'windowless',
]  # fmt: skip

#: The Scheduled Task's name.
TASK: Final = 'lab-forge-serve'

#: The documented stop.
DISABLE: Final = f'schtasks /Change /TN {TASK} /DISABLE'

#: The serve log rotates to ``serve.log.1`` once it holds this many bytes: at most about twice this on disk.
LOG_CAP: Final = 4 * 1024 * 1024

#: The checkout's own WINDOWLESS interpreter, relative to the checkout: ``pythonw.exe`` beside ``python.exe``.
_VENV_PYTHONW: Final = Path(venv_interpreter(os_name='nt')).with_name('pythonw.exe')


@dataclass(frozen=True)
class Definition:
    """Every fact of the Task that deploy owns; an installed Task differing in any one is rewritten."""

    command: str
    arguments: str
    working_directory: str
    logon_type: str = 'InteractiveToken'
    hidden: str = 'true'
    interval: str = 'PT5M'
    instances: str = 'IgnoreNew'


#: Each :class:`Definition` field's element in the Task XML.
_TAGS: Final = {
    'command': 'Command', 'arguments': 'Arguments', 'working_directory': 'WorkingDirectory',
    'logon_type': 'LogonType', 'hidden': 'Hidden', 'interval': 'Interval', 'instances': 'MultipleInstancesPolicy',
}  # fmt: skip

_XML: Final = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>forge serve of every [serve] repo, written by lab_commons.dev.workstation deploy</Description>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <Repetition><Interval>{interval}</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition>
      <StartBoundary>2026-01-01T00:00:00</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{user}</UserId>
      <LogonType>{logon_type}</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>{instances}</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <Hidden>{hidden}</Hidden>
    <ExecutionTimeLimit>PT72H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{command}</Command>
      <Arguments>{arguments}</Arguments>
      <WorkingDirectory>{working_directory}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def this_user() -> str:
    """The domain-qualified name of the account running this, the account the Task runs as."""
    user = os.environ.get('USERNAME') or os.environ.get('USER', '')
    domain = os.environ.get('USERDOMAIN', '')
    return f'{domain}\\{user}' if domain else user


def definition_of(lab: Path, *, mode: str = 'integrate') -> Definition:
    """The Task that serves every declared repo from the lab-commons checkout *lab*, with no window."""
    arguments = f'-m lab_commons.dev.workstation serve --mode {mode}'
    return Definition(command=str(lab / _VENV_PYTHONW), arguments=arguments, working_directory=str(lab))


def task_xml(task: Definition, *, user: str) -> str:
    """The Task Scheduler XML that ``schtasks /Create /XML`` registers *task* from, as *user*."""
    values = {**asdict(task), 'user': user}
    return _XML.format(**{name: html.escape(value, quote=False) for name, value in values.items()})


def create_argv(xml: Path) -> list[str]:
    """The one ``schtasks /Create`` command that registers the Task from the definition file *xml*."""
    return ['schtasks', '/Create', '/TN', TASK, '/XML', str(xml), '/F']


def query_argv() -> list[str]:
    """The read-only query whose XML :func:`installed` reads."""
    return ['schtasks', '/Query', '/TN', TASK, '/XML']


def installed(xml: str) -> Definition | None:
    """The :class:`Definition` of the Task whose ``schtasks /Query /XML`` is *xml*; ``None`` with no action."""
    found = {}
    for name, tag in _TAGS.items():
        match = re.search(rf'<{tag}>(.*?)</{tag}>', xml, re.DOTALL)
        found[name] = html.unescape(match[1]).strip() if match else ''
    return Definition(**found) if found['command'] else None


def windowless() -> dict[str, int]:
    """The ``subprocess`` keywords that start a child with NO console window: ``CREATE_NO_WINDOW`` on Windows."""
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}


def home() -> Path:
    """The per-user serve directory, the serve lock's: ``%LOCALAPPDATA%/lab-forge``, else ``~/.cache/lab-forge``."""
    return default_lock().parent


def log_path() -> Path:
    """Where a windowless serve, and every child it starts, writes."""
    return home() / 'serve.log'


def open_log(path: Path, *, cap: int = LOG_CAP) -> IO[str]:
    """*path* opened to append, line-buffered, after rotating it to ``<name>.1`` once it holds *cap* bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.stat().st_size >= cap:
        path.replace(path.with_name(path.name + '.1'))
    return path.open('a', encoding='utf-8', errors='replace', buffering=1)
