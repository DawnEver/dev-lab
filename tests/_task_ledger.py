"""Stand in for the machine's task ledger (:mod:`dev_lab.dev.taskledger`) and the branch that names a task.

The ledger is ONE per machine at a derived path, ``<machine home>/repos/tasks`` (user ruling 2026-11-23), a clone of
the family ``[tasks] remote``; conftest gives each test its own machine home. :func:`plant_ledger` makes that path a
git clone; :func:`open_task` writes a task as the task door's open does; :func:`on_branch` puts a
checkout on a branch, which is the only thing that says which task it works on.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from lab_commons.home import part

from dev_lab.dev.taskledger import LEDGER_DIR

_GIT = shutil.which('git') or 'git'


def plant_ledger() -> Path:
    """Make this machine's derived ledger path a git repository; the path."""
    where = part('repos') / LEDGER_DIR
    where.mkdir(parents=True, exist_ok=True)
    if not (where / '.git').exists():
        subprocess.run([_GIT, 'init', '-q', str(where)], check=True, capture_output=True)
    return where


def open_task(ledger: Path, slug: str, *, authority: str = 'a1', status: str = 'open', extra: str = '') -> str:
    """Write ``<ledger>/<slug>/TASK.md`` as rem's task-open does; the task id ``<slug>@<authority>``."""
    folder = ledger / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'TASK.md').write_text(f'---\nauthority: {authority}\nstatus: {status}\n{extra}---\n', encoding='utf-8')
    return f'{slug}@{authority}'


def on_branch(root: Path, branch: str) -> Path:
    """Make *root* a git checkout (when it is none) whose HEAD is *branch*; *root*."""
    if not (root / '.git').exists():
        subprocess.run([_GIT, 'init', '-q', str(root)], check=True, capture_output=True)
    subprocess.run([_GIT, 'symbolic-ref', 'HEAD', f'refs/heads/{branch}'], cwd=root, check=True, capture_output=True)
    return root
