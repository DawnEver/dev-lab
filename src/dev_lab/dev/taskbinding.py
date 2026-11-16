"""A SESSION KEEPS ITS ONE TASK: the user's word binds it, and its branches derive from it (D5, 2026-11-15).

A prompt whose FIRST line is ``task: <slug>`` binds the session receiving it to that OPEN task of the checkout:
the ``UserPromptSubmit`` hook (``python -m dev_lab.dev.taskbinding bind``, :func:`bind`) writes the binding from the
harness's own payload (its ``session_id``, the user's ``prompt``). An agent can name a worktree or a branch after a
task and can set an environment variable; it cannot author the user's prompt, so neither of those binds. This is the
ONE session -> task record: the task gate (:mod:`dev_lab.dev.taskgate`), the integrator role
(:mod:`dev_lab.dev.hpcaccount.session`), the branch-name help and rem (which reads the file itself) all read it.

THE LEDGER AND THE BINDING ARE REPO STATE, NOT BRANCH STATE (W4, 2026-11-16: a task opened in one worktree was not
found from another, because each reader resolved a different tree). Both live in ONE directory, :func:`ledger` --
``<main checkout>/.claude/tasks/``, the parent of ``git rev-parse --git-common-dir``, the same from every worktree.
A binding is ``.bindings/<session>.json`` there, ``{"session": ..., "task": "<slug>@<authority>"}`` -- a format rem
owns and reads directly; rem's task guard refuses an agent's write to it. The ledger is never committed on a
feature branch: it is the working state of the repository, not of one branch.

A task id is ``<slug>@<authority>``: the ``authority`` the user's task-open minted into ``.claude/tasks/<slug>/
TASK.md``, so a task closed and reopened under the same slug is a new id and an old binding never carries over.

BRANCHES DERIVE FROM THE TASK. A bound session publishes ``pr/<slug>/<feature>`` (:func:`head_for`); a landed PR
ends a feature, never the task, so the next feature is ``pr/<slug>/<next>`` with no new binding. A task never
publishes a bare ``pr/<slug>``: git keeps a ref and the refs below it apart (``refs/heads/pr/<slug>`` is a file,
``refs/heads/pr/<slug>/x`` needs it to be a directory), so the bare branch would refuse every feature of its task.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final, TextIO

from lab_commons import launch
from lab_commons.log import emit

from dev_lab.dev.native_session import session_of, valid

__all__ = [
    'BINDINGS',
    'BIND_PROMPT',
    'DOOR',
    'PREFIX',
    'bind',
    'bound_task',
    'checkout_root',
    'head_advice',
    'head_for',
    'ledger',
    'main',
    'session_task',
    'slug_of',
    'task_id',
    'under',
]

#: Where the session -> task bindings live, below the :func:`ledger`.
BINDINGS: Final = '.bindings'
_SLUG: Final = r'[a-z0-9]+(?:-[a-z0-9]+)*'
#: The user's binding prompt: its FIRST line is exactly ``task: <slug>``.
BIND_PROMPT: Final = re.compile(rf'\A[ \t]*task:[ \t]*({_SLUG})[ \t]*(?:\r?\n|\Z)')
#: The namespace a task's PR heads live under: ``pr/<slug>/<feature>``.
PREFIX: Final = 'pr/'
#: The one door that binds a session, named by every refusal that finds none.
DOOR: Final = (
    'the user binds this session with a prompt whose first line is `task: <slug>` (an open task; '
    'a new one is opened by the user with /rem:task open <slug> "<goal>")'
)


def checkout_root(cwd: Path) -> Path:
    """The main checkout of the repository at *cwd* -- the parent of its common git dir, from any of its worktrees."""
    common = launch.run(
        [shutil.which('git') or 'git', 'rev-parse', '--path-format=absolute', '--git-common-dir'],
        cwd=cwd, capture_output=True, text=True, encoding='utf-8', check=True,
    ).stdout.strip()  # fmt: skip
    return Path(common).parent


def ledger(start: Path) -> Path:
    """THE ONE RESOLVER: the task ledger of the repository at *start* -- the same directory from every worktree.

    Raises:
        OSError, subprocess.CalledProcessError: *start* is in no git repository.

    """
    return checkout_root(start) / '.claude' / 'tasks'


def task_id(start: Path, slug: str) -> str:
    """The id ``<slug>@<authority>`` of the OPEN task *slug* in *start*'s :func:`ledger`; ValueError otherwise."""
    if not re.fullmatch(_SLUG, slug):
        msg = f'{slug!r} is not a task slug'
        raise ValueError(msg)
    try:
        path = ledger(start) / slug / 'TASK.md'
        head = path.read_text(encoding='utf-8').split('---')[1]
    except (OSError, IndexError, subprocess.CalledProcessError):
        msg = f'no task {slug} in the ledger of {Path(start).as_posix()}'
        raise ValueError(msg) from None
    fields = dict(line.split(':', 1) for line in head.splitlines() if ':' in line)
    authority, status = fields.get('authority', '').strip(), fields.get('status', '').strip()
    if status != 'open' or not authority:
        msg = f'task {slug} is not open with a user authority (status {status or "none"})'
        raise ValueError(msg)
    return f'{slug}@{authority}'


