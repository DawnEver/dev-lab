"""THE DOOR that carries a rem task's ledger from one host to another, through the forge (hosts-config #78 item 0).

``.claude/tasks`` is untracked by design and the task guard refuses committing it (D80), and hosts meet only
through the forge, never a direct copy. So the ledger of task ``<slug>`` -- ``TASK.md``, journals, decisions,
everything under ``<ledger>/<slug>/`` (:func:`dev_lab.dev.taskbinding.ledger`) -- travels as ONE ref of its own,
``refs/tasks/<slug>`` on ``origin``: a commit of that directory alone, written through a private index, so no
branch, PR or code index ever holds it. Each carry chains onto the ref origin holds, keeping the ledger's history.

* :func:`carry` -- this host's ledger of *slug* becomes origin's ``refs/tasks/<slug>``;
* :func:`receive` -- origin's ``refs/tasks/<slug>`` becomes this host's ledger of *slug*. A ledger already here is
  never overwritten unasked: ``--replace`` takes the carried one whole.

CLI: ``python -m dev_lab.dev.taskcarry carry|receive <slug> [--replace]``.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from lab_commons import launch
from lab_commons.log import emit

from dev_lab.dev import taskbinding

__all__ = ['REFS', 'CarryRefused', 'carry', 'main', 'receive']

#: The ref namespace a task ledger travels under on origin; one ref per task slug.
REFS: Final = 'refs/tasks/'

_REMOTE: Final = 'origin'
_SLUG: Final = r'[a-z0-9]+(?:-[a-z0-9]+)*'


class CarryRefused(ValueError):
    """A carry or receive that cannot proceed; its message names the cause and the door."""


def _git(cwd: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return launch.run(
        [shutil.which('git') or 'git', *args],
        cwd=cwd, capture_output=True, text=True, encoding='utf-8', check=False, env=env,
    )  # fmt: skip


def _checked(cwd: Path, *args: str, env: dict[str, str] | None = None) -> str:
    done = _git(cwd, *args, env=env)
    if done.returncode != 0:
        msg = f'git {" ".join(args)} failed: {done.stderr.strip()}'
        raise CarryRefused(msg)
    return done.stdout.strip()


def _task_dir(root: Path, slug: str) -> Path:
    if not re.fullmatch(_SLUG, slug):
        msg = f'{slug!r} is not a task slug (lowercase words joined by -); name the task as rem opened it'
        raise CarryRefused(msg)
    return taskbinding.ledger(root) / slug


def _ref(slug: str) -> str:
    return f'{REFS}{slug}'


def _fetched(root: Path, slug: str) -> str | None:
    """The commit origin holds at ``refs/tasks/<slug>``, fetched here; None when origin holds none."""
    listed = _checked(root, 'ls-remote', _REMOTE, _ref(slug))
    if not listed:
        return None
    _checked(root, 'fetch', '-q', _REMOTE, f'+{_ref(slug)}:{_ref(slug)}')
    return listed.split()[0]


def _private_index(work: Path, index: Path) -> dict[str, str]:
    """An environment whose index and work tree are the ledger's own, so the code index is never touched."""
    return {**os.environ, 'GIT_INDEX_FILE': str(index), 'GIT_WORK_TREE': str(work)}


def carry(root: Path, slug: str) -> str:
    """Publish the ledger of *slug* at *root* as origin's ``refs/tasks/<slug>``; the commit sha carried."""
    task = _task_dir(root, slug)
    if not (task / 'TASK.md').is_file():
        msg = f'no task {slug} in the ledger {task.parent.as_posix()}: open it with rem task-open, or receive it'
        raise CarryRefused(msg)
    parent = _fetched(root, slug)
    with tempfile.TemporaryDirectory() as scratch:
        env = _private_index(task, Path(scratch) / 'index')
        _checked(task, 'add', '-A', '-f', '.', env=env)
        tree = _checked(task, 'write-tree', env=env)
    if parent is not None and _checked(root, 'rev-parse', f'{parent}^{{tree}}') == tree:
        return parent
    made = ['commit-tree', tree, '-m', f'task ledger {slug}', *(['-p', parent] if parent else [])]
    sha = _checked(root, *made)
    _checked(root, 'push', '-q', _REMOTE, f'{sha}:{_ref(slug)}')
    return sha


def receive(root: Path, slug: str, *, replace: bool = False) -> str:
    """Make origin's ``refs/tasks/<slug>`` the ledger of *slug* at *root*; the commit sha received."""
    task = _task_dir(root, slug)
    sha = _fetched(root, slug)
    if sha is None:
        msg = f'origin holds no {_ref(slug)}: carry {slug} from the host that holds its ledger first'
        raise CarryRefused(msg)
    if task.exists():
        if not replace:
            msg = (
                f'the ledger {task.as_posix()} already exists here and would be overwritten: '
                f'carry {slug} from this host first to keep its entries, or receive --replace to take the carried one'
            )
            raise CarryRefused(msg)
        shutil.rmtree(task)
    task.mkdir(parents=True)
    with tempfile.TemporaryDirectory() as scratch:
        env = _private_index(task, Path(scratch) / 'index')
        _checked(task, 'read-tree', sha, env=env)
        _checked(task, 'checkout-index', '-a', '-f', env=env)
    return sha


def main(argv: Sequence[str] | None = None) -> int:
    """``carry|receive <slug> [--replace]``: 0 with the sha moved, 1 with the refusal's cause and door."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.taskcarry', description=__doc__.splitlines()[0])
    parser.add_argument('verb', choices=('carry', 'receive'))
    parser.add_argument('slug')
    parser.add_argument('--replace', action='store_true', help='receive: take the carried ledger over a local one')
    args = parser.parse_args(argv)
    root = Path.cwd()
    try:
        sha = carry(root, args.slug) if args.verb == 'carry' else receive(root, args.slug, replace=args.replace)
    except CarryRefused as refused:
        emit(f'TASK-CARRY: {refused}', err=True)
        return 1
    emit(f'[taskcarry] {args.verb} {args.slug}: {_ref(args.slug)} at {sha[:12]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
