"""A SESSION COMMITS UNDER ITS TASK: a repo declaring it refuses an agent push off its bound task.

User ruling 2026-11-14 (a pilot in one very large repo; opt-in, never a family default): in a repo declaring
``[tool.dev_lab.task] required = true``, a native agent session publishes work only while it is bound to an OPEN
rem task. A human push is not judged.

ONE SOURCE, TWO SIDES (2026-11-16). rem owns the ledger and the binding: its ``UserPromptSubmit`` hook binds a
session on the user's ``task: <slug>`` prompt, and its ``PreToolUse`` task guard covers the work inside the session.
This gate is the GIT side only -- a pure reader of rem's files (:mod:`dev_lab.dev.taskbinding`, rem's documented
contract), run at pre-push and never at a commit: a local commit is in-session work, already rem's.

THE BINDING IS THE USER'S WORD (decision D5, 2026-11-15): the task a session works on is the one its user bound it
to, never a guess from a worktree directory or a branch name. A bound session pushes its task's heads
``pr/<slug>/<feature>`` -- one per PR, so a landed PR never forces a new task -- or a branch outside ``pr/`` (local
fan-out, a detached tip); a ``pr/`` branch not under its own task (another task's, the bare ``pr/<slug>``, a flat
``pr/<feature>``) is refused naming the bound task. An unbound session is refused naming rem's door: the user's
``task: <slug>`` prompt, which rem's hook binds.

rem's journal (JOURNAL.md) is appended to and read only through rem's own CLI, found at :data:`REM_ENV` (a path to
``task.js``), else in Claude Code's installed-plugins record.

* :func:`refusal` -- the ``task-bound`` pre-push row (``githooks/base.toml``); it reads files only, no rem CLI.
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

from dev_lab.dev import remplugin, taskbinding
from dev_lab.dev.family import declared_table
from dev_lab.dev.native_session import session_of
from dev_lab.dev.taskbinding import head_for, slug_of

__all__ = [
    'HOOK_ID',
    'REM_ENV',
    'RULE',
    'Reader',
    'TaskUnreadable',
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
_OPENED: Final = re.compile(r'(?:pr|issue) opened: (\S+)')
_PULL: Final = re.compile(r'/pulls?/(\d+)\b')
_NODE: Final = shutil.which('node') or 'node'
_GIT: Final = shutil.which('git') or 'git'

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


def _branch(root: Path) -> str:
    """The branch checked out in *root*, or ``''`` on a detached HEAD."""
    done = _door.run(
        [_GIT, 'symbolic-ref', '--quiet', '--short', 'HEAD'],
        cwd=root, capture_output=True, text=True, encoding='utf-8', check=False,
    )  # fmt: skip
    return done.stdout.strip() if done.returncode == 0 else ''


def _unbound(root: Path, env: Mapping[str, str], home: Path) -> tuple[str | None, str | None]:
    """``(open bound task id, None)``, or ``(None, why)`` -- no session, an unreadable one, none bound, or closed.

    With none bound, the door names the session's binder when its registry shows why it bound nothing (rem absent,
    disabled or older than the binding release, :func:`dev_lab.dev.remplugin.binder_door`), else the user's prompt.
    """
    try:
        task = taskbinding.session_task(env, start=root)
    except ValueError as unread:
        return (
            None,
            f'{RULE}: this repo requires a session bound to an open task, and the session cannot be read: {unread}',
        )
    if task is None:
        # The binder's own text is a cause line and a door line; the user's prompt is a door line alone.
        binder = remplugin.binder_door(env, home, root)
        door = f' {binder}' if binder else f'\nDoor: {taskbinding.DOOR}'
        return None, (
            f'{RULE}: this repo requires every agent session to work under the task its user bound it to, '
            f'and none is bound.{door}.'
        )
    try:
        still = taskbinding.task_id(root, slug_of(task))
    except ValueError:
        still = None
    if still != task:
        closed = f'{RULE}: this session is bound to task {task}, which is no longer open.'
        return None, f'{closed}\nDoor: {taskbinding.DOOR}.'
    return task, None


def refusal(root: Path, *, env: Mapping[str, str], branch: str | None = None, home: Path | None = None) -> str | None:
    """Why an agent's push (or ``forge sync`` commit) in *root* is refused, or ``None``.

    Judged only in a required repo, for a native agent session: no open task bound to the session in rem's ledger,
    or a ``pr/`` branch outside the bound task's ``pr/<slug>/`` namespace. *branch* defaults to the one checked out
    in *root*.
    """
    try:
        judged = required(root) and bool(session_of(env))
    except ValueError as unread:
        return f'{RULE}: this repo requires a session bound to an open task, and the session cannot be read: {unread}'
    if not judged:
        return None
    task, why = _unbound(root, env, Path.home() if home is None else home)
    if task is None:
        return why
    slug = slug_of(task)
    branch = _branch(root) if branch is None else branch
    if not branch.startswith(taskbinding.PREFIX) or taskbinding.under(branch, slug):
        return None
    return (
        f'{RULE}: this session is bound to task {task}, and {branch} is not one of its heads '
        f'({head_for(slug, "<feature>")}).\n'
        f'Door: `git branch -m {branch} {head_for(slug, branch.rsplit("/", 1)[-1])}`; '
        'another task is the user`s to bind (`task: <slug>`).'
    )


def _bound_slug(root: Path, env: Mapping[str, str]) -> str | None:
    task = taskbinding.session_task(env, start=root)
    return None if task is None else slug_of(task)


def record(root: Path, kind: str, url: str, *, env: Mapping[str, str], read: Reader) -> str | None:
    """Append ``<kind> opened: <url>`` to the bound task's journal through rem; the line said, or ``None``."""
    try:
        if not required(root) or (task := _bound_slug(root, env)) is None:
            return None
        status, said = read(root, ['log', f'{kind} opened: {url}', '--task', task])
    except (TaskUnreadable, ValueError) as unread:
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
    if (refused := refusal(root, env=os.environ)) is not None:
        emit(refused, err=True)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