def slug_of(task: str) -> str:
    """The slug of task id ``<slug>@<authority>``."""
    return task.split('@', 1)[0]


def _binding(start: Path, session: str) -> Path:
    return ledger(start) / BINDINGS / f'{session}.json'


def bind(payload: Mapping[str, Any], *, start: Path | None = None) -> str | None:
    """Bind the payload's session to the task its USER prompt names; the task id bound, or ``None``.

    Only a ``UserPromptSubmit`` payload reaches here: the prompt is the user's, the session id the harness's.
    *start* (default: the payload's ``cwd``) is any path in the repository; the binding lands in its :func:`ledger`.
    """
    session, prompt = str(payload.get('session_id') or ''), str(payload.get('prompt') or '')
    found = BIND_PROMPT.match(prompt)
    if not found or not valid(session):
        return None
    where = Path(str(payload.get('cwd') or '.')) if start is None else start
    try:
        task = task_id(where, found.group(1))
        target = _binding(where, session)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({'session': session, 'task': task}), encoding='utf-8')
    except (ValueError, OSError, subprocess.CalledProcessError):
        return None
    return task


def bound_task(session: str, *, start: Path | None = None) -> str | None:
    """The task id the user bound *session* to in the repository at *start* (default: the cwd), or ``None``."""
    if not valid(session):
        return None
    try:
        record = json.loads(_binding(Path.cwd() if start is None else start, session).read_text(encoding='utf-8'))
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None
    return record.get('task') if isinstance(record, dict) and record.get('session') == session else None


def session_task(env: Mapping[str, str], *, start: Path | None = None) -> str | None:
    """The task id bound to the native session *env* names, or ``None`` (no session, or none bound).

    Raises:
        ValueError: *env* names an invalid or ambiguous native session (:func:`session_of`).

    """
    session = session_of(env)
    return bound_task(session, start=start) if session else None


def head_for(slug: str, feature: str) -> str:
    """The PR head a session bound to task *slug* publishes *feature* on."""
    return f'{PREFIX}{slug}/{feature}'


def under(branch: str, slug: str) -> bool:
    """Whether *branch* is one of task *slug*'s heads, ``pr/<slug>/<feature>`` (never the bare ``pr/<slug>``)."""
    prefix = f'{PREFIX}{slug}/'
    return branch.startswith(prefix) and len(branch) > len(prefix)


def head_advice(head: str, slug: str) -> str | None:
    """What a PR head should be called for a session bound to *slug*, or ``None`` when it already is."""
    if under(head, slug):
        return None
    return (
        f'this session works on task {slug}: its PR heads are {head_for(slug, "<feature>")} -- '
        f'`git branch -m {head} {head_for(slug, head.rsplit("/", 1)[-1])}`'
    )


def _hook(stdin: TextIO) -> int:
    """The ``UserPromptSubmit`` hook: bind on a ``task: <slug>`` prompt; never fails the prompt."""
    try:
        task = bind(json.load(stdin))
    except (ValueError, OSError, AttributeError):
        return 0
    if task:
        slug = slug_of(task)
        emit(f'this session works on task {task}: its branches are {head_for(slug, "<feature>")}')
    return 0


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None) -> int:
    """``bind`` is the prompt hook; ``status`` prints this session's bound task."""
    words = sys.argv[1:] if argv is None else argv
    if words == ['bind']:
        return _hook(stdin or sys.stdin)
    if words == ['status']:
        try:
            task = session_task(os.environ)
        except ValueError as refused:
            emit(str(refused), err=True)
            return 2
        emit(f'task {task}' if task else f'no task bound: {DOOR}')
        return 0
    emit('usage: python -m dev_lab.dev.taskbinding bind|status', err=True)
    return 2


if __name__ == '__main__':
    sys.exit(main())
