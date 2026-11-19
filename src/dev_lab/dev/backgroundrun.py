"""A BACKGROUND RUN: a detached interpreter, a per-repo lock, and the checkout it runs for.

The library the background hooks share (dev-lab #640: a hook imports no sibling hook's internals). The reclaim
(:mod:`dev_lab.dev.reclaimrun`), the shell reaper, the venv follower, the PR watcher and the landed-branch sweep each
detach a run that outlives the hook and opens no window, and serialize it on a lock in the repo's git COMMON dir,
which every worktree of the repo shares.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import lab_commons.launch as _door

from dev_lab.dev.checkout import git_out, worktrees
from dev_lab.dev.venvpointer import current_interpreter

__all__ = ['RECLAIM_LOCK', 'STALE_LOCK_S', 'common_dir', 'detach_argv', 'held', 'main_checkout', 'repo_main']

#: The per-repo reclaim lock: the reclaim and an approved branch delete serialize on it.
RECLAIM_LOCK: Final = 'dev-lab-reclaim.lock'
#: A lock this old belongs to a run that died; the next run takes it over.
STALE_LOCK_S: Final = 6 * 3600.0
#: Windows: no console window, its own process group, out of the hook runner's job (``subprocess`` names).
_DETACHED: Final = 0x08000000 | 0x00000200
_BREAKAWAY: Final = 0x01000000


def main_checkout(cwd: Path) -> Path | None:
    """The top of the MAIN checkout *cwd* lies in; ``None`` in a linked worktree or outside git."""
    out = git_out(cwd, 'rev-parse', '--path-format=absolute', '--git-dir', '--git-common-dir', '--show-toplevel')
    match (out or '').splitlines():
        case [git_dir, common, top] if Path(git_dir).resolve() == Path(common).resolve():
            return Path(top).resolve()
        case _:
            return None


def repo_main(cwd: Path) -> Path | None:
    """The MAIN checkout of the repository *cwd* lies in, from any of its trees; ``None`` outside git."""
    trees = worktrees(cwd) if cwd.is_dir() else None
    return trees[0][0].resolve() if trees else None


def common_dir(root: Path) -> Path:
    """*root*'s git COMMON dir, the one every worktree of the repo shares (where its per-repo locks live)."""
    out = git_out(root, 'rev-parse', '--path-format=absolute', '--git-common-dir')
    return Path((out or '').strip() or root / '.git')


@contextlib.contextmanager
def held(
    root: Path, *, name: str = RECLAIM_LOCK, stale_s: float = STALE_LOCK_S, at: Path | None = None
) -> Iterator[bool]:
    """Hold *root*'s lock *name* for the block; yields ``False`` (and holds nothing) when another run has it.

    *at* is the lock file itself, for a lock that belongs to one checkout rather than to the repository.
    """
    lock = at or common_dir(root) / name
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            with contextlib.suppress(OSError):
                if time.time() - lock.stat().st_mtime > stale_s:
                    lock.unlink()
                    continue
            yield False
            return
        os.write(fd, f'{os.getpid()}\n'.encode())
        os.close(fd)
        try:
            yield True
        finally:
            lock.unlink(missing_ok=True)
        return
    yield False


def detach_argv(root: Path, args: list[str]) -> None:
    """Start this interpreter with *args* in *root*, outliving this process and opening no window.

    This interpreter as its checkout's CURRENT environment has it (:func:`dev_lab.dev.venvpointer.current_interpreter`):
    a run detached by a process from a legacy ``.venv`` or an older ``.venvs/<name>`` never holds that one again.
    """
    argv = [current_interpreter(), *args]
    quiet = {'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL}
    if sys.platform != 'win32':
        _door.popen(argv, cwd=root, start_new_session=True, **quiet)
        return
    try:
        _door.popen(argv, cwd=root, creationflags=_DETACHED | _BREAKAWAY, **quiet)
    except OSError:  # the job forbids breakaway: still detached from the console and the process group
        _door.popen(argv, cwd=root, creationflags=_DETACHED, **quiet)
