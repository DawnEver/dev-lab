"""RECLAIM RUNS IN THE WORKFLOW: every session start reclaims landed worktrees in the background, never blocking.

User ruling 2026-10-27: cleanup of landed worktrees and branches is PART OF THE WORKFLOW and never blocks
development. MEASURED that day: a consumer carried 101 worktrees and 207 local branches, because the only
automation REPORTED debris and ``branchset --apply`` -- the owner of the deletable decision -- was never run,
being too slow to run inline. So this module decides nothing; it RUNS that owner
(:func:`dev_lab.dev.branchset.apply_local`, which reclaims through :func:`dev_lab.dev.reclaim.reclaim`):

* ``--session-start`` is the ``SessionStart`` hook (:data:`dev_lab.dev.agent_wiring.WIRING`): it reads the
  payload's ``cwd``, does nothing unless that is a MAIN checkout (a linked tree is somebody's lease), detaches
  a background run and returns at once;
* ``--background`` is the git hook's door (``githooks/base.toml``: ``post-merge``, user ruling 2026-11-12; a tree
  becomes reclaimable when its branch lands, which a checkout learns when it takes in upstream): from ANY tree of
  the repo it detaches a run of the MAIN checkout and returns at once, exit 0 whatever happens, so it never delays
  or fails the merge;
* a background run has no console, survives its parent, and holds a PER-REPO lock in the git common dir, so a
  second session's run is a no-op; a lock older than :data:`STALE_LOCK_S` is a crashed run's and is taken over;
* each run removes at most :data:`BATCH` trees and writes every line -- removed, kept with its reason (a real
  edit is listed, never deleted), deferred -- to ``output/logs/<yy>/<mm>/<dd>/reclaim/``.

``python -m dev_lab.dev.reclaimrun [--root R] [--batch N] [--background | --session-start]``; always exits 0.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Final, TextIO

from lab_commons.log import emit

from dev_lab.dev.backgroundrun import detach_argv, held, main_checkout, repo_main
from dev_lab.dev.branchset import BranchSetNotDeclared, apply_local, declared_branchset
from dev_lab.dev.checkout import worktrees
from dev_lab.dev.reclaim import QUIET_S
from dev_lab.dev.venvcurrent import reclaim as reclaim_envs

__all__ = ['BATCH', 'detach', 'main', 'run']

#: Trees removed per run at most: a run stays minutes, and the next session start takes the next batch.
BATCH: Final = 10


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
        lines = (*lines, *_envs(root)) if lines is not None else None
        now = datetime.now().astimezone()
        log = root / 'output' / 'logs' / now.strftime('%y/%m/%d') / 'reclaim' / f'{now:%H%M%S}-{os.getpid()}.log'
        log.parent.mkdir(parents=True, exist_ok=True)
        body = lines if lines is not None else (f'git could not read the branches of {root}; nothing was deleted',)
        log.write_text('\n'.join(body) + '\n', encoding='utf-8')
        return log


def _envs(root: Path) -> tuple[str, ...]:
    """Old environments nothing executes from, reclaimed in every checkout of *root* (dev-lab #632)."""
    trees = worktrees(root) or ()
    out: list[str] = []
    for tree in dict.fromkeys((root, *(path for path, _branch in trees))):
        try:
            out.extend(reclaim_envs(tree))
        except OSError as exc:
            out.append(f'environments of {tree} not reclaimed: {exc}')
    return tuple(out)


def detach(root: Path, *, batch: int = BATCH) -> None:
    """Start a background :func:`run` of *root* that outlives this process and opens no window."""
    detach_argv(root, ['-m', 'dev_lab.dev.reclaimrun', '--root', str(root), '--batch', str(batch)])


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
        if args.session_start or args.background:
            root = _session_root(stdin or sys.stdin) if args.session_start else repo_main(args.root)
            if root is not None:
                detach(root, batch=args.batch)
            return 0
        root = main_checkout(args.root)
        if root is None:
            return 0
        log = run(root, batch=args.batch)
    except OSError as exc:  # a hook never blocks the session it serves
        emit(f'reclaim did not run: {exc}')
        return 0
    emit(f'reclaim log: {log}' if log else 'reclaim: another run holds the lock; nothing done')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
