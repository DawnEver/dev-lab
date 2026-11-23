"""THE ONE READER of rem's task ledger, and of which task a checkout works on: its branch's (user ruling 2026-11-23).

* the ledger, :func:`ledger` -- ONE per machine, for every repo, at ONE family default derived on every host: the
  machine home's ``repos`` part, ``<machine home>/repos/tasks`` (:data:`LEDGER_DIR`; inside the declared write roots,
  never a checkout's sibling, never temp). It is a clone of the family layer's ``[tasks] remote`` (the one place the
  remote is stated, rendered into the machine file). A task lives at ``<ledger>/<slug>/`` and a closed one under
  ``<ledger>/archive/<YYYY-MM-DD>/<slug>/`` (rem moves it); its identity on the forge is the issue labelled
  ``task:<slug>``. No checkout holds a ledger;
* a task, :func:`task_in` -- ``<slug>/TASK.md`` there, frontmatter ``status: open`` and the ``authority`` the user's
  task-open minted. Its id is ``<slug>@<authority>``, so a task closed and reopened under the same slug is a new id;
* the task a checkout works on, :func:`task_of` -- DERIVED FROM ITS BRANCH and nothing else: the current HEAD of
  the checkout at a cwd, ``pr/<slug>/<feature>`` (:func:`head_for`), names task ``<slug>``, which must be open in the
  ledger. There is NO binding store: the retired per-session records under ``<machine home>/state/sessions/`` are
  never read (rem's one-shot ``node <rem plugin>/migrations/migrate.mjs`` deletes them).

A landed PR ends a feature, never the task, so the next feature is ``pr/<slug>/<next>``. A task never publishes a bare
``pr/<slug>``: git keeps a ref and the refs below it apart (``refs/heads/pr/<slug>`` is a file,
``refs/heads/pr/<slug>/x`` needs it to be a directory), so the bare branch would refuse every feature of its task.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Final

from lab_commons import config as machineconfig
from lab_commons import launch
from lab_commons.home import part

__all__ = [
    'DOOR',
    'LEDGER_DIR',
    'LEDGER_TABLE',
    'PREFIX',
    'LedgerUnresolvedError',
    'branch_of',
    'head_advice',
    'head_for',
    'ledger',
    'slug_of',
    'slug_on',
    'task_in',
    'task_of',
    'under',
]

#: The family table stating the ledger's remote once: ``[tasks] remote = "<url>"``.
LEDGER_TABLE: Final = 'tasks'
#: The ledger's directory below the machine home's ``repos`` part.
LEDGER_DIR: Final = 'tasks'
_SLUG: Final = r'[a-z0-9]+(?:-[a-z0-9]+)*'
#: The namespace a task's PR heads live under: ``pr/<slug>/<feature>``.
PREFIX: Final = 'pr/'
#: The one door to working on a task, named by every refusal that finds none.
DOOR: Final = (
    'work on a branch pr/<slug>/<feature> of a task open in the task ledger (`git switch -c pr/<slug>/<feature>`, '
    'or a worktree on one); a new task is opened by the user (/rem:task open <slug> "<goal>" until the dev-lab '
    'task door replaces it)'
)


class LedgerUnresolvedError(LookupError):
    """The machine's task ledger is not a git clone at its derived path."""


def ledger() -> Path:
    """THE ONE RESOLVER: this machine's task ledger, ``<machine home>/repos/tasks`` -- a clone of ``[tasks] remote``.

    Raises:
        LedgerUnresolvedError: the path is not a git clone; the refusal names the clone that makes it one.

    """
    found = part('repos') / LEDGER_DIR
    if (found / '.git').exists():
        return found
    table = machineconfig.machine().get(LEDGER_TABLE)
    remote = table.get('remote') if isinstance(table, dict) else None
    source = remote if isinstance(remote, str) and remote else f'<the family [{LEDGER_TABLE}] remote>'
    msg = f'the task ledger {found.as_posix()} is not a git clone.\nDoor: git clone {source} {found.as_posix()}'
    raise LedgerUnresolvedError(msg)


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


def slug_on(branch: str | None) -> str | None:
    """The task slug a branch ``pr/<slug>/<feature>`` names, else ``None`` (any other branch, or detached)."""
    if not branch or not branch.startswith(PREFIX):
        return None
    slug, _, feature = branch[len(PREFIX) :].partition('/')
    return slug if feature and re.fullmatch(_SLUG, slug) else None


def branch_of(cwd: Path) -> str | None:
    """The branch checked out at *cwd* (its worktree's HEAD), or ``None`` when detached or not in git."""
    try:
        done = launch.run(
            [shutil.which('git') or 'git', 'symbolic-ref', '--quiet', '--short', 'HEAD'],
            cwd=cwd, capture_output=True, text=True, encoding='utf-8', check=False,
        )  # fmt: skip
    except OSError:
        return None
    return done.stdout.strip() or None if done.returncode == 0 else None


def task_of(cwd: Path) -> str | None:
    """The id of the task the checkout at *cwd* works on -- its branch's -- or ``None`` on no task branch.

    Raises:
        ValueError: the branch names a task that is not open in the ledger.
        LedgerUnresolvedError: the branch names a task and no ledger resolves (:func:`ledger`).

    """
    slug = slug_on(branch_of(cwd))
    return None if slug is None else task_in(ledger(), slug)


def head_for(slug: str, feature: str) -> str:
    """The PR head a checkout working on task *slug* publishes *feature* on."""
    return f'{PREFIX}{slug}/{feature}'


def under(branch: str, slug: str) -> bool:
    """Whether *branch* is one of task *slug*'s heads, ``pr/<slug>/<feature>`` (never the bare ``pr/<slug>``)."""
    prefix = f'{PREFIX}{slug}/'
    return branch.startswith(prefix) and len(branch) > len(prefix)


def head_advice(head: str, slug: str) -> str | None:
    """What a PR head should be called for a checkout working on *slug*, or ``None`` when it already is."""
    if under(head, slug):
        return None
    return (
        f'this checkout works on task {slug}: its PR heads are {head_for(slug, "<feature>")} -- '
        f'`git branch -m {head} {head_for(slug, head.rsplit("/", 1)[-1])}`'
    )
