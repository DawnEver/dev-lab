"""The LOCAL WORKTREE CLEANUP DOOR: ``python -m dev_lab.dev.worktrees [--root R] [--prune]``.

User rulings 2026-10-04 (AUTO-MODE-RUNS-THE-DOORS): local cleanup is a checked door an agent may run
unattended and nothing here pushes or touches origin. User ruling 2026-10-25: the work is what git TRACKS;
everything else (scratch, untracked, ignored) goes with the tree. User ruling 2026-11-12: reclaiming useless trees
is a REQUIRED part of the workflow, so a reclaimable tree's run outputs move home, verified, before it goes.
``--archive NAME`` is the
step before a deliberate removal (:mod:`dev_lab.dev.worktree_archive`): it moves the tree's outputs home,
saves its work, and reports whether removing it loses anything -- it removes nothing itself. ``--remove NAME``
(:func:`remove`) is that removal, the ONE door for an archived tree on a branch or DETACHED (wall 2026-11-17: the
archive verdict named the raw git removal RECURSIVE-DELETE refuses, and ``branchset --discard`` takes a branch).

THE INCIDENT IT ENCODES (a consumer, 2026-10-04): a cleanup loop ran ``mkdir -p "$D" && mv output "$D"``
and then ``; git worktree remove --force``. The archive helper failed, ``mv`` never ran, and the ``;``
let the removal delete five worktrees' ignored ``output/``. So:

* a worktree is a LEASE on a branch for one task, and the decision is ONE function,
  :func:`dev_lab.dev.reclaim.reclaimable`: a linked tree goes only when it is unlocked, no TRACKED file is
  changed (staged or not), its content is LANDED on the trunk or a declared session (``git cherry``, or a
  squash merge whose origin ref is gone) and no process occupies it. Its run outputs are moved home and
  VERIFIED first -- chained, never after a ``;`` -- then it is deleted and pruned; its branch then goes
  through ``branchset --apply``.
* a directory under ``.claude/worktrees/`` that git does not register: judged the same way, then deleted.
* every main-checkout session start, and every merge, checkout and push in any tree, runs it in the background
  (:mod:`dev_lab.dev.reclaimrun`), logged.
* ``--prune`` under a Claude Code hook payload (:func:`hook_payload`) never runs inline: INCIDENT 2026-11-12, old
  worktrees still carry a retired SessionStart row running it synchronously (6+ min over 108 trees), so it detaches
  that same locked, batched background reclaim of the main checkout and returns at once.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Final, TextIO

from lab_commons.census import processes
from lab_commons.log import emit

from dev_lab.dev import reclaimrun
from dev_lab.dev.backgroundrun import repo_main
from dev_lab.dev.branchset import BranchSetNotDeclared, apply_local, declared_branchset, holders
from dev_lab.dev.checkout import authority_for, worktrees
from dev_lab.dev.liverun import Census, describe, removal_holders
from dev_lab.dev.reclaim import QUIET_S, blockers, reclaim, removed_approved
from dev_lab.dev.worktree_archive import (
    archive,
    archive_door,
    current_archive,
    linked,
    unheld_head,
)

__all__ = ['HOOK_READ_S', 'blockers', 'hook_payload', 'main', 'prune', 'remove']

#: The longest a ``--prune`` waits on a piped stdin for a hook payload before running as a person's door.
HOOK_READ_S: Final = 1.0


def prune(
    root: Path,
    *,
    apply: bool,
    occupied: Callable[[Path], bool] | None = None,
) -> tuple[str, ...] | None:
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


def remove(root: Path, name: str, *, census: Census = processes, quiet_s: float = QUIET_S) -> tuple[bool, str]:
    """THE ARCHIVED-TREE REMOVAL DOOR: remove linked worktree *name*, branch or detached; ``(removed, the line)``.

    Refused, nothing touched: no linked tree of that name (the main checkout never is one); a process holding it
    (the REMOVAL lock, :func:`dev_lab.dev.liverun.removal_holders`); a detached commit no ref contains (the archive
    saves no commit); no saved archive that holds the tree as it is NOW
    (:func:`dev_lab.dev.worktree_archive.current_archive` -- the refusal names ``--archive``). Then the same
    all-or-nothing delete ``branchset --discard`` uses (:func:`dev_lab.dev.reclaim.removed_approved`), whose own
    refusals stand: a live session, outputs that cannot move home. A branch stays for ``branchset --apply``.
    """
    main = root.resolve()
    tree = linked(main, name)
    if isinstance(tree, str):
        return False, f'refused  {name}: {tree}; nothing was removed'
    if live := removal_holders(tree, census=census):
        return False, f'refused  {name}: the tree is live; nothing was removed\n{describe(live)}'
    if head := unheld_head(tree):
        return False, f'refused  {name}: detached {head} -- no ref contains it; branch or tag it, then archive again'
    saved, why = current_archive(main, tree, name)
    if saved is None:
        return False, f'refused  {name}: {why}; archive it first: {archive_door(main, name)}'
    if why := removed_approved(main, tree, quiet_s=quiet_s):
        wait = f'; re-run once it has been quiet {quiet_s / 60:g} min' if why.startswith('index changed') else ''
        return False, f'refused  {name}: {why}{wait}'
    return True, f'removed  {tree}  (its work is saved in {saved}; a branch it held stays for branchset --apply)'


def hook_payload(stdin: TextIO, *, wait_s: float = HOOK_READ_S) -> dict[str, object] | None:
    """The Claude Code hook payload on *stdin* (a JSON object naming ``hook_event_name``); ``None`` otherwise.

    A terminal is never a hook. A pipe is read on a daemon thread for at most *wait_s*, so a stdin left open
    and empty (an agent's shell) costs that bound and reads as no hook.
    """
    with contextlib.suppress(AttributeError, ValueError, OSError):
        if stdin.isatty():
            return None
    box: list[str] = []
    reader = threading.Thread(target=lambda: box.append(stdin.read()), daemon=True)
    reader.start()
    reader.join(wait_s)
    try:
        payload = json.loads(box[0]) if box else None
    except ValueError:
        return None
    return payload if isinstance(payload, dict) and 'hook_event_name' in payload else None


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None) -> int:
    """List worktrees and leftovers; ``--prune`` removes the clean ones. Exit 1 on a failure, 2 when unread."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.worktrees', description=main.__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument(
        '--prune',
        action='store_true',
        help='reclaim landed, unoccupied worktrees with no tracked change, run outputs moved home; never origin',
    )
    parser.add_argument(
        '--archive',
        action='append',
        default=[],
        metavar='NAME',
        help='move the outputs of worktree NAME home and save its work (worktree_archive); removes nothing',
    )
    parser.add_argument(
        '--remove',
        action='append',
        default=[],
        metavar='NAME',
        help='remove worktree NAME (branch or detached) once --archive NAME saved it as it is now',
    )
    args = parser.parse_args(argv)
    if args.remove:
        removed = [remove(args.root, name) for name in args.remove]
        for _, line in removed:
            emit(line)
        return 0 if all(ok for ok, _ in removed) else 1
    if args.archive:
        done = [archive(args.root.resolve(), name) for name in args.archive]
        for line in (line for one in done for line in one.lines()):
            emit(line)
        return 0 if all(one.safe for one in done) else 1
    if args.prune and (payload := hook_payload(stdin or sys.stdin)) is not None:
        root = repo_main(Path(str(payload.get('cwd') or args.root)))
        with contextlib.suppress(OSError):  # a hook never blocks or fails the session it serves
            if root is not None:
                reclaimrun.detach(root)
        return 0
    lines = prune(args.root.resolve(), apply=args.prune)
    if lines is None:
        emit(f'git could not read the worktrees of {args.root}; nothing was touched')
        return 2
    for line in lines:
        emit(line)
    return 1 if any(line.startswith('FAILED') for line in lines) else 0


if __name__ == '__main__':
    raise SystemExit(main())
