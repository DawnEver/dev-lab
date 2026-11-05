"""A TASK CARRIES ITS KEY BUNDLE (user-approved design 2026-11-05): one secret per ai-lab task, loaded on stdin.

Each ai-lab task (``pr-review``, ``live``, ...) has ONE secret holding a TOML bundle of its model keys,
``[keys]`` with one list per provider in slot order. WHICH providers a task uses lives only in ai-lab's
``routes.toml``: dev-lab names no provider, it moves a task's bundle whole.

* :func:`secret_name` derives the secret's name from the task -- the ONE place that spelling is made;
* :func:`loader` is the ai-lab command that reads one bundle on stdin and stores it for its task;
* :func:`load` runs it, the bundle on stdin -- never argv, never a file, never a log line.
"""

from __future__ import annotations

import re
import subprocess
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

__all__ = ['PREFIX', 'REVIEW_TASK', 'load', 'loader', 'secret_name']

#: Every task's secret starts so: ``AI_LAB_KEYS_<TASK>``.
PREFIX: Final = 'AI_LAB_KEYS_'

#: The task a PR review and its judge run as.
REVIEW_TASK: Final = 'pr-review'

#: A task name ai-lab declares: lower-case words joined by ``-``.
_TASK: Final = re.compile(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*')


def secret_name(task: str) -> str:
    """The secret holding *task*'s bundle: ``AI_LAB_KEYS_`` and the task upper-cased, ``-`` as ``_``.

    Raises:
        ValueError: *task* is not a task name (lower-case words joined by ``-``).

    """
    if not _TASK.fullmatch(task):
        msg = f'{task!r} is not a task name: lower-case words joined by "-", e.g. {REVIEW_TASK}'
        raise ValueError(msg)
    return PREFIX + task.upper().replace('-', '_')


def loader(python: str, task: str) -> list[str]:
    """The isolated ai-lab command storing the bundle it reads on stdin for *task*, run by *python*."""
    secret_name(task)  # refuses a malformed task before it reaches a command line
    return [python, '-I', '-m', 'ai_lab.auth', 'login', '--task', task, '--bundle', '-']


def load(
    bundle: str, task: str, python: str, *, run: Callable[..., subprocess.CompletedProcess[str]] = _door.run
) -> None:
    """Store *bundle* for *task* through ai-lab's loader, on stdin; its output is never echoed (it may quote keys).

    Raises:
        OSError: the loader refused; the message names the task and exit code, never the bundle.

    """
    argv: Sequence[str] = loader(python, task)
    done = run(argv, input=bundle, capture_output=True, text=True, encoding='utf-8', check=False)
    if done.returncode != 0:
        msg = f'ai-lab refused the {task} key bundle (exit {done.returncode})'
        raise OSError(msg)
