"""The LOCAL WORKTREE CLEANUP DOOR: ``python -m dev_lab.dev.worktrees [--root R] [--prune]``.

User rulings 2026-10-04 (AUTO-MODE-RUNS-THE-DOORS): local cleanup is a checked door an agent may run
unattended and nothing here pushes or touches origin. User ruling 2026-10-25: the work is what git TRACKS;
everything else (scratch, untracked, ignored) goes with the tree, its run outputs moved home first.
``--archive NAME`` is the
step before a deliberate removal (:mod:`dev_lab.dev.worktree_archive`): it moves the tree's outputs home,
saves its work, and reports whether removing it loses anything -- it removes nothing itself.

THE INCIDENT IT ENCODES (a consumer, 2026-10-04): a cleanup loop ran ``mkdir -p "$D" && mv output "$D"``
and then ``; git worktree remove --force``. The archive helper failed, ``mv`` never ran, and the ``;``
let the removal delete five worktrees' ignored ``output/``. So:

* a worktree is a LEASE on a branch for one task, and the decision is ONE function,
  :func:`dev_lab.dev.reclaim.reclaimable`: a linked tree goes only when it is unlocked, no TRACKED file is
  changed (staged or not), its content is LANDED on the trunk or a declared session (``git cherry``, or a
  squash merge whose origin ref is gone) and no process occupies it. Its outputs are moved home and VERIFIED,
  and only then -- chained, never after a ``;`` -- ``git worktree remove --force``; its branch then goes
  through ``branchset --apply``.
* a directory under ``.claude/worktrees/`` that git does not register: outputs home, verified, then deleted.
* run it from the SessionStart/Stop debris hook: it prints what it removed and every kept tree with its reason.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from lab_commons.log import emit

from dev_lab.dev.branchset import BranchSetNotDeclared, apply_local, declared_branchset, holders
from dev_lab.dev.checkout import authority_for, worktrees
from dev_lab.dev.reclaim import blockers, reclaim
from dev_lab.dev.worktree_archive import archive

__all__ = ['blockers', 'main', 'prune']


def prune(root: Path, *, apply: bool, occupied: Callable[[Path], bool] | None = None) -> tuple[str, ...] | None:
    """One line per linked worktree and orphan directory; with *apply*, reclaim them. ``None``: unreadable.

    The decision is :func:`dev_lab.dev.reclaim.reclaimable`. In a repo that declares its branch set the
    holders are its trunk and sessions, and *apply* runs :func:`dev_lab.dev.branchset.apply_local`, so a
    reclaimed tree's branch goes with it; otherwise the one holder is the main checkout's branch on origin.
    """
    try:
        branchset = declared_branchset(root)
    except BranchSetNotDeclared:
        trees = worktrees(root)
        if not trees:
            return None
        return reclaim(root, (authority_for(root, trees[0][1]),), occupied=occupied, apply=apply)
    if apply:
        return apply_local(root, branchset, occupied=occupied)
    return reclaim(root, holders(root, branchset), occupied=occupied, apply=False)


def main(argv: list[str] | None = None) -> int:
    """List worktrees and leftovers; ``--prune`` removes the clean ones. Exit 1 on a failure, 2 when unread."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.worktrees', description=main.__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument(
        '--prune',
        action='store_true',
        help='reclaim landed, unoccupied worktrees with no tracked change (outputs moved home first); never origin',
    )
    parser.add_argument(
        '--archive',
        action='append',
        default=[],
        metavar='NAME',
        help='move the outputs of worktree NAME home and save its work (worktree_archive); removes nothing',
    )
    args = parser.parse_args(argv)
    if args.archive:
        done = [archive(args.root.resolve(), name) for name in args.archive]
        for line in (line for one in done for line in one.lines()):
            emit(line)
        return 0 if all(one.safe for one in done) else 1
    lines = prune(args.root.resolve(), apply=args.prune)
    if lines is None:
        emit(f'git could not read the worktrees of {args.root}; nothing was touched')
        return 2
    for line in lines:
        emit(line)
    return 1 if any(line.startswith('FAILED') for line in lines) else 0


if __name__ == '__main__':
    raise SystemExit(main())
