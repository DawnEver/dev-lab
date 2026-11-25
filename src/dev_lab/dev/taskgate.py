"""A SESSION COMMITS UNDER ITS TASK: a repo declaring it refuses an agent push from a branch naming no open task.

User ruling 2026-11-14 (a pilot in one very large repo; opt-in, never a family default): in a repo declaring
``[tool.dev_lab.task] required = true``, a native agent session publishes work only from a branch
``pr/<slug>/<feature>`` of a task OPEN in the machine's one task ledger. A human push is not judged.

THE BRANCH IS THE TASK (user ruling 2026-11-23): there is no binding store; the checkout's HEAD names the task
(:func:`dev_lab.dev.taskledger.task_of`) and the ledger (:func:`dev_lab.dev.taskledger.ledger`) judges it open. This
gate is the GIT side, run at commit-msg AND pre-push: rem's PreToolUse guard exists only under Claude Code, so the
git side is the backstop that holds for Codex, Antigravity or any agent (2026-11-20; sessions read by
:mod:`dev_lab.dev.native_session`). WHICH heads an agent session pushes is judged in every repo, not only a required
one: ``PUSHED-HEAD-CARRIES-ITS-TASK`` in the ``session-branch`` row (:mod:`dev_lab.dev.sessionbranch`).

The journal (JOURNAL.md) is appended to only through the task door, :mod:`dev_lab.dev.task`.

* :func:`refusal` -- the ``task-bound-commit`` commit-msg and ``task-bound`` pre-push rows (``githooks/base.toml``);
  it reads files only, no rem CLI.
* :func:`record` -- ``forge pr create`` / ``forge issue create`` append the opened URL to the branch's task journal
  (:func:`dev_lab.dev.task.append`, a ``log`` line), so the task names its own PRs and issues.
* :func:`task_prs` -- the PR numbers a task's journal names: what ``forge watch --task <slug>`` watches.
"""

from __future__ import annotations

import os
import re
import sys
import tomllib
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Final, Protocol

from lab_commons.log import emit

from dev_lab.dev import taskledger
from dev_lab.dev.family import declared_table
from dev_lab.dev.native_session import session_of
from dev_lab.dev.taskledger import slug_of

__all__ = [
    'COMMIT_HOOK_ID',
    'HOOK_ID',
    'RULE',
    'TaskUnreadable',
    'main',
    'record',
    'refusal',
    'required',
    'task_prs',
    'watch_argv',
]

RULE: Final = 'SESSION-COMMITS-UNDER-ITS-TASK'
#: The id this guard runs under in ``githooks/base.toml``.
HOOK_ID: Final = 'task-bound'
COMMIT_HOOK_ID: Final = 'task-bound-commit'
_TABLE: Final = 'task'
_OPENED: Final = re.compile(r'(?:pr|issue) opened: (\S+)')
_PULL: Final = re.compile(r'/pulls?/(\d+)\b')


class TaskUnreadable(RuntimeError):
    """A task's journal cannot be read here."""


def required(root: Path) -> bool:
    """Whether *root*'s pyproject declares ``[tool.dev_lab.task] required = true``."""
    try:
        data = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    table = declared_table(data, _TABLE, {})
    return isinstance(table, dict) and table.get('required') is True


def _off_task(root: Path) -> str | None:
    """Why the checkout at *root* works on no open task: its branch names none, or one the ledger holds not open."""
    branch = taskledger.branch_of(root)
    try:
        task = taskledger.task_of(root)
    except taskledger.LedgerUnresolvedError as unresolved:
        return f'{RULE}: {branch} names a task, and the task ledger cannot be read: {unresolved}'
    except ValueError as closed:
        return f'{RULE}: {branch} names a task the task ledger does not hold open: {closed}.\nDoor: {taskledger.DOOR}.'
    if task is None:
        return (
            f'{RULE}: this repo requires every agent session to work on a task branch, and '
            f'{branch or "a detached HEAD"} is none.\nDoor: {taskledger.DOOR}.'
        )
    return None


def refusal(root: Path, *, env: Mapping[str, str]) -> str | None:
    """Why an agent's push (or ``forge sync`` commit) in *root* is refused, or ``None``.

    Judged only in a required repo, for a native agent session: *root*'s branch names no task open in the ledger.
    """
    try:
        judged = required(root) and bool(session_of(env))
    except ValueError as unread:
        return f'{RULE}: this repo requires an agent session on a task branch, and the session cannot be read: {unread}'
    return _off_task(root) if judged else None


def _task_slug(root: Path) -> str | None:
    task = taskledger.task_of(root)
    return None if task is None else slug_of(task)


def record(root: Path, kind: str, url: str) -> str | None:
    """Append ``<kind> opened: <url>`` to the journal of *root*'s task through the task door; the line, or ``None``."""
    from dev_lab.dev import task as door  # noqa: PLC0415 -- the door's imports only when a PR or issue opened

    try:
        if not required(root) or (slug := _task_slug(root)) is None:
            return None
        return door.append(slug, 'log', f'{kind} opened: {url}')
    except (ValueError, LookupError) as unread:
        return f'{RULE}: not recorded in the task journal: {unread}'


def task_prs(task: str) -> tuple[int, ...]:
    """The PR numbers *task*'s journal records as opened (:func:`record`), in order, each once.

    Raises:
        TaskUnreadable: the task has no journal in the ledger.

    """
    try:
        shown = (taskledger.ledger() / task / 'JOURNAL.md').read_text(encoding='utf-8')
    except (OSError, LookupError) as unread:
        msg = f'task {task} has no journal in the ledger ({unread}).\nDoor: python -m dev_lab.dev.task list'
        raise TaskUnreadable(msg) from None
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


def watch_argv(words: Sequence[str], client: Callable[[], _PrHeads]) -> list[str]:
    """``forge watch`` argv with ``--task <slug>`` replaced by the head shas of every PR the task records.

    Raises:
        TaskUnreadable: no slug, an unreadable journal, or no PR head recorded.

    """
    at = list(words).index('--task')
    if at + 1 >= len(words):
        msg = '--task needs a task slug'
        raise TaskUnreadable(msg)
    task = words[at + 1]
    prs = task_prs(task)
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
