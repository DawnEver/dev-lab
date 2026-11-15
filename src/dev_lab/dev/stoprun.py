"""STOP ONE OWN RUN: ``python -m dev_lab.dev.stoprun --pid PID [--repo PATH] [--dry-run]``.

Generalised 2026-10-04 from a consumer's process-tree killer (its ``--pid`` mode) (AUTO-MODE-RUNS-THE-DOORS):
an agent stopping its OWN superseded run was refused as a raw ``taskkill /T /F``. The door replaces the
raw kill with a checked one: the NORMAL path REFUSES unless the pid's command line is a run it can identify
(:data:`~dev_lab.dev.stoprules.RUN_SIGNATURES` -- the family verify, a gate runner, pytest, a ``forge serve`` --
plus any the repo declares), and then stops that pid's subtree only, children first, never an ancestor or a sibling.
Local only.

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
  worker (:data:`~dev_lab.dev.stoprules.BUILTIN_ORPHANS`)::

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
import hashlib
import os
import re
import shutil
import signal
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from lab_commons.box.ledger import holdings
from lab_commons.census import processes
from lab_commons.liveness import CreationClock, creation_stamp
from lab_commons.log import emit
from lab_commons.proc import descendants, pid_alive

from dev_lab.dev import stoprules
from dev_lab.dev.checkout import git_out
from dev_lab.dev.servelock import note_stopped

__all__ = [
    'SERVE_GRACE_S',
    'ApprovedRun',
    'main',
    'process_table',
    'repo_root',
    'stop',
]


#: How long a serve whose producers were stopped may take to release its claim and exit, in seconds.
SERVE_GRACE_S: Final = 60.0


def process_table() -> dict[int, stoprules.Proc]:
    """``{pid: (ppid, cmdline)}`` for every process, from the one census (:mod:`lab_commons.census`)."""
    return {one.pid: (one.ppid, one.command_line) for one in processes()}


@dataclass(frozen=True)
class ApprovedRun:
    """The caller's explicit user authorization and exact root identity, not proof of ownership.

    Select the actual Python controller, not a venv launcher that merely waits for it. All facts
    are mandatory and single-use observations: execution rechecks them, even after a dry run.
    """

    created: int
    command_sha256: str
    user_words: str

    def __post_init__(self) -> None:
        """Reject an incomplete authorization before any process is observed or stopped."""
        if type(self.created) is not int or self.created <= 0:
            msg = 'approved created must be a positive exact integer creation stamp'
            raise ValueError(msg)
        if not isinstance(self.command_sha256, str) or re.fullmatch(r'[0-9a-f]{64}', self.command_sha256) is None:
            msg = 'approved command_sha256 must name the exact complete command line as lowercase SHA256'
            raise ValueError(msg)
        if not isinstance(self.user_words, str) or not self.user_words.strip():
            msg = 'approved user_words must contain the actual explicit user authorization'
            raise ValueError(msg)


def repo_root(start: Path) -> Path:
    """The git top level containing *start*, else *start* itself."""
    top = git_out(start, 'rev-parse', '--show-toplevel')
    return Path(top.strip()) if top and top.strip() else start


def _claimed() -> set[int]:
    """The pids holding a claim in this machine's box ledger now."""
    return {held.pid for held in holdings()}


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


def _command_hash(command: str) -> str:
    return hashlib.sha256(command.encode('utf-8')).hexdigest()


@dataclass
class _ApprovedTree:
    """One bounded original process snapshot and the parents this invocation proved stopped."""

    root: int
    table: Mapping[int, stoprules.Proc]
    members: frozenset[int]
    stamps: dict[int, int | None]
    stopped: set[int]

    @classmethod
    def capture(
        cls,
        pid: int,
        table: Mapping[int, stoprules.Proc],
        approved: ApprovedRun,
        born: CreationClock,
        *,
        signatures: tuple[str, ...],
        orphans: tuple[str, ...],
    ) -> _ApprovedTree:
        """Reuse the process owner's refuted-edge closure, then require positive identity proof."""
        stamps: dict[int, int | None] = {}

        def observed(member: int) -> int | None:
            if member not in stamps:
                stamps[member] = born(member)
            return stamps[member]

        if observed(pid) != approved.created or _command_hash(table[pid][1]) != approved.command_sha256:
            msg = 'approved root creation stamp or complete command identity disagrees'
            raise ValueError(msg)
        if stoprules.why_stoppable(table, pid, signatures, born) is not None:
            raise ValueError(stoprules.ordinary_lifecycle_door(pid))
        rows = {member: (row[1], row[0]) for member, row in table.items()}
        members = descendants(pid, rows, observed)
        if any(type(observed(member)) is not int or observed(member) <= 0 for member in members):
            msg = 'an approved subtree member has no readable creation stamp'
            raise ValueError(msg)
        if any(not table[member][1].strip() for member in members):
            msg = 'an approved subtree member has no readable complete command'
            raise ValueError(msg)
        for member in members:
            command = table[member][1]
            if (
                stoprules.SERVE.search(command)
                or stoprules.orphan_role(command, orphans)
                or stoprules.orphaned_worker(table, member, born) is not None
            ):
                raise ValueError(stoprules.ordinary_lifecycle_door(member))
        return cls(pid, dict(table), members, stamps, set())

    def changed(self, fresh: Callable[[], Mapping[int, stoprules.Proc]], born: CreationClock) -> str | None:
        """Refuse an unreadable fresh census rather than killing against an old observation."""
        try:
            return self._changed(fresh(), born)
        except OSError as exc:
            return f'the fresh process identity is unreadable: {exc}'

    def _changed(self, current: Mapping[int, stoprules.Proc], born: CreationClock) -> str | None:
        """The exact original members remain; only a proved stopped parent licenses reparenting."""
        for member in self.members - self.stopped:
            if member not in current:
                return f'original member {member} disappeared before its identity could be proved'
            if never := stoprules.never(member, current):
                return never
            if born(member) != self.stamps[member] or _command_hash(current[member][1]) != _command_hash(
                self.table[member][1]
            ):
                return f'original member {member} changed creation stamp or complete command'
            parent = self.table[member][0]
            if current[member][0] != parent and parent not in self.stopped:
                return f'original member {member} changed parent while its proved parent was not stopped'
        current_rows = {member: (row[1], row[0]) for member, row in current.items()}
        # Keep only the ORIGINAL proved edges through stopped/reparented members. Never walk a
        # new parent. These virtual rows diagnose growth; they never authorize an extra kill.
        current_rows.update({member: (row[1], row[0]) for member, row in self.table.items() if member in self.members})
        growth = (
            descendants(
                self.root,
                current_rows,
                lambda member: self.stamps[member] if member in self.stopped else born(member),
            )
            - self.members
        )
        if growth:
            return (
                f'additional processes below the recorded parent identities: {sorted(growth)}; '
                'no new member is authorized. Inspect them and use their recognized run door or a new exact approval'
            )
        return None


