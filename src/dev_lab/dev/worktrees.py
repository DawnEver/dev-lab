"""The LOCAL WORKTREE CLEANUP DOOR: ``python -m dev_lab.dev.worktrees [--root R] [--prune [--limit N]]``.

User rulings 2026-10-04 (AUTO-MODE-RUNS-THE-DOORS): local cleanup is a checked door an agent may run
unattended and nothing here pushes or touches origin. D31 (2026-11-17): the work is what git
tracks plus every untracked, not-ignored file; only what git IGNORES goes with the tree. User ruling
2026-11-12: reclaiming useless trees is a REQUIRED part of the workflow, so a reclaimable tree's run outputs
move home, verified, before it goes.
``--remove NAME`` (:func:`remove`) is the ONE door for removing a named tree on a branch or DETACHED (wall
2026-11-17: ``branchset --discard`` takes a branch): it removes a tree holding nothing unlanded, its outputs moved
home first, and refuses one holding work with that work's doors. D31 (user, 2026-11-17) retired ``--archive``,
which saved a tree's work aside: a worktree's work is MERGED or the tree CLEANED, never parked.
``--salvage NAME`` (user ruling 2026-11-24, :mod:`dev_lab.dev.salvage`) records a dirty tree's work as a commit on
``salvage/<name>`` by plumbing, no hook judging it; ``--remove`` then takes a tree whose content IS that record
without the quiet wait. ``--reap-orphans`` removes a home directory git lists nowhere whose gitdir vanished, once
every file in it is reachable.

A THROWAWAY CHECKOUT (2026-11-10, a consumer, three times in one day: a detached base tree made to diff tests
against was kept by reclaim as ``not landed`` and refused to ``git worktree remove``, so each needed the user):
``--scratch NAME SHA`` makes it DETACHED under the worktree home and declares it DISPOSABLE; ``--discard NAME``
removes it now (:func:`dev_lab.dev.scratchtree.discard`), and ``--prune`` once it is quiet. Disposable means its
untracked content is scratch and it waits for no landing -- never that a tracked change, a commit no ref holds,
a lock or a live process may go with it.

THE INCIDENT IT ENCODES (a consumer, 2026-10-04): a cleanup loop ran ``mkdir -p "$D" && mv output "$D"``
and then ``; git worktree remove --force``. The archive helper failed, ``mv`` never ran, and the ``;``
let the removal delete five worktrees' ignored ``output/``. So:

* a worktree is a LEASE on a branch for one task, and the decision is ONE function,
  :func:`dev_lab.dev.reclaim.reclaimable`: a linked tree goes only when it is unlocked, holds nothing unlanded
  (:func:`dev_lab.dev.reclaim.unlanded_work`), its content is LANDED on the trunk or a declared session
  (``git cherry``, or a squash merge whose origin ref is gone) and no process occupies it. Its run outputs are
  moved home and VERIFIED first -- chained, never after a ``;`` -- then it is deleted and pruned; its branch then goes
  through ``branchset --apply``.
* a directory under ``.claude/worktrees/`` that git does not register: judged the same way, then deleted.
* every main-checkout session start, and every merge, checkout and push in any tree, runs it in the background
  (:mod:`dev_lab.dev.reclaimrun`), logged.
* ``--prune`` under a Claude Code hook payload (:func:`hook_payload`) never runs inline: INCIDENT 2026-11-12, old
  worktrees still carry a retired SessionStart row running it synchronously (6+ min over 108 trees), so it detaches
  that same locked, batched background reclaim of the main checkout and returns at once.
* ``--prune`` removes at most ``--limit N`` trees per run (default :data:`dev_lab.dev.reclaimrun.BATCH`; ``0``: no
  bound), the rest ``deferred`` with a ``next`` line naming the run that takes them. WALL 2026-11-17: an unbounded
  prune over ~90 trees outran an agent's 50-minute shell. MEASURED on 94 trees: judging them all took ~4.4 min
  (about 40% of it the per-tree process scan), and each removal deletes a tree's ~12.8k files (its ``.venv``),
  ~12 s apiece -- the removals are the part that grows without bound.
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
from dev_lab.dev.checkout import authority_for, git_out, worktrees
from dev_lab.dev.liverun import Census, describe, removal_holders
from dev_lab.dev.reclaim import QUIET_S, blockers, reclaim, removed_approved, unlanded_work
from dev_lab.dev.salvage import reap_orphans, salvage, salvaged
from dev_lab.dev.scratchtree import discard, scratch
from dev_lab.dev.worktree_outputs import linked, unheld_head, worktrees_door

__all__ = ['HOOK_READ_S', 'RETIRED_ARCHIVE', 'blockers', 'hook_payload', 'main', 'prune', 'remove']

#: RETIRED-NAMES-REGISTERED: the flag D31 retired, refused by name with its doors, never parsed as unknown.
RETIRED_ARCHIVE: Final = (
    '[worktrees] `--archive` is retired (D31, 2026-11-17): a worktree is merged or cleaned, its work never saved '
    'aside. Commit its work on its branch and land it through a PR; `--remove NAME` removes a tree holding nothing '
    'unlanded; the user discards an unlanded lane: python -m dev_lab.dev.branchset --discard <branch> --approved '
    '"<the user words>"'
)

#: The longest a ``--prune`` waits on a piped stdin for a hook payload before running as a person's door.
HOOK_READ_S: Final = 1.0


def prune(
    root: Path,
    *,
    apply: bool,
    occupied: Callable[[Path], bool] | None = None,
    limit: int | None = None,
) -> tuple[str, ...] | None:
    """One line per linked worktree and orphan directory; with *apply*, reclaim them. ``None``: unreadable.

    The decision is :func:`dev_lab.dev.reclaim.reclaimable`. In a repo that declares its branch set the
    holders are its trunk and sessions, and *apply* runs :func:`dev_lab.dev.branchset.apply_local`, so a
    reclaimed tree's branch goes with it; otherwise the one holder is the main checkout's branch on origin.
    *limit* bounds the removals of one run; the rest are ``deferred`` lines, taken by the next run.
    """
    try:
        branchset = declared_branchset(root)
    except BranchSetNotDeclared:
        trees = worktrees(root)
        if not trees:
            return None
        return reclaim(root, (authority_for(root, trees[0][1]),), occupied=occupied, apply=apply, limit=limit)
    if apply:
        return apply_local(root, branchset, occupied=occupied, limit=limit)
    return reclaim(root, holders(root, branchset), occupied=occupied, apply=False)


def _next_batch(root: Path, lines: tuple[str, ...], limit: int | None) -> tuple[str, ...]:
    """The line naming the run that takes the next batch, when this one deferred any; else nothing."""
    deferred = sum(line.startswith('deferred') for line in lines)
    if not deferred or limit is None:
        return ()
    door = worktrees_door(root, f'--prune --limit {limit}')
    return (f'next     {deferred} deferred past the batch of {limit}; run it again to take the next: {door}',)


def _standing(main: Path, name: str) -> Path | tuple[bool, str]:
    """Linked tree *name* when its directory stands; else the removal's whole answer.

    dev-lab#791: a timed-out removal left the record but not the directory, and the next ``--remove`` crashed in
    ``unheld_head``. A gone directory holds nothing, so its stale record is pruned.
    """
    tree = linked(main, name)
    if isinstance(tree, str):
        return False, f'refused  {name}: {tree}; nothing was removed'
    if tree.is_dir():
        return tree
    if git_out(main, 'worktree', 'prune') is None:
        return False, f'refused  {name}: {tree} is already gone and git could not prune its record'
    return True, f'removed  {tree}  (its directory was already gone; its stale record was pruned)'


def remove(root: Path, name: str, *, census: Census = processes, quiet_s: float = QUIET_S) -> tuple[bool, str]:
    """THE NAMED-TREE REMOVAL DOOR: remove linked worktree *name*, branch or detached; ``(removed, the line)``.

    Refused, nothing touched: no linked tree of that name (the main checkout never is one); a process holding it
    (the REMOVAL lock, :func:`dev_lab.dev.liverun.removal_holders`); a detached commit no ref contains; unlanded
    work in it -- a tracked change or an untracked, not-ignored file (:func:`dev_lab.dev.reclaim.unlanded_work`),
    named with its doors (D31: merged or cleaned, never parked). Then the same
    all-or-nothing delete ``branchset --discard`` uses (:func:`dev_lab.dev.reclaim.removed_approved`), whose own
    refusals stand: a live session, outputs that cannot move home. A branch stays for ``branchset --apply``.
    """
    main = root.resolve()
    tree = _standing(main, name)
    if isinstance(tree, tuple):
        return tree
    if live := removal_holders(tree, census=census):
        return False, f'refused  {name}: the tree is live; nothing was removed\n{describe(live)}'
    if head := unheld_head(tree):
        return False, f'refused  {name}: detached {head} -- no ref contains it; branch it and land it through a PR'
    recorded = salvaged(tree, name)
    if not recorded and (work := unlanded_work(tree)):
        return False, f'refused  {name}: {work}; nothing was removed'
    if why := removed_approved(main, tree, quiet_s=0 if recorded else quiet_s):
        wait = f'; re-run once it has been quiet {quiet_s / 60:g} min' if why.startswith('index changed') else ''
        return False, f'refused  {name}: {why}{wait}'
    return True, f'removed  {tree}  (it held nothing unlanded; a branch it held stays for branchset --apply)'


def hook_payload(stdin: TextIO, *, wait_s: float = HOOK_READ_S) -> dict[str, object] | None:
    """The Claude Code hook payload on *stdin* (a JSON object naming ``hook_event_name``); ``None`` otherwise.

    A terminal is never a hook. A pipe is read on a daemon thread for at most *wait_s*, so a stdin left open
    and empty (an agent's shell) costs that bound and reads as no hook.
    """
    with contextlib.suppress(AttributeError, ValueError, OSError):
        if stdin.isatty():
            return None
    box: list[str] = []

    def read() -> None:  # a stdin that refuses a read (pytest's captured one) is no hook, not a thread crash
        with contextlib.suppress(OSError, ValueError):
            box.append(stdin.read())

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(wait_s)
    try:
        payload = json.loads(box[0]) if box else None
    except ValueError:
        return None
    return payload if isinstance(payload, dict) and 'hook_event_name' in payload else None


def _named(args: argparse.Namespace) -> int | None:
    """Run the doors that act on named trees or orphans; their exit code, or ``None`` when none was asked."""
    if args.scratch or args.discard:
        made = [scratch(args.root.resolve(), *args.scratch)] if args.scratch else []
        lines = made + [discard(args.root.resolve(), name) for name in args.discard]
        for line in lines:
            emit(line)
        return 1 if any(not line.startswith(('made', 'removed')) for line in lines) else 0
    if not (args.salvage or args.reap_orphans or args.remove):
        return None
    done = [salvage(args.root, name) for name in args.salvage or ()]
    reaped = reap_orphans(args.root, salvage=args.salvage is not None) if args.reap_orphans else ()
    done += [remove(args.root, name) for name in args.remove]
    for line in (*(line for _, line in done), *reaped):
        emit(line)
    return 0 if all(ok for ok, _ in done) and not any(line.startswith('FAILED') for line in reaped) else 1


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
        '--limit',
        type=int,
        default=reclaimrun.BATCH,
        metavar='N',
        help=f'with --prune: remove at most N trees per run, the rest deferred to the next (default '
        f'{reclaimrun.BATCH}; 0: no bound)',
    )
    parser.add_argument(
        '--remove',
        action='append',
        default=[],
        metavar='NAME',
        help='remove worktree NAME (branch or detached) holding nothing unlanded, its outputs moved home first',
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
    parser.add_argument(
        '--salvage',
        action='extend',
        nargs='*',
        default=None,
        metavar='NAME',
        help="record worktree NAME's work (tracked + untracked, ignored excluded) as a commit on salvage/NAME; "
        "no hook, nothing pushed, the tree untouched. Bare, with --reap-orphans: record each orphan's "
        'unreachable files on salvage/<dir> first, then reap it',
    )
    parser.add_argument(
        '--reap-orphans',
        action='store_true',
        help='remove home directories git lists nowhere whose gitdir vanished, once every file is reachable',
    )
    words = list(sys.argv[1:] if argv is None else argv)
    if any(word.partition('=')[0] == '--archive' for word in words):
        emit(RETIRED_ARCHIVE, err=True)
        return 2
    args = parser.parse_args(words)
    if (code := _named(args)) is not None:
        return code
    if args.prune and (payload := hook_payload(stdin or sys.stdin)) is not None:
        root = repo_main(Path(str(payload.get('cwd') or args.root)))
        with contextlib.suppress(OSError):  # a hook never blocks or fails the session it serves
            if root is not None:
                reclaimrun.detach(root)
        return 0
    limit = args.limit if args.limit > 0 else None
    lines = prune(args.root.resolve(), apply=args.prune, limit=limit)
    if lines is None:
        emit(f'git could not read the worktrees of {args.root}; nothing was touched')
        return 2
    for line in (*lines, *_next_batch(args.root.resolve(), lines, limit)):
        emit(line)
    return 1 if any(line.startswith('FAILED') for line in lines) else 0


if __name__ == '__main__':
    raise SystemExit(main())
