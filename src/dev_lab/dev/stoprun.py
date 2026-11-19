"""STOP ONE OWN RUN: ``python -m dev_lab.dev.stoprun --pid PID [--repo PATH] [--dry-run]``.

Generalised 2026-10-04 from a consumer's process-tree killer (its ``--pid`` mode) (AUTO-MODE-RUNS-THE-DOORS):
an agent stopping its OWN superseded run was refused as a raw ``taskkill /T /F``. The door replaces the
raw kill with a checked one: the NORMAL path REFUSES unless the pid's command line is a run it can identify
(:data:`RUN_SIGNATURES` -- the family verify, a gate runner, pytest, a ``forge serve`` -- plus any the repo
declares), and then stops that pid's subtree only, children first, never an ancestor or a sibling. Local only.

An explicitly user-approved, otherwise unrecognized controller has a separate identity mode:
``--approved-created STAMP --approved-command-sha256 HASH --approved-user-words WORDS``. All three are
mandatory. It stops the verified actual controller FIRST so its child cannot cause the next file to launch.
The bounded original subtree is rechecked before each stop; uncertainty reports partial completion. This is
neither inferred session ownership nor atomic process control; see ``docs-src/dev/auto-doors.md``.

AN ORPHANED WORKER IS PROVEN, NOT RECOGNISED (2026-10-23). A child that outlives the run that started it is
unreachable by any signature: the root that identified it is gone. A multiprocessing worker names the process
it exists to serve (``spawn_main(parent_pid=N)``), so it is an orphan exactly when N is absent, or N was created
after the worker (the pid was reused). :func:`orphaned_worker` reads that from the table; a worker whose parent
lives is somebody's running pool and stays refused. A widened signature would trust the command line's shape
instead of this fact, so none is offered.

A ``forge serve`` IS STOPPED SO ITS CLAIM IS RELEASED: its producers are noted as stopped on purpose
(:func:`dev_lab.dev.servelock.note_stopped`) and stopped first, then the serve itself is given
:data:`SERVE_GRACE_S` to release the claim as ``error: stopped`` and exit before it is killed too.

A repo adds its own signatures as DATA, in ONE place -- its ``pyproject.toml`` (the repo of the cwd,
or ``--repo``)::

    [tool.dev_lab.stoprun]
    signatures = ["jcwrap"]   # regexes searched in the pid's own command line, like the built-ins

A declaration that is not a list of valid regex strings raises :class:`SignaturesNotDeclared`.

AN ORPHAN IS STOPPABLE TOO, BY THREE CONDITIONS THAT MUST ALL HOLD (added 2026-10-21: two orphaned JMAG
Designers, a node-side ``JobSystem.exe -s`` and a leftover ``scratch/`` shell watcher matched no run
signature, RAW-PROCESS-KILL forbade ``taskkill``, and the memory they held kept a box from admitting a solve):

* its PARENT IS GONE -- the ppid is absent, is init (POSIX reparents an orphan to pid 1), or is a younger
  process wearing the recycled number;
* NO BOX CLAIM is held by it or a descendant (:func:`lab_commons.box.ledger.holdings`; a Designer a claim
  was handed over to is that claim's, and is released through its own door). An unreadable ledger refuses;
* its command line is a DECLARED vendor tool, a ``scratch/`` script or a multiprocessing spawn/forkserver
  worker (:data:`BUILTIN_ORPHANS`)::

      [tool.dev_lab.stoprun]
      orphans = ["designer.exe.* --process-link", "JobSystem.exe -s "]

A refusal names the condition that failed -- a live parent is named, so the run it belongs to is stopped instead.
A REFUSAL IS NEVER BARE (2026-11-13: an agent got "no signature" and nothing to act on): it says WHAT the pid is
(its command line), WHO started it (its parent), whether it descends from this session (:func:`whose`), and the
exit -- ask the user, or declare the run's command line as a signature when it is a run of this repo.
``--dry-run`` names the signature that matched.

No new dependency: the process table is :func:`lab_commons.census.processes` (Win32 calls on Windows,
``/proc`` on Linux, ``ps -ww`` on macOS) -- the one census :mod:`dev_lab.dev.liverun` reads too;
:func:`stop` takes the table as an argument so a test can plant one.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import signal
import sqlite3
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from lab_commons.box.ledger import holdings
from lab_commons.liveness import CreationClock, creation_stamp
from lab_commons.log import emit
from lab_commons.proc import pid_alive

from dev_lab.dev.checkout import git_out
from dev_lab.dev.proctable import INIT, Proc, process_table, subtree, unstoppable, whose
from dev_lab.dev.servelock import note_stopped
from dev_lab.dev.stopapproved import ApprovedRun, stop_approved
from dev_lab.dev.stopsignatures import (
    BUILTIN_ORPHANS,
    SERVE,
    TABLE,
    declared_orphans,
    declared_signatures,
    orphan_role,
    why_stoppable,
)

__all__ = ['SERVE_GRACE_S', 'main', 'repo_root', 'stop', 'stop_subtree']

#: How long a serve whose producers were stopped may take to release its claim and exit, in seconds.
SERVE_GRACE_S: Final = 60.0


def repo_root(start: Path) -> Path:
    """The git top level containing *start*, else *start* itself."""
    top = git_out(start, 'rev-parse', '--show-toplevel')
    return Path(top.strip()) if top and top.strip() else start


def _claimed() -> set[int]:
    """The pids holding a claim in this machine's box ledger now."""
    return {held.pid for held in holdings()}


