"""A SESSION COMMITS UNDER ITS TASK: a repo that declares it refuses an agent's commit or push with no task bound.

User ruling 2026-11-14 (a pilot in one very large repo; opt-in, never a family default): in a repo declaring
``[tool.dev_lab.task] required = true``, an agent session (:data:`dev_lab.dev.sessionprs.SESSION_ENV` set) commits
and pushes only while an OPEN rem task is bound to its working tree. A human commit is not judged.

LAYERING. rem owns the task ledger (TASK.md, JOURNAL.md, the binding rule); this module only READS it, through rem's
own CLI, and appends only through rem's own append verb -- it never parses or writes rem's files. The binding is
rem's: ``task.js bound`` resolves the worktree directory name, else the branch's last segment (``pr/<slug>``), to an
open task, so one source says which task a tree works on. rem's CLI is found at :data:`REM_ENV` (a path to
``task.js``), else in Claude Code's installed-plugins record. A required repo whose ledger cannot be read refuses
(fail closed), naming what is missing.

* :func:`refusal` -- the ``task-bound`` pre-commit and pre-push row (``githooks/base.toml``).
* :func:`record` -- ``forge pr create`` / ``forge issue create`` append the opened URL to the bound task's journal
  (``task.js log``), so the task names its own PRs and issues.
* :func:`task_prs` -- the PR numbers a task's journal names: what ``forge watch --task <slug>`` watches.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tomllib
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Final, Protocol

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.family import declared_table
from dev_lab.dev.sessionprs import SESSION_ENV

__all__ = [
    'HOOK_ID',
    'REM_ENV',
    'RULE',
    'Reader',
    'TaskUnreadable',
    'bound_task',
    'main',
    'reader_for',
    'record',
    'refusal',
    'required',
    'task_prs',
    'watch_argv',
]

RULE: Final = 'SESSION-COMMITS-UNDER-ITS-TASK'
#: The id this guard runs under in ``githooks/base.toml``.
HOOK_ID: Final = 'task-bound'
#: A path to rem's ``task.js``; overrides the installed-plugin lookup.
REM_ENV: Final = 'DEV_LAB_REM_TASK'
_TABLE: Final = 'task'
_REM_PLUGIN: Final = 'rem@'
_NONE: Final = '(none)'
_OPENED: Final = re.compile(r'(?:pr|issue) opened: (\S+)')
_PULL: Final = re.compile(r'/pulls?/(\d+)\b')
_NODE: Final = shutil.which('node') or 'node'

#: ``read(root, args) -> (exit status, stdout)``: one call of rem's task CLI in *root*.
Reader = Callable[[Path, Sequence[str]], tuple[int, str]]


class TaskUnreadable(RuntimeError):
    """rem's task ledger cannot be read here: no CLI found, or the CLI failed."""


def required(root: Path) -> bool:
    """Whether *root*'s pyproject declares ``[tool.dev_lab.task] required = true``."""
    try:
        data = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    table = declared_table(data, _TABLE, {})
    return isinstance(table, dict) and table.get('required') is True