def _stop_approved(
    pid: int,
    table: Mapping[int, stoprules.Proc],
    approved: ApprovedRun,
    *,
    dry_run: bool,
    born: CreationClock,
    fresh: Callable[[], Mapping[int, stoprules.Proc]],
    kill: Callable[[int], None],
    gone: Callable[[int, float], bool],
    signatures: tuple[str, ...],
    orphans: tuple[str, ...],
) -> tuple[int, list[str]]:
    """Cut the actual controller first; every later uncertainty reports partial, never atomic success."""
    try:
        tree = _ApprovedTree.capture(pid, table, approved, born, signatures=signatures, orphans=orphans)
    except (ValueError, OSError) as exc:
        return 3, [f'refused: {exc}']
    if why := tree.changed(fresh, born):
        return 3, [f'refused: {why}']
    lines = ['user-authorized exact controller identity; this assertion is not session ownership proof']
    order = [pid, *(member for member in stoprules.subtree(table, pid) if member != pid and member in tree.members)]
    for member in order:
        if why := tree.changed(fresh, born):
            prefix = 'partial: stopped no further process' if tree.stopped else 'refused'
            return 3, [*lines, f'{prefix}: {why}']
        if dry_run:
            lines.append(
                f'would stop {member} created={tree.stamps[member]} command_sha256={_command_hash(table[member][1])}'
            )
            continue
        try:
            kill(member)
            exited = gone(member, 2.0)
        except OSError as exc:
            return 3, [*lines, f'partial: stopping {member} was not confirmed: {exc}; no further kill']
        if not exited:
            return 3, [*lines, f'partial: stop requested for {member}, but exit was not confirmed; no further kill']
        tree.stopped.add(member)
        lines.append(f'stopped {member} created={tree.stamps[member]} command_sha256={_command_hash(table[member][1])}')
    why = tree.changed(fresh, born)
    return (3, [*lines, f'partial: the original stop sequence ended, but {why}']) if why else (0, lines)


def stop(
    pid: int,
    table: Mapping[int, stoprules.Proc],
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
    fresh: Callable[[], Mapping[int, stoprules.Proc]] = process_table,
) -> tuple[int, list[str]]:
    """Stop *pid*'s subtree if it is an identifiable run or a stoppable orphan. ``(exit code, lines)``; 3 refused."""
    if never := stoprules.never(pid, table):
        return 3, [f'refused: {never}']
    if approved is not None:
        return _stop_approved(
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
    matched = stoprules.why_stoppable(table, pid, signatures, born)
    if matched is None:
        if why := stoprules.orphan_refusal(pid, table, orphans, claimed, born):
            return 3, stoprules.refusal(table, pid, why, os.getpid() if me is None else me, manifest)
        lines = [f'an orphan: its parent is gone and it holds no box claim: {table[pid][1][:120]!r}']
    else:
        lines = [f'matched signature {matched!r}']
    return _stop_identified_subtree(
        pid, table, matched, lines, dry_run=dry_run, kill=kill, gone=gone, notes=notes, born=born
    )


def _stop_identified_subtree(
    pid: int,
    table: Mapping[int, stoprules.Proc],
    matched: str | None,
    lines: list[str],
    *,
    dry_run: bool,
    kill: Callable[[int], None],
    gone: Callable[[int, float], bool],
    notes: Path | None,
    born: CreationClock,
) -> tuple[int, list[str]]:
    """The existing signature/orphan behavior: children first, with the serve release grace."""
    serve = matched == stoprules.SERVE.pattern
    # Each member's creation stamp as the snapshot saw it: a pid recycled during the serve grace is not ours.
    stamps = {member: born(member) for member in stoprules.subtree(table, pid)} if not dry_run else {}
    if serve and not dry_run:
        for child in (p for p, (ppid, *_) in table.items() if ppid == pid and p != pid):
            note_stopped(child, root=notes)
    for member in stoprules.subtree(table, pid):
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
        signatures=stoprules.declared_signatures(root),
        orphans=stoprules.declared_orphans(root),
        manifest=str(root / 'pyproject.toml'),
        approved=approved,
    )
    for line in lines:
        emit(f'[stoprun] {line}', err=bool(code))
    return code


if __name__ == '__main__':
    sys.exit(main())
