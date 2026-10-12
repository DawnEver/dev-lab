"""A WINDOWS WORKSTATION AS A ``forge serve`` HOST: ``python -m lab_commons.dev.servetask [--dry-run]``.

The workstation counterpart of a cluster account's crontab line (:mod:`lab_commons.hpc.deploy`): one
Scheduled Task, ``lab-forge-serve``, run from the checkout it serves. It lives here, not in
:mod:`lab_commons.hpc`, because what it schedules is this package's own serve and lock.

THE TASK, as one ``schtasks /Create`` command:

* every 5 minutes (``/SC MINUTE /MO 5``); a tick still running when the next fires is skipped --
  ``MultipleInstancesPolicy IgnoreNew``, the policy ``schtasks /Create`` writes -- and ``--lock`` makes
  the serve refuse an overlap itself, whatever started it (:mod:`lab_commons.dev.servelock`);
* as THIS user, only while logged on (``/RU <user> /IT``, no stored password): the forge credential and
  a vendor's scheduler are per user, and nothing non-interactive has been measured yet;
* the action ``cmd /c cd /d <checkout> && <its .venv python> -m lab_commons.dev.forge serve
  --mode <mode> --lock`` -- a bare ``--lock`` is the default lock, resolved by the serve itself
  (:func:`lab_commons.dev.servelock.default_lock`, under this user's ``%LOCALAPPDATA%``).

``--dry-run`` prints the exact command and changes nothing. THE STOP STEP is to disable the Task --
``schtasks /Change /TN lab-forge-serve /DISABLE`` (``/ENABLE`` resumes it) -- then stop a serve still
running with ``python -m lab_commons.dev.stoprun --pid <pid>``, which releases its claim as ``stopped``.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

from lab_commons.dev.venvpath import venv_interpreter
from lab_commons.log import emit

__all__ = ['TASK', 'create_argv', 'main', 'this_user']

#: The Scheduled Task's name.
TASK: Final = 'lab-forge-serve'

#: ``schtasks /TR`` refuses an action longer than this.
_TR_MAX: Final = 261

_DISABLE: Final = f'schtasks /Change /TN {TASK} /DISABLE'


def this_user() -> str:
    """The domain-qualified name of the account running this, the account the Task runs as."""
    user = os.environ.get('USERNAME') or os.environ.get('USER', '')
    domain = os.environ.get('USERDOMAIN', '')
    return f'{domain}\\{user}' if domain else user


#: The checkout's own interpreter, relative to the checkout the action changes into.
_VENV_PYTHON: Final = venv_interpreter(os_name='nt')


def _python(root: Path) -> Path:
    return root / _VENV_PYTHON


def create_argv(root: Path, *, user: str, mode: str = 'integrate') -> list[str]:
    """The one ``schtasks /Create`` command that schedules *root*'s serve."""
    action = f'cmd /c cd /d "{root}" && "{_VENV_PYTHON}" -m lab_commons.dev.forge serve --mode {mode} --lock'
    return ['schtasks', '/Create', '/TN', TASK, '/SC', 'MINUTE', '/MO', '5', '/TR', action, '/RU', user, '/IT', '/F']


def main(
    argv: Sequence[str] | None = None,
    *,
    run: Callable[[list[str]], object] | None = None,
    windows: bool = os.name == 'nt',
) -> int:
    """Write the Task (or print it with ``--dry-run``); 0 done, 2 refused."""
    parser = argparse.ArgumentParser(prog='python -m lab_commons.dev.servetask', description=__doc__.splitlines()[0])
    parser.add_argument('--root', type=Path, default=Path.cwd(), help='the checkout the Task serves (default: cwd)')
    parser.add_argument('--mode', default='integrate', help='the serve mode (default: integrate)')
    parser.add_argument('--dry-run', action='store_true', help='print the exact command; change nothing')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = args.root.resolve()
    command = create_argv(root, user=this_user(), mode=args.mode)
    if not _python(root).is_file():
        emit(f'servetask refused: no {_python(root)}; build the checkout .venv first', err=True)
        return 2
    action = command[command.index('/TR') + 1]
    if len(action) > _TR_MAX:
        emit(f'servetask refused: the action is {len(action)} characters, schtasks takes {_TR_MAX}', err=True)
        return 2
    emit(subprocess.list2cmdline(command))
    emit(f'stop: {_DISABLE}')
    if args.dry_run:
        return 0
    if not windows:
        emit('servetask refused: a Scheduled Task is Windows-only; a POSIX host serves from cron', err=True)
        return 2
    runner = run or (lambda argv: subprocess.run(argv, check=False).returncode)
    return 0 if runner(command) == 0 else 2


if __name__ == '__main__':
    sys.exit(main())
