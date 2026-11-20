"""THE ONE READER of rem's task ledger and session binding; a session's branches derive from its task (D5, 2026-11-15).

REM OWNS THE BINDING, and is its one writer (2026-11-16). A prompt whose FIRST line is ``task: <slug>`` binds the
session receiving it to that OPEN task: rem's one ``UserPromptSubmit`` task hook writes the binding, node only, so no
dev-lab interpreter takes part in a prompt and a stale venv cannot stop one. dev-lab never writes the ledger or a
binding. It reads both here, through the contract rem documents (rem's ``skills/rem/reference/tasks.md``, "The
binding file") and never through rem's code:

* the ledger, :func:`ledger` -- ``<main checkout>/.claude/tasks/``, the parent of ``git rev-parse --git-common-dir``,
  the same from every worktree (W4, 2026-11-16): the working state of the repository, never committed on a branch;
* a task, :func:`task_id` / :func:`task_in` -- ``<slug>/TASK.md`` there, frontmatter ``status: open`` and the
  ``authority`` the user's task-open minted. Its id is ``<slug>@<authority>``, so a task closed and reopened under
  the same slug is a new id and an old binding never carries over;
* a binding, :func:`binding` -- PER SESSION, not per repo (user ruling D34, 2026-11-17): ONE file
  ``<machine home>/state/sessions/<session>.json`` (:func:`binding_path`; the home is lab_commons'), =
  ``{"session": ..., "task": "<slug>@<authority>", "ledger": {"repo_key": ..., "path": <ledger dir>}}``,
  keyed by the session a process inside it names (:func:`~dev_lab.dev.native_session.session_of`:
  ``CLAUDE_CODE_SESSION_ID``, ``CODEX_THREAD_ID``, or ``ANTIGRAVITY_CONVERSATION_ID``). Every repo's push check reads
  that one file, so a session bound from repo A pushes from repo B under its task, judged open in the ledger the record
  names. The retired per-repo store ``<ledger>/.bindings/<session>.json`` is never read: a record still found there
  is refused by name with its one-shot migration (:data:`MIGRATE_DOOR`; FORMATS-MIGRATE-ONCE).

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
from typing import Final, NamedTuple

from lab_commons import launch
from lab_commons.home import part

from dev_lab.dev.native_session import session_of, valid

__all__ = [
    'DOOR',
    'MIGRATE_DOOR',
    'PREFIX',
    'RETIRED_BINDINGS',
    'SESSIONS',
    'Binding',
    'UnmigratedBindingError',
    'binding',
    'binding_path',
    'bound_task',
    'checkout_root',
    'head_advice',
    'head_for',
    'ledger',
    'session_binding',
    'session_task',
    'slug_of',
    'task_id',
    'task_in',
    'under',
]

#: The directory of the machine home's ``state`` part rem writes every session's binding into (D34).
SESSIONS: Final = 'sessions'
#: The retired per-repo binding store below a :func:`ledger`: never read; a record still there is refused.
RETIRED_BINDINGS: Final = '.bindings'
#: The one-shot migration of the retired store -- rem's, since rem is the binding's one writer.
MIGRATE_DOOR: Final = (
    "move it once with rem's migration -- the /migrate skill, or node <rem plugin>/migrations/migrate.mjs "
    '<main checkout> -- which moves every record of that store into the session store and deletes it'
)
_SLUG: Final = r'[a-z0-9]+(?:-[a-z0-9]+)*'
#: The namespace a task's PR heads live under: ``pr/<slug>/<feature>``.
PREFIX: Final = 'pr/'
#: The one door that binds a session -- rem's -- named by every refusal that finds none.
DOOR: Final = (
    "the user binds this session with a prompt whose first line is `task: <slug>`, which rem's UserPromptSubmit "
    'hook writes as the binding (the rem plugin; an open task -- a new one is opened by the user with '
    '/rem:task open <slug> "<goal>"; rem\'s `task.js status` shows what is bound; rem finds the machine home in '
    'LAB_COMMONS_HOME, which `python -m dev_lab.dev.remhome --install` sets)'
)


class Binding(NamedTuple):
    """One session's binding as rem wrote it: its task id, the ledger that task lives in, and the file read."""

    task: str
    ledger: Path
    path: Path


class UnmigratedBindingError(ValueError):
    """A session's binding is still in the retired per-repo store and not in the session store."""


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
    try:
        where = ledger(start)
    except (OSError, subprocess.CalledProcessError):
        msg = f'no task {slug} in the ledger of {Path(start).as_posix()}'
        raise ValueError(msg) from None
    return task_in(where, slug)


def task_in(tasks: Path, slug: str) -> str:
    """The id ``<slug>@<authority>`` of the OPEN task *slug* in the ledger directory *tasks*; ValueError otherwise."""
    if not re.fullmatch(_SLUG, slug):
        msg = f'{slug!r} is not a task slug'
        raise ValueError(msg)
    try:
        head = (tasks / slug / 'TASK.md').read_text(encoding='utf-8').split('---')[1]
    except (OSError, IndexError):
        msg = f'no task {slug} in the ledger {tasks.as_posix()}'
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


def binding_path(session: str) -> Path:
    """THE ONE PATH of *session*'s binding, for every repo: ``<machine home>/state/sessions/<session>.json``."""
    return part('state') / SESSIONS / f'{session}.json'


def _refuse_retired(session: str, start: Path | None) -> None:
    try:
        old = ledger(Path.cwd() if start is None else start) / RETIRED_BINDINGS / f'{session}.json'
    except (OSError, subprocess.CalledProcessError):
        return
    if old.is_file():
        msg = (
            f'session {session} is bound only in the retired per-repo store {old.as_posix()}; the one store '
            f'every repo reads is {binding_path(session).as_posix()} (D34), which holds none.\n'
            f'Door: {MIGRATE_DOOR}'
        )
        raise UnmigratedBindingError(msg)


def _parsed(record: object, session: str, path: Path) -> Binding | None:
    if not isinstance(record, dict) or record.get('session') != session:
        return None
    task, where = record.get('task'), record.get('ledger')
    tasks = where.get('path') if isinstance(where, dict) else None
    if not isinstance(task, str) or not isinstance(tasks, str):
        return None
    return Binding(task, Path(tasks), path)


def binding(session: str, *, start: Path | None = None) -> Binding | None:
    """*session*'s binding read from :func:`binding_path`, or ``None`` when none is written or it is malformed.

    Raises:
        UnmigratedBindingError: none is written, and the repository at *start* (default: the cwd) still holds the
            session's record in the retired per-repo store.

    """
    if not valid(session):
        return None
    path = binding_path(session)
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        _refuse_retired(session, start)
        return None
    except (OSError, ValueError):
        return None
    return _parsed(record, session, path)


def bound_task(session: str, *, start: Path | None = None) -> str | None:
    """The task id rem bound *session* to (:func:`binding`), or ``None``; raises as :func:`binding` does."""
    found = binding(session, start=start)
    return None if found is None else found.task


def session_binding(env: Mapping[str, str], *, start: Path | None = None) -> Binding | None:
    """The binding of the native session *env* names, or ``None`` (no session, or none bound).

    Raises:
        ValueError: *env* names an invalid or ambiguous native session (:func:`session_of`), or its binding is
            unmigrated (:class:`UnmigratedBindingError`).

    """
    session = session_of(env)
    return binding(session, start=start) if session else None


def session_task(env: Mapping[str, str], *, start: Path | None = None) -> str | None:
    """The task id bound to the native session *env* names, or ``None``; raises as :func:`session_binding` does."""
    found = session_binding(env, start=start)
    return None if found is None else found.task


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
