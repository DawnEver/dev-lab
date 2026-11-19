"""LEDGER-MIGRATES-ON-INSTALL: the one step every door that installs a lab-commons environment runs right after.

A lab-commons whose box ledger migrates once (``python -m lab_commons.box migrate``) REFUSES every process that
opens an unmigrated ledger. So a machine that just installed it must migrate before anything there opens the
ledger, or it is left refusing. :func:`migrate` is that step, called by each installing door: the dependency
door's bootstrap, sync and lock upgrade (:mod:`dev_lab.dev.dep`, which the workstation and host-refresh doors
reach) and the HPC account deploy's venv build (:func:`dev_lab.dev.hpcaccount.steps.build`).

DETECTED BY CAPABILITY, never by version: the installed environment's own ``-m lab_commons.box --help`` must
name the ``migrate`` verb. An environment without it is skipped and says so. A failed migration is reported
naming the ledger and the command to rerun, and its exit code is the door's -- never swallowed.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Final

import lab_commons.launch as _door
from lab_commons.log import emit

__all__ = ['VERB', 'command', 'migrate']

#: The installed environment's box door.
VERB: Final = ('-m', 'lab_commons.box')
_WALL_S: Final = 600.0
_NAMES_MIGRATE: Final = re.compile(r'\bmigrate\b')
_LEDGER: Final = 'from lab_commons.box.ledger import box_path; print(box_path())'


def command(python: str) -> tuple[str, ...]:
    """The migration *python*'s environment runs: idempotent, under the ledger's write lock."""
    return (python, *VERB, 'migrate')


def migrate(python: str, *, run: Callable[..., Any] = _door.run, env: Mapping[str, str] | None = None) -> int:
    """Migrate this machine's box ledger with *python*'s lab-commons when it provides the verb; its exit code.

    *run* is called as :func:`subprocess.run` is. 0 when migrated, or skipped (said by name) when *python* is no
    file or provides no verb.
    """
    if not Path(python).is_file():
        emit(f'box ledger: no interpreter at {python}; migration skipped')
        return 0
    io = {'capture_output': True, 'text': True, 'encoding': 'utf-8', 'check': False, 'timeout': _WALL_S}
    if env is not None:
        io['env'] = dict(env)
    probe = run([python, *VERB, '--help'], **io)
    if probe.returncode or not _NAMES_MIGRATE.search(probe.stdout or ''):
        emit(f'box ledger: {python} provides no `-m lab_commons.box migrate`; migration skipped')
        return 0
    argv = command(python)
    done = run(list(argv), **io)
    if not done.returncode:
        emit(f'box ledger migrated: {" ".join(argv)}')
        return 0
    where = run([python, '-c', _LEDGER], **io)
    ledger = (where.stdout or '').strip() if not where.returncode else ''
    tail = ((done.stderr or '') + (done.stdout or '')).strip().splitlines()[-5:]
    emit(
        f'REFUSED: box ledger migration failed (exit {done.returncode}) on '
        f'{ledger or "the default ledger (LAB_COMMONS_BOX, else the platform default)"}; '
        f'every process opening it is refused until it succeeds. Rerun: {" ".join(argv)}',
        err=True,
    )
    for line in tail:
        emit(f'  {line}', err=True)
    return done.returncode
