"""RECLAIM RUNS IN THE WORKFLOW: every session start reclaims landed worktrees in the background, never blocking.

User ruling 2026-10-27: cleanup of landed worktrees and branches is PART OF THE WORKFLOW and never blocks
development. MEASURED that day: a consumer carried 101 worktrees and 207 local branches, because the only
automation REPORTED debris and ``branchset --apply`` -- the owner of the deletable decision -- was never run,
being too slow to run inline. So this module decides nothing; it RUNS that owner
(:func:`dev_lab.dev.branchset.apply_local`, which reclaims through :func:`dev_lab.dev.reclaim.reclaim`):

* ``--session-start`` is the ``SessionStart`` hook (:data:`dev_lab.dev.agent_guard.WIRING`): it reads the
  payload's ``cwd``, does nothing unless that is a MAIN checkout (a linked tree is somebody's lease), detaches
  a background run and returns at once;
* a background run has no console, survives its parent, and holds a PER-REPO lock in the git common dir, so a
  second session's run is a no-op; a lock older than :data:`STALE_LOCK_S` is a crashed run's and is taken over;
* each run removes at most :data:`BATCH` trees and writes every line -- removed, kept with its reason (a real
  edit is listed, never deleted), deferred -- to ``output/logs/<yy>/<mm>/<dd>/reclaim/``.

``python -m dev_lab.dev.reclaimrun [--root R] [--batch N] [--background | --session-start]``; always exits 0.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Final, TextIO

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.branchset import BranchSetNotDeclared, apply_local, declared_branchset
from dev_lab.dev.checkout import git_out
from dev_lab.dev.reclaim import QUIET_S

__all__ = ['BATCH', 'LOCK_NAME', 'STALE_LOCK_S', 'detach', 'held', 'main', 'main_checkout', 'run']

#: Trees removed per run at most: a run stays minutes, and the next session start takes the next batch.
BATCH: Final = 10
#: The per-repo lock, in the git COMMON dir every worktree of the repo shares.
LOCK_NAME: Final = 'dev-lab-reclaim.lock'
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


def _common_dir(root: Path) -> Path:
    out = git_out(root, 'rev-parse', '--path-format=absolute', '--git-common-dir')
    return Path((out or '').strip() or root / '.git')


@contextlib.contextmanager
def held(root: Path, *, stale_s: float = STALE_LOCK_S) -> Iterator[bool]:
    """Hold *root*'s reclaim lock for the block; yields ``False`` (and holds nothing) when another run has it."""
    lock = _common_dir(root) / LOCK_NAME
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


def run(
    root: Path,
    *,
    batch: int = BATCH,
    occupied: Callable[[Path], bool] | None = None,
    quiet_s: float = QUIET_S,
) -> Path | None:
    """One locked reclaim of *root*; the log it wrote, or ``None`` when another run holds the lock (a no-op)."""
    with held(root) as mine:
        if not mine:
            return None
        try:
            lines = apply_local(root, declared_branchset(root), occupied=occupied, limit=batch, quiet_s=quiet_s)
        except BranchSetNotDeclared as exc:
            lines = (f'nothing reclaimed: {exc}',)
        now = datetime.now().astimezone()
        log = root / 'output' / 'logs' / now.strftime('%y/%m/%d') / 'reclaim' / f'{now:%H%M%S}-{os.getpid()}.log'
        log.parent.mkdir(parents=True, exist_ok=True)
        body = lines if lines is not None else (f'git could not read the branches of {root}; nothing was deleted',)
        log.write_text('\n'.join(body) + '\n', encoding='utf-8')
        return log


def detach(root: Path, *, batch: int = BATCH) -> None:
    """Start a background :func:`run` of *root* that outlives this process and opens no window."""
    argv = [sys.executable, '-m', 'dev_lab.dev.reclaimrun', '--root', str(root), '--batch', str(batch)]
    quiet = {'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL}
    if sys.platform != 'win32':
        _door.popen(argv, cwd=root, start_new_session=True, **quiet)
        return
    try:
        _door.popen(argv, cwd=root, creationflags=_DETACHED | _BREAKAWAY, **quiet)
    except OSError:  # the job forbids breakaway: still detached from the console and the process group
        _door.popen(argv, cwd=root, creationflags=_DETACHED, **quiet)


def _session_root(stdin: TextIO) -> Path | None:
    try:
        payload = json.load(stdin)
    except ValueError:
        payload = {}
    cwd = (payload if isinstance(payload, dict) else {}).get('cwd') or Path.cwd()
    return main_checkout(Path(cwd))


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None) -> int:
    """Reclaim landed worktrees and their branches: inline, ``--background``, or as the ``--session-start`` hook."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.reclaimrun', description=main.__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd(), help='the main checkout (default: cwd)')
    parser.add_argument('--batch', type=int, default=BATCH, help=f'trees removed per run (default {BATCH})')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--background', action='store_true', help='detach a run and return at once')
    mode.add_argument('--session-start', action='store_true', help='the SessionStart hook: main checkout only')
    args = parser.parse_args(argv)
    try:
        root = _session_root(stdin or sys.stdin) if args.session_start else main_checkout(args.root)
        if root is None:
            return 0
        if args.background or args.session_start:
            detach(root, batch=args.batch)
            return 0
        log = run(root, batch=args.batch)
    except OSError as exc:  # a hook never blocks the session it serves
        emit(f'reclaim did not run: {exc}')
        return 0
    emit(f'reclaim log: {log}' if log else 'reclaim: another run holds the lock; nothing done')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