def _orphan_refusal(
    pid: int,
    table: Mapping[int, Proc],
    orphans: tuple[str, ...],
    claimed: Callable[[], set[int]],
    born: CreationClock,
) -> str | None:
    """Why *pid* is NOT a stoppable orphan, or ``None`` when it is (the module docstring's three conditions)."""
    cmdline = table[pid][1]
    if not orphan_role(cmdline, orphans):
        builtin = ', '.join(repr(sig.pattern) for sig in BUILTIN_ORPHANS)
        return f'no orphan signature either (built-in {builtin} or {TABLE} orphans)'
    ppid = table[pid][0]
    if ppid > INIT and ppid in table:  # POSIX reparents an orphan to init: its parent is gone
        parent, child = born(ppid), born(pid)
        if parent is None or child is None or parent <= child:
            return f'its parent {ppid} is alive ({table[ppid][1][:120]!r}) -- stop that run instead'
    try:
        held = claimed() & set(subtree(table, pid))
    except (OSError, sqlite3.Error) as exc:
        return f'the box ledger could not be read, so a claim cannot be ruled out: {exc}'
    if held:
        return f'{sorted(held)} holds a box claim -- release it through the door that took it'
    return None


#: The exit every refusal ends with: the two ways forward, never a bare "refused".
EXIT: Final = (
    'exit: ask the user to stop it, or -- when it is a run of this repo -- declare its command line as a regex in '
    '`{table} signatures = [...]` of {manifest}'
)


def _refusal(table: Mapping[int, Proc], pid: int, why: str, me: int, manifest: str) -> list[str]:
    """The refusal of *pid*: what it is, who started it, whose it is, and the exit."""
    ppid = table[pid][0]
    parent = f'{ppid} {table[ppid][1][:120]!r}' if ppid in table else f'{ppid} (gone)'
    return [
        f'refused: {pid} matches no run signature (built-in or {TABLE}) and {why}',
        f'what: {table[pid][1][:200]!r}',
        f'parent: {parent}',
        f'whose: {whose(table, pid, me)}',
        EXIT.format(table=TABLE, manifest=manifest),
    ]


def _kill(pid: int) -> None:
    if os.name == 'nt':
        _door.run(
            [shutil.which('taskkill') or 'taskkill', '/PID', str(pid), '/F'],
            capture_output=True,
            check=False,
            timeout=60,
        )
        return
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGTERM)


def _gone(pid: int, seconds: float) -> bool:
    """Whether *pid* exits within *seconds*."""
    deadline = time.monotonic() + seconds
    while pid_alive(pid):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.5)
    return True


