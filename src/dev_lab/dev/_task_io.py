"""The task ledger's I/O, for :mod:`dev_lab.dev.task`: its refusal, the forge issue, the git commit and the lock.

Split out of :mod:`dev_lab.dev.task` (2026-11-25, MODULE-SIZE-ALARM) along its own seam: that module is the verbs
over a journal; this one is what every verb writes THROUGH -- one commit per write, under one lock.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import os
import re
import shutil
import time
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol

import lab_commons.launch as _door

from dev_lab.dev.labsession import ENV

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = [
    'GIT',
    'LOCK_WAIT_S',
    'Branches',
    'Forge',
    'ForgeIssues',
    'TaskRefused',
    'checkout_branches',
    'commit',
    'git',
    'locked',
    'today',
]

GIT: Final = shutil.which('git') or 'git'
#: How long a verb waits for another verb's ledger lock.
LOCK_WAIT_S: Final = 30.0


class TaskRefused(ValueError):
    """A task verb refused: the message names the cause and the door."""


class Forge(Protocol):
    """A task's identity on the forge: one issue labeled ``task:<slug>`` in the ledger's origin."""

    def open(self, slug: str, goal: str) -> str:
        """Open the issue; its URL."""
        ...

    def close(self, url: str) -> None:
        """Close the issue at *url*."""
        ...


class ForgeIssues:
    """The default :class:`Forge`: dev-lab's forge client for the ledger clone's origin (*client* stands in for it)."""

    def __init__(self, root: Path, *, client: Client | None = None) -> None:
        from dev_lab.dev.forgeclient import client_for  # noqa: PLC0415 -- the network client, only for open/close

        self._client = client if client is not None else client_for(root)

    def open(self, slug: str, goal: str) -> str:
        """The open issue labeled ``task:<slug>`` -- the one already there, else a new one (the label IS the id)."""
        from dev_lab.dev.issuekind import create  # noqa: PLC0415

        if held := self._client.issue_list(state='open', labels=(f'task:{slug}',)):
            return held[0].url
        body = f"The identity of task `{slug}`: the tasks repo's {slug}/ journals it and links here.\n\nGoal: {goal}"
        return create(self._client, f'task: {slug} -- {goal}', body, 'need', [f'task:{slug}']).url

    def close(self, url: str) -> None:
        if (number := re.search(r'/issues/(\d+)/?$', url)) is not None:
            self._client.issue_close(int(number[1]))


class Branches(Protocol):
    """A task's ``pr/<slug>/*`` heads: what blocks its close, and the prune once it is closed."""

    def unmerged(self, slug: str) -> list[str]:
        """One line per head integration does not contain; ``[]`` lets the close run."""
        ...

    def prune(self, slug: str) -> list[str]:
        """Delete every merged head, origin's and local; the lines said."""
        ...


def checkout_branches(cwd: Path) -> Branches:
    """The default :class:`Branches`: *cwd*'s checkout, its forge client and the real fetch."""
    from dev_lab.dev.branchdelete import TaskBranches  # noqa: PLC0415 -- the network client, only for close
    from dev_lab.dev.forge import fetch_origin  # noqa: PLC0415
    from dev_lab.dev.forgeclient import client_for  # noqa: PLC0415

    code, top = git(Path(cwd), 'rev-parse', '--show-toplevel')
    if code != 0:
        msg = f'{Path(cwd).as_posix()} is no git checkout.\nDoor: run task close from the checkout holding pr/<slug>/*'
        raise TaskRefused(msg)
    root = Path(top.strip())
    return TaskBranches(root, client=client_for(root), session=os.environ.get(ENV, ''), fetch=fetch_origin)


def today() -> str:
    return dt.datetime.now(dt.UTC).date().isoformat()


def git(root: Path, *args: str) -> tuple[int, str]:
    done = _door.run([GIT, '-C', str(root), *args], capture_output=True, text=True, encoding='utf-8', check=False)
    return done.returncode, (done.stderr or done.stdout).strip()


def commit(root: Path, message: str, *paths: str) -> None:
    # A path already moved by `git mv` is on neither disk nor index: `add` would refuse it; `commit` records it.
    present = [p for p in paths if (root / p).exists()]
    status, said = git(root, 'add', '-A', '--', *present) if present else (0, '')
    if status == 0:
        status, said = git(root, 'commit', '-q', '-m', message, '--', *paths)
    if status != 0:
        msg = (
            f'the ledger write landed but its commit failed ({said.splitlines()[-1] if said else status}).\n'
            f'Door: git -C {root.as_posix()} commit -m "{message}" -- {" ".join(paths)}'
        )
        raise TaskRefused(msg)


@contextlib.contextmanager
def locked(root: Path) -> Iterator[None]:
    from dev_lab.dev.servelock import held  # noqa: PLC0415

    deadline = time.monotonic() + LOCK_WAIT_S
    while True:
        with held(root / '.git' / 'task.lock') as mine:
            if mine:
                yield
                return
        if time.monotonic() > deadline:
            msg = f'the task ledger {root.as_posix()} stayed locked {LOCK_WAIT_S:g} s by another task verb; retry'
            raise TaskRefused(msg)
        time.sleep(0.02)