def _rem_cli(env: Mapping[str, str], home: Path) -> Path | None:
    if declared := env.get(REM_ENV):
        return Path(declared)
    try:
        plugins = json.loads((home / '.claude' / 'plugins' / 'installed_plugins.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    for name, installs in (plugins.get('plugins') or {}).items():
        if name.startswith(_REM_PLUGIN) and installs:
            return Path(installs[-1]['installPath']) / 'scripts' / 'task.js'
    return None


def reader_for(env: Mapping[str, str], home: Path) -> Reader:
    """Rem's own task CLI as a :data:`Reader`; it raises :class:`TaskUnreadable` when no CLI is found."""
    cli = _rem_cli(env, home)

    def read(root: Path, args: Sequence[str]) -> tuple[int, str]:
        if cli is None or not cli.is_file():
            msg = f"rem's task CLI is not found (set {REM_ENV} to its task.js, or install the rem plugin)"
            raise TaskUnreadable(msg)
        done = _door.run(
            [_NODE, str(cli), *args],
            cwd=root,
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=False,
            timeout=60,
            env={**os.environ, 'CLAUDE_PROJECT_DIR': str(root)},
        )
        return done.returncode, (done.stdout.strip() or done.stderr.strip())

    return read


def bound_task(root: Path, read: Reader) -> str | None:
    """The open task rem binds *root* to, or ``None``.

    Raises:
        TaskUnreadable: rem's CLI failed.

    """
    status, said = read(root, ['bound'])
    if status != 0:
        raise TaskUnreadable(said or f'task.js bound exited {status}')
    return None if said in {'', _NONE} else said


def refusal(root: Path, *, env: Mapping[str, str], read: Reader) -> str | None:
    """Why an agent's commit or push in *root* is refused, or ``None``: required, and no open task bound."""
    if not required(root) or not env.get(SESSION_ENV):
        return None
    try:
        task = bound_task(root, read)
    except TaskUnreadable as unread:
        return f'{RULE}: this repo requires an open rem task, and the task ledger cannot be read: {unread}'
    if task is not None:
        return None
    return (
        f'{RULE}: this repo requires every agent session to work under an open rem task, and none is bound to '
        f"this tree (rem binds the worktree directory name, else the branch's last segment, to an open task). "
        f'Door: work in a worktree or on a branch named after an open task (`task.js list`), or ask the user to open '
        f'one with /rem:task open <slug> "<goal>".'
    )


def record(root: Path, kind: str, url: str, *, env: Mapping[str, str], read: Reader) -> str | None:
    """Append ``<kind> opened: <url>`` to the bound task's journal through rem; the line said, or ``None``."""
    if not required(root) or not env.get(SESSION_ENV):
        return None
    try:
        task = bound_task(root, read)
        if task is None:
            return None
        status, said = read(root, ['log', f'{kind} opened: {url}', '--task', task])
    except TaskUnreadable as unread:
        return f'{RULE}: not recorded in the task journal: {unread}'
    return said if status == 0 else f'{RULE}: task.js log exited {status}: {said}'


def task_prs(root: Path, task: str, read: Reader) -> tuple[int, ...]:
    """The PR numbers *task*'s journal records as opened (:func:`record`), in order, each once.

    Raises:
        TaskUnreadable: rem's CLI failed.

    """
    status, shown = read(root, ['show', task])
    if status != 0:
        raise TaskUnreadable(shown or f'task.js show exited {status}')
    numbers: list[int] = []
    for url in _OPENED.findall(shown):
        if (pull := _PULL.search(url)) is not None and int(pull.group(1)) not in numbers:
            numbers.append(int(pull.group(1)))
    return tuple(numbers)


class _Pr(Protocol):
    @property
    def head_sha(self) -> str: ...


class _PrHeads(Protocol):
    def pr_view(self, number: int) -> _Pr: ...


def watch_argv(words: Sequence[str], client: Callable[[], _PrHeads], *, read: Reader | None = None) -> list[str]:
    """``forge watch`` argv with ``--task <slug>`` replaced by the head shas of every PR the task records.

    Raises:
        TaskUnreadable: no slug, an unreadable journal, or no PR head recorded.

    """
    at = list(words).index('--task')
    if at + 1 >= len(words):
        msg = '--task needs a task slug'
        raise TaskUnreadable(msg)
    task, root = words[at + 1], Path.cwd()
    reader = read or reader_for(os.environ, Path.home())
    prs = task_prs(root, task, reader)
    forge = client() if prs else None
    heads = [head for n in prs if forge is not None and (head := forge.pr_view(n).head_sha)]
    if not heads:
        msg = f'task {task} records no open PR head'
        raise TaskUnreadable(msg)
    return [*heads, *words[:at], *words[at + 2 :]]


def main(argv: Sequence[str] | None = None) -> int:
    """The ``task-bound`` hook row: exit 1 with :func:`refusal`'s line, else 0."""
    del argv
    root = Path.cwd()
    if (refused := refusal(root, env=os.environ, read=reader_for(os.environ, Path.home()))) is not None:
        emit(refused, err=True)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