def stop(
    pid: int,
    table: Mapping[int, Proc],
    *,
    dry_run: bool,
    kill: Callable[[int], None] = _kill,
    signatures: tuple[str, ...] = (),
    gone: Callable[[int, float], bool] = _gone,
    notes: Path | None = None,
    orphans: tuple[str, ...] = (),
    claimed: Callable[[], set[int]] = _claimed,
    born: CreationClock = creation_stamp,
    me: int | None = None,
    manifest: str = 'the repo`s pyproject.toml',
    approved: ApprovedRun | None = None,
    fresh: Callable[[], Mapping[int, Proc]] = process_table,
) -> tuple[int, list[str]]:
    """Stop *pid*'s subtree if it is an identifiable run or a stoppable orphan. ``(exit code, lines)``; 3 refused."""
    if never := unstoppable(pid, table):
        return 3, [f'refused: {never}']
    if approved is not None:
        return stop_approved(
            pid,
            table,
            approved,
            dry_run=dry_run,
            born=born,
            fresh=fresh,
            kill=kill,
            gone=gone,
            signatures=signatures,
            orphans=orphans,
        )
    matched = why_stoppable(table, pid, signatures, born)
    if matched is None:
        if why := _orphan_refusal(pid, table, orphans, claimed, born):
            return 3, _refusal(table, pid, why, os.getpid() if me is None else me, manifest)
        lines = [f'an orphan: its parent is gone and it holds no box claim: {table[pid][1][:120]!r}']
    else:
        lines = [f'matched signature {matched!r}']
    return stop_subtree(pid, table, matched, lines, dry_run=dry_run, kill=kill, gone=gone, notes=notes, born=born)


def stop_subtree(
    pid: int,
    table: Mapping[int, Proc],
    matched: str | None,
    lines: list[str],
    *,
    dry_run: bool,
    kill: Callable[[int], None] = _kill,
    gone: Callable[[int, float], bool] = _gone,
    notes: Path | None = None,
    born: CreationClock = creation_stamp,
) -> tuple[int, list[str]]:
    """Stop *pid*'s subtree children first, a member whose pid was recycled skipped; a serve gets its grace.

    The ONE tree-kill path: the identified-run and orphan modes reach it after :func:`stop` judged *pid*, and
    :mod:`dev_lab.dev.shellreaper` after its own judgement (an agent shell past its bound, no seat, no spare).
    """
    serve = matched == SERVE.pattern
    # Each member's creation stamp as the snapshot saw it: a pid recycled during the serve grace is not ours.
    stamps = {member: born(member) for member in subtree(table, pid)} if not dry_run else {}
    if serve and not dry_run:
        for child in (p for p, (ppid, *_) in table.items() if ppid == pid and p != pid):
            note_stopped(child, root=notes)
    for member in subtree(table, pid):
        if serve and member == pid and not dry_run and gone(pid, SERVE_GRACE_S):
            lines.append(f'serve {pid} released its claim and exited')
            continue
        if not dry_run and born(member) != stamps[member]:
            lines.append(f'skipped {member}: its pid now names another process (creation stamp moved)')
            continue
        lines.append(f'{"would stop" if dry_run else "stopped"} {member}  {table[member][1][:120]}')
        if not dry_run:
            kill(member)
    return 0, lines


def main(argv: list[str] | None = None) -> int:
    """Stop one identifiable run, or one orphan, and its subtree. Exit 3 when refused."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.stoprun', description=main.__doc__)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--repo', type=Path, default=None, help='repo whose pyproject declares signatures')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument(
        '--approved-created', type=int, help='creation stamp of the explicitly user-approved controller'
    )
    parser.add_argument('--approved-command-sha256', help='SHA256 of its complete command line, without normalization')
    parser.add_argument('--approved-user-words', help='the actual explicit user authorization; not inferred ownership')
    args = parser.parse_args(argv)
    facts = (args.approved_created, args.approved_command_sha256, args.approved_user_words)
    approved = None
    if any(fact is not None for fact in facts):
        if any(fact is None for fact in facts):
            parser.error('approved-created, approved-command-sha256 and approved-user-words must be supplied together')
        try:
            approved = ApprovedRun(*facts)
        except ValueError as exc:
            parser.error(str(exc))
    root = args.repo or repo_root(Path.cwd())
    code, lines = stop(
        args.pid,
        process_table(),
        dry_run=args.dry_run,
        signatures=declared_signatures(root),
        orphans=declared_orphans(root),
        manifest=str(root / 'pyproject.toml'),
        approved=approved,
    )
    for line in lines:
        emit(f'[stoprun] {line}', err=bool(code))
    return code


if __name__ == '__main__':
    sys.exit(main())
