"""THE ONE READER of rem's task ledger and session binding; a session's branches derive from its task (D5, 2026-11-15).

REM OWNS THE BINDING, and is its one writer (2026-11-16). A prompt whose FIRST line is ``task: <slug>`` binds the
session receiving it to that OPEN task: rem's one ``UserPromptSubmit`` task hook writes the binding, node only, so no
dev-lab interpreter takes part in a prompt and a stale venv cannot stop one. dev-lab never writes the ledger or a
binding. It reads both here, through the contract rem documents (rem's ``skills/rem/reference/tasks.md``, "The
binding file") and never through rem's code:

* the ledger, :func:`ledger` -- ``<main checkout>/.claude/tasks/``, the parent of ``git rev-parse --git-common-dir``,
  the same from every worktree (W4, 2026-11-16): the working state of the repository, never committed on a branch;
* a task, :func:`task_id` -- ``<slug>/TASK.md`` there, frontmatter ``status: open`` and the ``authority`` the user's
  task-open minted. Its id is ``<slug>@<authority>``, so a task closed and reopened under the same slug is a new id
  and an old binding never carries over;
* a binding, :func:`bound_task` -- ``.bindings/<session>.json`` there,
  ``{"session": ..., "task": "<slug>@<authority>"}``,
  keyed by the session a process inside it names (:func:`~dev_lab.dev.native_session.session_of`:
  ``CLAUDE_CODE_SESSION_ID``, or a Codex session's ``CODEX_THREAD_ID``).

An agent can name a worktree or a branch after a task and can set an environment variable; it cannot author the
user's prompt, so neither of those binds. The task gate (:mod:`dev_lab.dev.taskgate`), the integrator role
(:mod:`dev_lab.dev.hpcaccount.session`) and the branch-name help all read the binding here.

BRANCHES DERIVE FROM THE TASK. A bound session publishes ``pr/<slug>/<feature>`` (:func:`head_for`); a landed PR
ends a feature, never the task, so the next feature is ``pr/<slug>/<next>`` with no new binding. A task never
publishes a bare ``pr/<slug>``: git keeps a ref and the refs below it apart (``refs/heads/pr/<slug>`` is a file,
``refs/heads/pr/<slug>/x`` needs it to be a directory), so the bare branch would refuse every feature of its task.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from lab_commons import launch

from dev_lab.dev.native_session import session_of, valid

__all__ = [
    'BINDINGS',
    'DOOR',
    'PREFIX',
    'bound_task',
    'checkout_root',
    'head_advice',
    'head_for',
    'ledger',
    'session_task',
    'slug_of',
    'task_id',
    'under',
]

#: Where rem writes the session -> task bindings, below the :func:`ledger`.
BINDINGS: Final = '.bindings'
_SLUG: Final = r'[a-z0-9]+(?:-[a-z0-9]+)*'
#: The namespace a task's PR heads live under: ``pr/<slug>/<feature>``.
PREFIX: Final = 'pr/'
#: The one door that binds a session -- rem's -- named by every refusal that finds none.
DOOR: Final = (
    "the user binds this session with a prompt whose first line is `task: <slug>`, which rem's UserPromptSubmit "
    'hook writes as the binding (the rem plugin; an open task -- a new one is opened by the user with '
    '/rem:task open <slug> "<goal>"; rem\'s `task.js status` shows what is bound)'
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


def bound_task(session: str, *, start: Path | None = None) -> str | None:
    """The task id rem bound *session* to in the repository at *start* (default: the cwd), or ``None``."""
    if not valid(session):
        return None
    try:
        where = Path.cwd() if start is None else start
        record = json.loads((ledger(where) / BINDINGS / f'{session}.json').read_text(encoding='utf-8'))
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
