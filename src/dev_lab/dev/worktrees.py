"""The LOCAL WORKTREE CLEANUP DOOR: ``python -m dev_lab.dev.worktrees [--root R] [--prune]``.

User rulings 2026-10-04 (AUTO-MODE-RUNS-THE-DOORS): local cleanup is a checked door an agent may run
unattended and nothing here pushes or touches origin. User ruling 2026-10-25: the work is what git TRACKS;
everything else (scratch, untracked, ignored) goes with the tree. User ruling 2026-11-09: run outputs route to the
main checkout, so a tree holding any is a writer defect, kept and named; ``--home-outputs NAME`` is the deliberate
keep, moving that tree's outputs home, verified, before it goes.
``--archive NAME`` is the
step before a deliberate removal (:mod:`dev_lab.dev.worktree_archive`): it moves the tree's outputs home,
saves its work, and reports whether removing it loses anything -- it removes nothing itself.

A THROWAWAY CHECKOUT (2026-11-10, a consumer, three times in one day: a detached base tree made to diff tests
against was kept by reclaim as ``not landed`` and refused to ``git worktree remove``, so each needed the user):
``--scratch NAME SHA`` makes it DETACHED under the worktree home and declares it DISPOSABLE; ``--discard NAME``
removes it now (:func:`dev_lab.dev.reclaim.discard`), and ``--prune`` once it is quiet. Disposable means its
untracked content is scratch and it waits for no landing -- never that a tracked change, a commit no ref holds,
a lock or a live process may go with it.

THE INCIDENT IT ENCODES (a consumer, 2026-10-04): a cleanup loop ran ``mkdir -p "$D" && mv output "$D"``
and then ``; git worktree remove --force``. The archive helper failed, ``mv`` never ran, and the ``;``
let the removal delete five worktrees' ignored ``output/``. So:

* a worktree is a LEASE on a branch for one task, and the decision is ONE function,
  :func:`dev_lab.dev.reclaim.reclaimable`: a linked tree goes only when it is unlocked, no TRACKED file is
  changed (staged or not), its content is LANDED on the trunk or a declared session (``git cherry``, or a
  squash merge whose origin ref is gone) and no process occupies it. With no run outputs it is deleted and
  pruned; a named ``--home-outputs`` tree has them moved home and VERIFIED first -- chained, never after a
  ``;``; its branch then goes through ``branchset --apply``.
* a directory under ``.claude/worktrees/`` that git does not register: judged the same way, then deleted.
* every main-checkout session start runs it in the background (:mod:`dev_lab.dev.reclaimrun`), logged.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from lab_commons.log import emit

from dev_lab.dev.branchset import BranchSetNotDeclared, apply_local, declared_branchset, holders
from dev_lab.dev.checkout import authority_for, worktrees
from dev_lab.dev.reclaim import blockers, discard, reclaim, scratch
from dev_lab.dev.worktree_archive import archive

__all__ = ['blockers', 'main', 'prune']


def prune(
    root: Path,
    *,
    apply: bool,
    occupied: Callable[[Path], bool] | None = None,
    move_home: frozenset[str] = frozenset(),
) -> tuple[str, ...] | None:
    """One line per linked worktree and orphan directory; with *apply*, reclaim them. ``None``: unreadable.

    *move_home* names the trees whose run outputs move home before they go (:func:`dev_lab.dev.reclaim.reclaim`).

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
        return reclaim(root, (authority_for(root, trees[0][1]),), occupied=occupied, apply=apply, move_home=move_home)
    if apply:
        return apply_local(root, branchset, occupied=occupied, move_home=move_home)
    return reclaim(root, holders(root, branchset), occupied=occupied, apply=False)


def main(argv: list[str] | None = None) -> int:
    """List worktrees and leftovers; ``--prune`` removes the clean ones. Exit 1 on a failure, 2 when unread."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.worktrees', description=main.__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument(
        '--prune',
        action='store_true',
        help='reclaim landed, unoccupied worktrees with no tracked change and no run outputs; never origin',
    )
    parser.add_argument(
        '--home-outputs',
        action='append',
        default=[],
        metavar='NAME',
        help='with --prune: move the run outputs of worktree NAME home, verified, then reclaim it',
    )
    parser.add_argument(
        '--archive',
        action='append',
        default=[],
        metavar='NAME',
        help='move the outputs of worktree NAME home and save its work (worktree_archive); removes nothing',
    )
    parser.add_argument(
        '--scratch',
        nargs=2,
        metavar=('NAME', 'SHA'),
        help='make a DETACHED throwaway worktree NAME at SHA under the worktree home, declared disposable',
    )
    parser.add_argument(
        '--discard',
        action='append',
        default=[],
        metavar='NAME',
        help='remove the disposable worktree NAME now (made by --scratch; refused with tracked work or a process)',
    )
    args = parser.parse_args(argv)
    if args.scratch or args.discard:
        made = [scratch(args.root.resolve(), *args.scratch)] if args.scratch else []
        lines = made + [discard(args.root.resolve(), name) for name in args.discard]
        for line in lines:
            emit(line)
        return 1 if any(not line.startswith(('made', 'removed')) for line in lines) else 0
    if args.archive:
        done = [archive(args.root.resolve(), name) for name in args.archive]
        for line in (line for one in done for line in one.lines()):
            emit(line)
        return 0 if all(one.safe for one in done) else 1
    lines = prune(args.root.resolve(), apply=args.prune, move_home=frozenset(args.home_outputs))
    if lines is None:
        emit(f'git could not read the worktrees of {args.root}; nothing was touched')
        return 2
    for line in lines:
        emit(line)
    return 1 if any(line.startswith('FAILED') for line in lines) else 0


if __name__ == '__main__':
    raise SystemExit(main())
